"""Safe, auditable protective response planning."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from threading import Lock
from uuid import uuid4

from sentinel.domain.integrity import IntegrityDecision
from sentinel.domain.risk import RiskAssessment, RiskDecisionCode
from sentinel.domain.transactions import Transaction, TransactionState


class ProtectiveAction(StrEnum):
    """Actions that may be planned by the protective response engine."""

    ALLOW = "ALLOW"
    HOLD = "HOLD"
    REJECT = "REJECT"
    RETRY = "RETRY"
    BLOCK_RETRY = "BLOCK_RETRY"
    RECONCILE = "RECONCILE"
    REVERSAL = "REVERSAL"
    COMPENSATION = "COMPENSATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CIRCUIT_BREAK = "CIRCUIT_BREAK"


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Authoritative-state and adapter capability facts for recovery planning."""

    reversal_supported: bool = False
    compensation_supported: bool = False
    retry_safe: bool = False
    system_anomaly: bool = False


@dataclass(frozen=True, slots=True)
class ProtectiveDecision:
    """Immutable, auditable protective decision record."""

    action_id: str
    transaction_id: str
    action: ProtectiveAction
    reason: str
    timestamp: datetime
    source: str
    risk_decision: RiskDecisionCode | None = None
    integrity_code: str | None = None
    state: TransactionState | None = None


class ProtectiveActionRegistry:
    """Thread-safe process-local registry preventing duplicate action plans."""

    def __init__(self) -> None:
        self._decisions: dict[str, ProtectiveDecision] = {}
        self._lock = Lock()

    def get_or_store(self, key: str, decision: ProtectiveDecision) -> ProtectiveDecision:
        """Return the first decision for a key and ignore duplicate planning calls."""
        with self._lock:
            existing = self._decisions.get(key)
            if existing is not None:
                if _decision_signature(existing) != _decision_signature(decision):
                    raise ProtectiveActionConflict(
                        f"action identity already belongs to a different plan: {key}"
                    )
                return existing
            self._decisions[key] = decision
            return decision


class ProtectiveActionConflict(ValueError):
    """Raised when an action identity is reused for a different plan."""


