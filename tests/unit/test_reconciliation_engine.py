import asyncio
from datetime import UTC, datetime

from sentinel.adapters.cbs.contracts import (
    CBSAdapterCapabilities,
    ReconciliationResult,
    ReversalResult,
    TransactionStatus,
)
from sentinel.domain.reconciliation import ReconciliationEngine, ReconciliationOutcome
from sentinel.domain.transactions import Transaction, TransactionState


def evidence(transaction_id, status, source, destination, details="evidence"):
    return ReconciliationResult(
        transaction_id,
        status,
        source,
        destination,
        details,
        datetime.now(UTC),
    )


class ReversalAdapter:
    capabilities = CBSAdapterCapabilities(reversal=True, reconciliation=True)

    def __init__(self):
        self.calls = []

    async def request_reversal(self, transaction_id, *, reversal_transaction_id, idempotency_key):
        self.calls.append((transaction_id, reversal_transaction_id, idempotency_key))
        return ReversalResult(
            transaction_id,
            reversal_transaction_id,
            TransactionStatus.POSTED,
            "reverse-ref",
            datetime.now(UTC),
        )


class CompensationAdapter:
    capabilities = CBSAdapterCapabilities(compensation=True, reconciliation=True)


class CompensationHandler:
    def __init__(self):
        self.calls = []

    async def compensate(self, transaction_id, *, idempotency_key):
        self.calls.append((transaction_id, idempotency_key))
        return "compensation-ref"


def transaction_in(state):
    transaction = Transaction("txn-reconcile")
    if state is TransactionState.UNKNOWN:
        for next_state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.UNKNOWN,
        ):
            transaction.transition(next_state)
    elif state is TransactionState.PARTIAL_FAILURE:
        for next_state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.CBS_PROCESSING,
            TransactionState.PARTIAL_FAILURE,
        ):
            transaction.transition(next_state)
    return transaction


def test_reconciliation_classifies_success_failure_and_unknown():
    engine = ReconciliationEngine()

    success = engine.decide(
        Transaction("success"),
        evidence("success", TransactionStatus.POSTED, True, True),
    )
    failure = engine.decide(
        Transaction("failure"),
        evidence("failure", TransactionStatus.FAILED, False, False),
    )
    unknown = engine.decide(
        transaction_in(TransactionState.UNKNOWN),
        evidence("txn-reconcile", TransactionStatus.UNKNOWN, None, None),
        delayed_response=True,
    )

    assert success.outcome is ReconciliationOutcome.RECONCILED_SUCCESS
    assert failure.outcome is ReconciliationOutcome.RECONCILED_FAILURE
    assert unknown.outcome is ReconciliationOutcome.UNKNOWN_REQUIRES_INVESTIGATION
    assert "txn-reconcile" in engine.unresolved_transactions
    assert len(engine.decision_audit) == 3


def test_posting_matrix_fails_closed_for_inconsistent_effects():
    engine = ReconciliationEngine()
    cases = [
        ("credit-only", False, True),
        ("neither", False, False),
    ]

    for transaction_id, source, destination in cases:
        decision = engine.decide(
            Transaction(transaction_id),
            evidence(transaction_id, TransactionStatus.POSTED, source, destination),
        )
        assert decision.outcome is ReconciliationOutcome.MANUAL_REVIEW

    both = engine.decide(
        Transaction("both"),
        evidence("both", TransactionStatus.POSTED, True, True),
        duplicate_posting=True,
    )
    assert both.outcome is ReconciliationOutcome.MANUAL_REVIEW


def test_source_debit_without_destination_credit_requires_reversal():
    engine = ReconciliationEngine()
    decision = engine.decide(
        transaction_in(TransactionState.PARTIAL_FAILURE),
        evidence("txn-reconcile", TransactionStatus.POSTED, True, False),
    )

    assert decision.outcome is ReconciliationOutcome.REVERSAL_REQUIRED


def test_duplicate_posting_is_manual_review():
    engine = ReconciliationEngine()
    decision = engine.decide(
        Transaction("duplicate"),
        evidence("duplicate", TransactionStatus.POSTED, True, True),
        duplicate_posting=True,
    )

    assert decision.outcome is ReconciliationOutcome.MANUAL_REVIEW


def test_reversal_is_separately_identified_and_idempotent():
    engine = ReconciliationEngine()
    adapter = ReversalAdapter()
    transaction = transaction_in(TransactionState.PARTIAL_FAILURE)
    decision = engine.decide(
        transaction,
        evidence(transaction.transaction_id, TransactionStatus.POSTED, True, False),
    )

    async def recover_twice():
        first = await engine.recover(transaction, decision, adapter)
        second = await engine.recover(transaction, decision, adapter)
        return first, second

    first, second = asyncio.run(recover_twice())
    assert first == second
    assert len(adapter.calls) == 1
    assert adapter.calls[0][1].startswith("reversal-")


def test_compensation_requires_capability_and_is_idempotent():
    engine = ReconciliationEngine()
    adapter = CompensationAdapter()
    handler = CompensationHandler()
    transaction = transaction_in(TransactionState.PARTIAL_FAILURE)
    decision = engine.decide(
        transaction,
        evidence(transaction.transaction_id, TransactionStatus.POSTED, True, False),
    )
    decision = decision.__class__(
        transaction.transaction_id,
        ReconciliationOutcome.COMPENSATION_REQUIRED,
        "approved compensation",
        decision.observed_status,
        decision.source_debited,
        decision.destination_credited,
        decision.duplicate_posting,
        decision.decided_at,
    )

    async def recover_twice():
        first = await engine.recover(transaction, decision, adapter, compensation=handler)
        second = await engine.recover(transaction, decision, adapter, compensation=handler)
        return first, second

    first, second = asyncio.run(recover_twice())
    assert first == second
    assert len(handler.calls) == 1