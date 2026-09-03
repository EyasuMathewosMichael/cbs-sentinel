from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sentinel.domain.integrity import IntegrityDecision, IntegrityDecisionCode, TransactionRequest
from sentinel.domain.risk import RiskDecisionCode, RiskEngine, RiskRules, RiskSignal


def make_request(**overrides):
    values = {
        "transaction_id": "txn-risk-001",
        "idempotency_key": "idem-risk-001",
        "source_account": "acct-source",
        "destination_account": "acct-destination",
        "amount": Decimal("100.00"),
        "currency": "ETB",
    }
    values.update(overrides)
    return TransactionRequest(**values)


def test_low_risk_assessment_is_explainable_and_versioned():
    assessment = RiskEngine().evaluate(make_request())

    assert assessment.decision is RiskDecisionCode.LOW_RISK
    assert assessment.risk_score == 0
    assert assessment.rules_triggered == ()
    assert assessment.policy_version == "policy-v1"
    assert assessment.rule_version == "risk-rules-v1"
    assert assessment.model_version == "none"
    assert assessment.decision_id


def test_rules_score_risk_factors_deterministically():
    assessment = RiskEngine().evaluate(
        make_request(amount=Decimal("20000")),
        RiskSignal(
            velocity_count=5,
            transaction_frequency=10,
            previous_failures=1,
            retry_count=2,
            unusual_timing=True,
            unusual_channel=True,
            unusual_device=True,
            system_anomaly=True,
            account_history_score=5,
        ),
    )

    assert assessment.decision is RiskDecisionCode.HIGH_RISK
    assert assessment.risk_score == 100
    assert "HIGH_AMOUNT" in assessment.rules_triggered
    assert "SYSTEM_ANOMALY" in assessment.rules_triggered
    assert "ACCOUNT_HISTORY" in assessment.rules_triggered


def test_missing_signals_are_safe_defaults():
    assessment = RiskEngine().evaluate(make_request(), None)

    assert assessment.risk_score == 0
    assert assessment.rules_triggered == ()


@pytest.mark.parametrize(
    ("amount", "expected_score", "expected_decision"),
    [
        (Decimal("9999.99"), 0, RiskDecisionCode.LOW_RISK),
        (Decimal("10000"), 30, RiskDecisionCode.ELEVATED_RISK),
    ],
)
def test_amount_rule_boundary_is_inclusive(amount, expected_score, expected_decision):
    assessment = RiskEngine().evaluate(make_request(amount=amount))

    assert assessment.risk_score == expected_score
    assert assessment.decision is expected_decision


@pytest.mark.parametrize(
    ("score", "expected_decision"),
    [
        (29, RiskDecisionCode.LOW_RISK),
        (30, RiskDecisionCode.ELEVATED_RISK),
        (59, RiskDecisionCode.ELEVATED_RISK),
        (60, RiskDecisionCode.HIGH_RISK),
    ],
)
def test_decision_threshold_boundaries(score, expected_decision):
    rules = RiskRules(amount_weight=score, amount_threshold=Decimal("1"))

    assessment = RiskEngine(rules).evaluate(make_request())

    assert assessment.risk_score == score
    assert assessment.decision is expected_decision


def test_conflicting_signals_add_and_cap_at_one_hundred():
    assessment = RiskEngine().evaluate(
        make_request(amount=Decimal("20000")),
        RiskSignal(velocity_count=5, unusual_channel=True),
    )

    assert assessment.risk_score == 65
    assert assessment.rules_triggered == ("HIGH_AMOUNT", "HIGH_VELOCITY", "UNUSUAL_CHANNEL")


def test_custom_rules_control_thresholds_and_score():
    rules = RiskRules(amount_threshold=Decimal("50"), amount_weight=40, elevated_risk_threshold=20)

    assessment = RiskEngine(rules).evaluate(make_request())

    assert assessment.risk_score == 40
    assert assessment.decision is RiskDecisionCode.ELEVATED_RISK


def test_integrity_failure_has_priority_over_risk_score():
    integrity = IntegrityDecision(
        IntegrityDecisionCode.PARTIAL_FAILURE,
        "txn-risk-001",
        ("debit and credit effects do not match",),
    )

    assessment = RiskEngine().evaluate(
        make_request(amount=Decimal("50000")),
        RiskSignal(system_anomaly=True),
        integrity_decision=integrity,
    )

    assert assessment.decision is RiskDecisionCode.INTEGRITY_BLOCKED
    assert assessment.integrity_code == "PARTIAL_FAILURE"
    assert assessment.risk_score == 0
    assert assessment.rules_triggered == ()


@pytest.mark.parametrize(
    "signal",
    [
        RiskSignal(velocity_count=-1),
        RiskSignal(account_history_score=101),
    ],
)
def test_invalid_risk_signal_is_rejected(signal):
    assessment = RiskEngine().evaluate(make_request(), signal)

    assert assessment.decision is RiskDecisionCode.INVALID_INPUT


def test_invalid_risk_rules_are_rejected():
    rules = RiskRules(high_risk_threshold=20, elevated_risk_threshold=20)

    assessment = RiskEngine(rules).evaluate(make_request())

    assert assessment.decision is RiskDecisionCode.INVALID_INPUT
    assert "rules:" in assessment.rules_triggered[0]


def test_non_positive_amount_threshold_is_rejected():
    assessment = RiskEngine(RiskRules(amount_threshold=Decimal("0"))).evaluate(make_request())

    assert assessment.decision is RiskDecisionCode.INVALID_INPUT


def test_non_decimal_amount_is_rejected_without_type_error():
    assessment = RiskEngine().evaluate(make_request(amount="100"))

    assert assessment.decision is RiskDecisionCode.INVALID_INPUT


def test_negative_rule_weight_is_rejected():
    assessment = RiskEngine(RiskRules(amount_weight=-1)).evaluate(make_request())

    assert assessment.decision is RiskDecisionCode.INVALID_INPUT


def test_concurrent_risk_evaluations_are_independent():
    engine = RiskEngine()
    requests = [make_request(transaction_id=f"txn-risk-{index}") for index in range(32)]

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as executor:
        assessments = list(executor.map(engine.evaluate, requests))

    assert len({assessment.decision_id for assessment in assessments}) == 32
    assert {assessment.transaction_id for assessment in assessments} == {
        request.transaction_id for request in requests
    }


def test_fixed_record_inputs_make_assessment_reproducible():
    engine = RiskEngine()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    signal = RiskSignal(velocity_count=5, unusual_device=True)

    first = engine.evaluate(
        make_request(), signal, decision_id="decision-001", timestamp=timestamp
    )
    second = engine.evaluate(
        make_request(), signal, decision_id="decision-001", timestamp=timestamp
    )

    assert first == second
    assert engine.score(make_request(), signal) == (35, ("HIGH_VELOCITY", "UNUSUAL_DEVICE"))