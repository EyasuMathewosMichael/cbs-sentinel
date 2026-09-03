from datetime import UTC, datetime
from decimal import Decimal

from sentinel.domain.integrity import (
    IntegrityDecision,
    IntegrityDecisionCode,
    TransactionRequest,
)
from sentinel.domain.protection import (
    ProtectiveAction,
    ProtectiveActionConflict,
    ProtectiveResponseEngine,
    RecoveryContext,
)
from sentinel.domain.risk import RiskEngine, RiskSignal
from sentinel.domain.transactions import Transaction, TransactionState


def transaction_in_state(state: TransactionState) -> Transaction:
    transaction = Transaction("txn-protection")
    if state in {TransactionState.UNKNOWN, TransactionState.TIMEOUT}:
        for next_state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            state,
        ):
            transaction.transition(next_state)
    elif state is TransactionState.PARTIAL_FAILURE:
        for next_state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.CBS_PROCESSING,
            state,
        ):
            transaction.transition(next_state)
    return transaction


def test_low_risk_allows_without_executing_an_action():
    transaction = Transaction("txn-allow")
    risk = RiskEngine().evaluate(
        request=TransactionRequest(
            "txn-allow", "idem-allow", "source", "destination", Decimal("10"), "ETB"
        )
    )

    decision = ProtectiveResponseEngine().decide(transaction, risk_assessment=risk)

    assert decision.action is ProtectiveAction.ALLOW
    assert transaction.state is TransactionState.RECEIVED


def test_risk_actions_are_hold_and_manual_review():
    request = TransactionRequest(
        "txn-risk", "idem-risk", "source", "destination", Decimal("10"), "ETB"
    )
    engine = RiskEngine()
    response_engine = ProtectiveResponseEngine()

    hold = response_engine.decide(
        Transaction("txn-risk"),
        risk_assessment=engine.evaluate(
            request,
            RiskSignal(velocity_count=5, transaction_frequency=10),
        ),
    )
    review = response_engine.decide(
        Transaction("txn-high"),
        risk_assessment=engine.evaluate(
            request,
            RiskSignal(
                system_anomaly=True,
                unusual_device=True,
                velocity_count=5,
                transaction_frequency=10,
            ),
        ),
    )

    assert hold.action is ProtectiveAction.HOLD
    assert review.action is ProtectiveAction.MANUAL_REVIEW


def test_unknown_always_blocks_retry_and_requires_verification():
    decision = ProtectiveResponseEngine().decide(
        transaction_in_state(TransactionState.UNKNOWN),
        recovery=RecoveryContext(retry_safe=True),
    )

    assert decision.action is ProtectiveAction.BLOCK_RETRY
    assert "uncertain" in decision.reason


def test_timeout_is_uncertain_and_cannot_be_retried():
    transaction = transaction_in_state(TransactionState.TIMEOUT)

    decision = ProtectiveResponseEngine().decide(
        transaction,
        recovery=RecoveryContext(retry_safe=True),
    )

    assert decision.action is ProtectiveAction.BLOCK_RETRY


def test_retry_requires_explicit_safe_classification_and_known_state():
    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-safe-retry"),
        recovery=RecoveryContext(retry_safe=True),
    )

    assert decision.action is ProtectiveAction.RETRY


def test_risk_record_for_another_transaction_requires_manual_review():
    request = TransactionRequest(
        "txn-risk-source", "idem-risk-source", "source", "destination", Decimal("10"), "ETB"
    )
    assessment = RiskEngine().evaluate(request)

    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-risk-target"),
        risk_assessment=assessment,
    )

    assert decision.action is ProtectiveAction.MANUAL_REVIEW
    assert "transaction" in decision.reason


def test_partial_failure_selects_reversal_compensation_or_reconciliation():
    engine = ProtectiveResponseEngine()
    transaction = transaction_in_state(TransactionState.PARTIAL_FAILURE)

    reversal = engine.decide(transaction, recovery=RecoveryContext(reversal_supported=True))
    compensation = engine.decide(transaction, recovery=RecoveryContext(compensation_supported=True))
    reconcile = engine.decide(transaction)

    assert reversal.action is ProtectiveAction.REVERSAL
    assert compensation.action is ProtectiveAction.COMPENSATION
    assert reconcile.action is ProtectiveAction.RECONCILE


def test_reversal_and_compensation_plans_are_idempotent():
    engine = ProtectiveResponseEngine()
    transaction = transaction_in_state(TransactionState.PARTIAL_FAILURE)

    first_reversal = engine.decide(
        transaction,
        recovery=RecoveryContext(reversal_supported=True),
        action_id="reverse-1",
    )
    second_reversal = engine.decide(
        transaction,
        recovery=RecoveryContext(reversal_supported=True),
        action_id="reverse-1",
    )
    first_compensation = engine.decide(
        transaction,
        recovery=RecoveryContext(compensation_supported=True),
        action_id="compensate-1",
    )
    second_compensation = engine.decide(
        transaction,
        recovery=RecoveryContext(compensation_supported=True),
        action_id="compensate-1",
    )

    assert first_reversal == second_reversal
    assert first_compensation == second_compensation
    assert first_reversal.action is ProtectiveAction.REVERSAL
    assert first_compensation.action is ProtectiveAction.COMPENSATION


def test_integrity_failure_has_priority_and_is_audited():
    integrity = IntegrityDecision(IntegrityDecisionCode.DUPLICATE_TRANSACTION, "txn-priority")
    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-priority"),
        integrity_decision=integrity,
        recovery=RecoveryContext(retry_safe=True),
    )

    assert decision.action is ProtectiveAction.REJECT
    assert decision.integrity_code == "DUPLICATE_TRANSACTION"
    assert decision.source == "protective-response-engine"


def test_system_anomaly_trips_circuit_breaker():
    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-circuit"),
        recovery=RecoveryContext(system_anomaly=True),
    )

    assert decision.action is ProtectiveAction.CIRCUIT_BREAK


def test_policy_retry_conflict_blocks_retry_when_not_safe():
    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-policy"),
        policy_action=ProtectiveAction.RETRY,
    )

    assert decision.action is ProtectiveAction.BLOCK_RETRY


def test_policy_action_is_overridden_by_circuit_breaker():
    decision = ProtectiveResponseEngine().decide(
        Transaction("txn-policy-circuit"),
        policy_action=ProtectiveAction.ALLOW,
        recovery=RecoveryContext(system_anomaly=True),
    )

    assert decision.action is ProtectiveAction.CIRCUIT_BREAK


def test_decision_record_is_reproducible_with_fixed_inputs():
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    engine = ProtectiveResponseEngine()
    first = engine.decide(Transaction("txn-record"), action_id="action-1", timestamp=timestamp)
    second = engine.decide(Transaction("txn-record"), action_id="action-1", timestamp=timestamp)

    assert first == second


def test_action_planning_without_explicit_id_is_idempotent():
    engine = ProtectiveResponseEngine()
    transaction = Transaction("txn-idempotent")

    first = engine.decide(transaction)
    second = engine.decide(transaction)

    assert first == second


def test_reusing_action_id_for_different_plan_is_rejected():
    engine = ProtectiveResponseEngine()
    transaction = Transaction("txn-conflict")

    engine.decide(transaction, action_id="action-conflict")

    try:
        engine.decide(
            transaction,
            recovery=RecoveryContext(retry_safe=True),
            action_id="action-conflict",
        )
    except ProtectiveActionConflict:
        pass
    else:
        raise AssertionError("conflicting action identity was accepted")