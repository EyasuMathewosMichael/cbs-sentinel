import asyncio
from decimal import Decimal

from sentinel.adapters.cbs import CBSOperationTimeout, SimulatorCBSAdapter
from sentinel.adapters.cbs.contracts import TransactionStatus, TransactionSubmission, utc_now
from sentinel.application.orchestration import TransactionOrchestrator
from sentinel.domain.integrity import (
    IntegrityDecisionCode,
    IntegrityEngine,
    ProcessingObservation,
    TransactionRequest,
)
from sentinel.domain.protection import ProtectiveAction, ProtectiveResponseEngine
from sentinel.domain.risk import RiskEngine
from sentinel.domain.transactions import TransactionState


class Policy:
    async def decide(self, request, risk):
        return ProtectiveAction.ALLOW


class Reconciliation:
    def __init__(self):
        self.calls = []

    async def request_reconciliation(self, transaction):
        self.calls.append(transaction.transaction_id)


class Events:
    def __init__(self):
        self.events = []

    async def publish(self, event_type, transaction):
        self.events.append((event_type, transaction.state))


class TimeoutAdapter(SimulatorCBSAdapter):
    async def submit_transaction(self, request, *, idempotency_key):
        raise CBSOperationTimeout("timeout")


class PostedAdapter(SimulatorCBSAdapter):
    async def submit_transaction(self, request, *, idempotency_key):
        return TransactionSubmission(
            request.transaction_id,
            "cbs-posted-ref",
            TransactionStatus.POSTED,
            utc_now(),
        )


class FailedAdapter(SimulatorCBSAdapter):
    async def submit_transaction(self, request, *, idempotency_key):
        return TransactionSubmission(
            request.transaction_id,
            "cbs-failed-ref",
            TransactionStatus.FAILED,
            utc_now(),
        )


class InvalidPolicy:
    async def decide(self, request, risk):
        return "submit-anyway"


def make_request(transaction_id="txn-workflow"):
    return TransactionRequest(
        transaction_id,
        f"idem-{transaction_id}",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )


def make_orchestrator(adapter, policy=None):
    reconciliation = Reconciliation()
    events = Events()
    return (
        TransactionOrchestrator(
            adapter,
            IntegrityEngine(),
            RiskEngine(),
            ProtectiveResponseEngine(),
            policy or Policy(),
            reconciliation,
            events,
        ),
        reconciliation,
        events,
    )


def test_workflow_coordinates_validation_policy_cbs_and_events():
    orchestrator, reconciliation, events = make_orchestrator(SimulatorCBSAdapter())

    result = asyncio.run(orchestrator.process(make_request()))

    assert result.transaction.state is TransactionState.CBS_PROCESSING
    assert result.integrity.allowed
    assert result.protective.action is ProtectiveAction.ALLOW
    assert reconciliation.calls == []
    assert [event[0] for event in events.events] == [
        "transaction.received",
        "transaction.validating",
        "transaction.submitted",
        "transaction.processing",
    ]


def test_posted_cbs_response_reaches_posted_state():
    orchestrator, _, events = make_orchestrator(PostedAdapter())

    result = asyncio.run(orchestrator.process(make_request("txn-posted")))

    assert result.transaction.state.value == "POSTED"
    assert events.events[-1][0] == "transaction.posted"


def test_failed_cbs_response_reaches_failed_state():
    orchestrator, _, events = make_orchestrator(FailedAdapter())

    result = asyncio.run(orchestrator.process(make_request("txn-failed")))

    assert result.transaction.state is TransactionState.FAILED
    assert events.events[-1][0] == "transaction.failed"


def test_timeout_becomes_unknown_and_triggers_reconciliation_without_retry():
    orchestrator, reconciliation, events = make_orchestrator(TimeoutAdapter())

    result = asyncio.run(orchestrator.process(make_request()))

    assert result.transaction.state.value == "UNKNOWN"
    assert reconciliation.calls == ["txn-workflow"]
    assert "transaction.unknown" in [event[0] for event in events.events]


def test_integrity_failure_rejects_without_calling_cbs():
    class RejectingPolicy:
        async def decide(self, request, risk):
            raise AssertionError("policy must not run after integrity failure")

    orchestrator, _, events = make_orchestrator(SimulatorCBSAdapter(), RejectingPolicy())
    request = make_request()
    request = TransactionRequest(
        request.transaction_id,
        request.idempotency_key,
        request.source_account,
        request.destination_account,
        Decimal("0"),
        request.currency,
    )

    result = asyncio.run(orchestrator.process(request))

    assert result.integrity.code is IntegrityDecisionCode.INVALID_AMOUNT
    assert result.transaction.state.value == "MANUAL_REVIEW"
    assert events.events[-1][0] == "transaction.rejected"


def test_invalid_policy_action_fails_closed_to_manual_review():
    orchestrator, _, _ = make_orchestrator(SimulatorCBSAdapter(), InvalidPolicy())

    result = asyncio.run(orchestrator.process(make_request("txn-invalid-policy")))

    assert result.protective.action is ProtectiveAction.MANUAL_REVIEW
    assert result.transaction.state is TransactionState.MANUAL_REVIEW


def test_duplicate_request_is_rejected_before_second_cbs_submission():
    adapter = SimulatorCBSAdapter()
    orchestrator, _, _ = make_orchestrator(adapter)
    request = make_request("txn-duplicate")

    first = asyncio.run(orchestrator.process(request))
    second = asyncio.run(orchestrator.process(request))

    assert first.integrity.allowed
    assert second.integrity.code is IntegrityDecisionCode.DUPLICATE_TRANSACTION
    assert second.transaction.state is TransactionState.REJECTED


def test_partial_processing_is_not_treated_as_success():
    orchestrator, _, _ = make_orchestrator(SimulatorCBSAdapter())

    result = asyncio.run(
        orchestrator.process(
            make_request("txn-partial"),
            processing=ProcessingObservation(debit_posted=True, credit_posted=False),
        )
    )

    assert result.integrity.code.value == "PARTIAL_FAILURE"
    assert result.transaction.state is TransactionState.MANUAL_REVIEW
