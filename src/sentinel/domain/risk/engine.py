"""Deterministic, explainable transaction risk scoring."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sentinel.domain.integrity import IntegrityDecision, TransactionRequest


class RiskDecisionCode(StrEnum):
    """Risk classifications emitted by the risk engine."""

    LOW_RISK = "LOW_RISK"
    ELEVATED_RISK = "ELEVATED_RISK"
    HIGH_RISK = "HIGH_RISK"
    INTEGRITY_BLOCKED = "INTEGRITY_BLOCKED"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True, slots=True)
class RiskSignal:
    """Optional transaction context used by deterministic risk rules."""

    velocity_count: int = 0
    transaction_frequency: int = 0
    previous_failures: int = 0
    retry_count: int = 0
    unusual_timing: bool = False
    unusual_channel: bool = False
    unusual_device: bool = False
    system_anomaly: bool = False
    account_history_score: int = 0


@dataclass(frozen=True, slots=True)
class RiskRules:
    """Versioned thresholds and weights for deterministic risk scoring."""

    amount_threshold: Decimal = Decimal("10000")
    amount_weight: int = 30
    velocity_threshold: int = 5
    velocity_weight: int = 20
    frequency_threshold: int = 10
    frequency_weight: int = 10
    previous_failures_threshold: int = 1
    previous_failures_weight: int = 15
    retry_threshold: int = 2
    retry_weight: int = 20
    unusual_timing_weight: int = 10
    unusual_channel_weight: int = 15
    unusual_device_weight: int = 15
    system_anomaly_weight: int = 25
    high_risk_threshold: int = 60
    elevated_risk_threshold: int = 30
    rule_version: str = "risk-rules-v1"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Auditable risk decision record for one transaction."""

    decision_id: str
    transaction_id: str
    risk_score: int
    decision: RiskDecisionCode
    rules_triggered: tuple[str, ...]
    policy_version: str
    rule_version: str
    model_version: str
    configuration_version: str
    timestamp: datetime
    integrity_code: str | None = None