class ProtectiveResponseEngine:
    """Plan protective actions without executing financial operations."""

    def __init__(self, action_registry: ProtectiveActionRegistry | None = None) -> None:
        self._action_registry = action_registry or ProtectiveActionRegistry()

    def decide(
        self,
        transaction: Transaction,
        *,
        integrity_decision: IntegrityDecision | None = None,
        risk_assessment: RiskAssessment | None = None,
        recovery: RecoveryContext | None = None,
        policy_action: ProtectiveAction | None = None,
        action_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> ProtectiveDecision:
        """Return a safe action plan and never mutate the transaction or CBS."""
        recovery_context = recovery or RecoveryContext()
        decision_time = timestamp or datetime.now(UTC)
        if decision_time.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if action_id is not None and not action_id.strip():
            raise ValueError("action_id must not be empty")

        if (
            risk_assessment is not None
            and risk_assessment.transaction_id != transaction.transaction_id
        ):
            return self._record(
                transaction,
                ProtectiveAction.MANUAL_REVIEW,
                "risk assessment belongs to a different transaction",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if transaction.state in {TransactionState.UNKNOWN, TransactionState.TIMEOUT}:
            return self._record(
                transaction,
                ProtectiveAction.BLOCK_RETRY,
                "uncertain transaction requires authoritative state verification",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if integrity_decision is not None and not integrity_decision.allowed:
            return self._record(
                transaction,
                self._integrity_action(integrity_decision.code.value),
                "deterministic integrity decision has priority",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if transaction.state is TransactionState.PARTIAL_FAILURE:
            if recovery_context.reversal_supported:
                action = ProtectiveAction.REVERSAL
            elif recovery_context.compensation_supported:
                action = ProtectiveAction.COMPENSATION
            else:
                action = ProtectiveAction.RECONCILE
            return self._record(
                transaction,
                action,
                "partial processing requires controlled recovery",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if recovery_context.system_anomaly:
            return self._record(
                transaction,
                ProtectiveAction.CIRCUIT_BREAK,
                "system anomaly requires protective isolation",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if policy_action is ProtectiveAction.RETRY and not recovery_context.retry_safe:
            return self._record(
                transaction,
                ProtectiveAction.BLOCK_RETRY,
                "policy retry conflicts with unsafe retry classification",
                decision_time,
                action_id,
                integrity_decision,
                risk_assessment,
            )

        if policy_action is not None:
            action = policy_action
            reason = "policy action applied after safety controls"
        elif risk_assessment is None:
            action = ProtectiveAction.ALLOW
            reason = "no risk assessment supplied; no protective restriction requested"
        elif risk_assessment.decision is RiskDecisionCode.HIGH_RISK:
            action = ProtectiveAction.MANUAL_REVIEW
            reason = "high risk requires review before financial processing"
        elif risk_assessment.decision is RiskDecisionCode.ELEVATED_RISK:
            action = ProtectiveAction.HOLD
            reason = "elevated risk requires a controlled hold"
        elif risk_assessment.decision is RiskDecisionCode.INTEGRITY_BLOCKED:
            action = ProtectiveAction.REJECT
            reason = "risk assessment confirms integrity controls blocked processing"
        elif risk_assessment.decision is RiskDecisionCode.INVALID_INPUT:
            action = ProtectiveAction.MANUAL_REVIEW
            reason = "invalid risk input requires review"
        else:
            action = ProtectiveAction.ALLOW
            reason = "risk assessment is low risk"

        if action is ProtectiveAction.ALLOW and recovery_context.retry_safe:
            action = ProtectiveAction.RETRY
            reason = "retry explicitly classified as safe and state is not UNKNOWN"
        return self._record(
            transaction,
            action,
            reason,
            decision_time,
            action_id,
            integrity_decision,
            risk_assessment,
        )

    @staticmethod
    def _integrity_action(integrity_code: str) -> ProtectiveAction:
        if integrity_code in {"DUPLICATE_TRANSACTION", "IDEMPOTENCY_KEY_CONFLICT"}:
            return ProtectiveAction.REJECT
        if integrity_code == "PARTIAL_FAILURE":
            return ProtectiveAction.RECONCILE
        return ProtectiveAction.HOLD

    def _record(
        self,
        transaction: Transaction,
        action: ProtectiveAction,
        reason: str,
        timestamp: datetime,
        action_id: str | None,
        integrity_decision: IntegrityDecision | None,
        risk_assessment: RiskAssessment | None,
    ) -> ProtectiveDecision:
        decision = ProtectiveDecision(
            action_id=action_id or str(uuid4()),
            transaction_id=transaction.transaction_id,
            action=action,
            reason=reason,
            timestamp=timestamp,
            source="protective-response-engine",
            risk_decision=risk_assessment.decision if risk_assessment else None,
            integrity_code=integrity_decision.code.value if integrity_decision else None,
            state=transaction.state,
        )
        key = action_id or _idempotency_key(decision)
        return self._action_registry.get_or_store(key, decision)


def _idempotency_key(decision: ProtectiveDecision) -> str:
    """Create a stable key for repeated planning of the same transaction action."""
    material = "|".join(
        (
            decision.transaction_id,
            decision.state.value if decision.state else "NONE",
            decision.action.value,
            decision.integrity_code or "",
            decision.risk_decision.value if decision.risk_decision else "",
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _decision_signature(decision: ProtectiveDecision) -> tuple[str, ...]:
    return (
        decision.transaction_id,
        decision.action.value,
        decision.state.value if decision.state else "NONE",
        decision.integrity_code or "",
        decision.risk_decision.value if decision.risk_decision else "",
    )