class RiskEngine:
    """Score transactions using deterministic rules without performing actions."""

    def __init__(
        self,
        rules: RiskRules | None = None,
        *,
        policy_version: str = "policy-v1",
        model_version: str = "none",
        configuration_version: str = "config-v1",
    ) -> None:
        self._rules = rules or RiskRules()
        self._policy_version = policy_version
        self._model_version = model_version
        self._configuration_version = configuration_version

    def evaluate(
        self,
        request: TransactionRequest,
        signal: RiskSignal | None = None,
        *,
        integrity_decision: IntegrityDecision | None = None,
        decision_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> RiskAssessment:
        """Create an explainable risk record without changing financial state."""
        assessment_time = timestamp or datetime.now(UTC)
        if assessment_time.tzinfo is None:
            return self._record(
                request,
                RiskDecisionCode.INVALID_INPUT,
                0,
                ("timestamp: must be timezone-aware",),
                datetime.now(UTC),
                decision_id=decision_id,
            )
        if decision_id is not None and not decision_id.strip():
            return self._record(
                request,
                RiskDecisionCode.INVALID_INPUT,
                0,
                ("decision_id: must not be empty",),
                assessment_time,
            )
        if integrity_decision is not None and not integrity_decision.allowed:
            return self._record(
                request,
                RiskDecisionCode.INTEGRITY_BLOCKED,
                0,
                (),
                assessment_time,
                integrity_decision.code.value,
                decision_id=decision_id,
            )

        input_errors = _validate_inputs(request, signal or RiskSignal(), self._rules)
        if input_errors:
            return self._record(
                request,
                RiskDecisionCode.INVALID_INPUT,
                0,
                tuple(input_errors),
                assessment_time,
                decision_id=decision_id,
            )

        active_signal = signal or RiskSignal()
        score, triggered_rules = self.score(request, active_signal)
        if score >= self._rules.high_risk_threshold:
            decision = RiskDecisionCode.HIGH_RISK
        elif score >= self._rules.elevated_risk_threshold:
            decision = RiskDecisionCode.ELEVATED_RISK
        else:
            decision = RiskDecisionCode.LOW_RISK
        return self._record(
            request,
            decision,
            score,
            tuple(triggered_rules),
            assessment_time,
            decision_id=decision_id,
        )

    def score(
        self,
        request: TransactionRequest,
        signal: RiskSignal | None = None,
    ) -> tuple[int, tuple[str, ...]]:
        """Return deterministic score and rule evidence without creating a record."""
        active_signal = signal or RiskSignal()
        input_errors = _validate_inputs(request, active_signal, self._rules)
        if input_errors:
            raise ValueError("; ".join(input_errors))
        score, triggered_rules = self._score(request, active_signal)
        return score, tuple(triggered_rules)

    def _score(self, request: TransactionRequest, signal: RiskSignal) -> tuple[int, list[str]]:
        rules = self._rules
        score = 0
        triggered: list[str] = []

        weighted_rules = (
            (request.amount >= rules.amount_threshold, rules.amount_weight, "HIGH_AMOUNT"),
            (
                signal.velocity_count >= rules.velocity_threshold,
                rules.velocity_weight,
                "HIGH_VELOCITY",
            ),
            (
                signal.transaction_frequency >= rules.frequency_threshold,
                rules.frequency_weight,
                "HIGH_FREQUENCY",
            ),
            (
                signal.previous_failures >= rules.previous_failures_threshold,
                rules.previous_failures_weight,
                "PREVIOUS_FAILURES",
            ),
            (signal.retry_count >= rules.retry_threshold, rules.retry_weight, "RETRY_FREQUENCY"),
            (signal.unusual_timing, rules.unusual_timing_weight, "UNUSUAL_TIMING"),
            (signal.unusual_channel, rules.unusual_channel_weight, "UNUSUAL_CHANNEL"),
            (signal.unusual_device, rules.unusual_device_weight, "UNUSUAL_DEVICE"),
            (signal.system_anomaly, rules.system_anomaly_weight, "SYSTEM_ANOMALY"),
        )
        for condition, weight, rule_name in weighted_rules:
            if condition:
                score += weight
                triggered.append(rule_name)
        score = min(100, score + signal.account_history_score)
        if signal.account_history_score > 0:
            triggered.append("ACCOUNT_HISTORY")
        return score, triggered

    def _record(
        self,
        request: TransactionRequest,
        decision: RiskDecisionCode,
        score: int,
        triggered_rules: tuple[str, ...],
        timestamp: datetime,
        integrity_code: str | None = None,
        decision_id: str | None = None,
    ) -> RiskAssessment:
        return RiskAssessment(
            decision_id=decision_id or str(uuid4()),
            transaction_id=request.transaction_id,
            risk_score=score,
            decision=decision,
            rules_triggered=triggered_rules,
            policy_version=self._policy_version,
            rule_version=self._rules.rule_version,
            model_version=self._model_version,
            configuration_version=self._configuration_version,
            timestamp=timestamp,
            integrity_code=integrity_code,
        )


def _validate_inputs(
    request: TransactionRequest,
    signal: RiskSignal,
    rules: RiskRules,
) -> list[str]:
    errors: list[str] = []
    valid_amount = isinstance(request.amount, Decimal) and request.amount.is_finite()
    if not valid_amount:
        errors.append("amount: must be a finite Decimal")
    elif request.amount <= Decimal("0"):
        errors.append("amount: must be greater than zero")
    if rules.high_risk_threshold <= rules.elevated_risk_threshold:
        errors.append("rules: high-risk threshold must exceed elevated threshold")
    if rules.elevated_risk_threshold < 0 or rules.high_risk_threshold > 100:
        errors.append("rules: risk thresholds must be between 0 and 100")
    if not rules.amount_threshold.is_finite() or rules.amount_threshold <= Decimal("0"):
        errors.append("rules: amount threshold must be greater than zero")
    for field_name in (
        "amount_weight",
        "velocity_weight",
        "frequency_weight",
        "previous_failures_weight",
        "retry_weight",
        "unusual_timing_weight",
        "unusual_channel_weight",
        "unusual_device_weight",
        "system_anomaly_weight",
    ):
        if getattr(rules, field_name) < 0:
            errors.append(f"rules: {field_name} must not be negative")
    for field_name in (
        "velocity_count",
        "transaction_frequency",
        "previous_failures",
        "retry_count",
        "account_history_score",
    ):
        if getattr(signal, field_name) < 0:
            errors.append(f"{field_name}: must not be negative")
    if not 0 <= signal.account_history_score <= 100:
        errors.append("account_history_score: must be between 0 and 100")
    return errors