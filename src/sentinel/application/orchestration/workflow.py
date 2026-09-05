"""Transaction workflow coordination across existing domain ports."""

from dataclasses import dataclass
from typing import Protocol

from sentinel.adapters.cbs import CBSAdapter
from sentinel.adapters.cbs.contracts import CBSOperationError, TransactionStatus
from sentinel.domain.integrity import (
    IntegrityDecision,
    IntegrityEngine,
    ProcessingObservation,
    TransactionRequest,
)
from sentinel.domain.protection import (
    ProtectiveAction,
    ProtectiveDecision,
    ProtectiveResponseEngine,
    RecoveryContext,
)
from sentinel.domain.risk import RiskAssessment, RiskEngine, RiskSignal
from sentinel.domain.transactions import Transaction, TransactionState


class PolicyHook(Protocol):
    """Application-provided policy decision hook."""

    async def decide(self, request: TransactionRequest, risk: RiskAssessment) -> ProtectiveAction:
        """Return a policy action without executing it."""
        ...


class ReconciliationHook(Protocol):
    """Application-provided reconciliation trigger hook."""

    async def request_reconciliation(self, transaction: Transaction) -> None:
        """Schedule investigation of an uncertain transaction."""
        ...


class EventHook(Protocol):
    """Application-provided event publication hook."""

    async def publish(self, event_type: str, transaction: Transaction) -> None:
        """Publish a lifecycle event."""
        ...


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Outcome of one orchestration attempt."""

    transaction: Transaction
    integrity: IntegrityDecision
    risk: RiskAssessment | None
    protective: ProtectiveDecision


class TransactionOrchestrator:
    """Coordinate existing domain engines and external-system ports."""

    def __init__(
        self,
        cbs: CBSAdapter,
        integrity: IntegrityEngine,
        risk: RiskEngine,
        protection: ProtectiveResponseEngine,
        policy: PolicyHook,
        reconciliation: ReconciliationHook,
        events: EventHook,
    ) -> None:
        self._cbs = cbs
        self._integrity = integrity
        self._risk = risk
        self._protection = protection
        self._policy = policy
        self._reconciliation = reconciliation
        self._events = events

    async def process(
        self,
        request: TransactionRequest,
        *,
        risk_signal: RiskSignal | None = None,
        processing: ProcessingObservation | None = None,
    ) -> WorkflowResult:
        """Run one transaction through validation, decisioning, CBS, and hooks."""
        transaction = Transaction(request.transaction_id)
        await self._events.publish("transaction.received", transaction)
        transaction.transition(TransactionState.VALIDATING, actor="orchestrator")
        await self._events.publish("transaction.validating", transaction)

        integrity = self._integrity.evaluate(
            request,
            transaction=transaction,
            processing=processing,
        )
        if not integrity.allowed:
            protective = self._protection.decide(
                transaction,
                integrity_decision=integrity,
            )
            if protective.action is ProtectiveAction.REJECT:
                transaction.transition(TransactionState.REJECTED, actor="orchestrator")
            else:
                transaction.transition(TransactionState.MANUAL_REVIEW, actor="orchestrator")
            await self._events.publish("transaction.rejected", transaction)
            return WorkflowResult(transaction, integrity, None, protective)

        risk = self._risk.evaluate(request, risk_signal, integrity_decision=integrity)
        policy_action = await self._policy.decide(request, risk)
        if not isinstance(policy_action, ProtectiveAction):
            policy_action = ProtectiveAction.MANUAL_REVIEW
        protective = self._protection.decide(
            transaction,
            integrity_decision=integrity,
            risk_assessment=risk,
            policy_action=policy_action,
            recovery=_recovery_context(self._cbs),
        )
        if protective.action in {
            ProtectiveAction.REJECT,
            ProtectiveAction.HOLD,
            ProtectiveAction.MANUAL_REVIEW,
            ProtectiveAction.CIRCUIT_BREAK,
        }:
            transaction.transition(TransactionState.MANUAL_REVIEW, actor="orchestrator")
            await self._events.publish("transaction.protected", transaction)
            return WorkflowResult(transaction, integrity, risk, protective)

        transaction.transition(TransactionState.ACCEPTED, actor="orchestrator")
        transaction.transition(TransactionState.SUBMITTED_TO_CBS, actor="orchestrator")
        await self._events.publish("transaction.submitted", transaction)
        try:
            submission = await self._cbs.submit_transaction(
                request,
                idempotency_key=request.idempotency_key,
            )
        except CBSOperationError:
            transaction.transition(TransactionState.TIMEOUT, actor="orchestrator")
            transaction.transition(TransactionState.UNKNOWN, actor="orchestrator")
            await self._events.publish("transaction.unknown", transaction)
            await self._reconciliation.request_reconciliation(transaction)
            return WorkflowResult(transaction, integrity, risk, protective)

        if submission.status is TransactionStatus.UNKNOWN:
            transaction.transition(TransactionState.UNKNOWN, actor="orchestrator")
            await self._events.publish("transaction.unknown", transaction)
            await self._reconciliation.request_reconciliation(transaction)
        elif submission.status is TransactionStatus.POSTED:
            transaction.transition(TransactionState.CBS_PROCESSING, actor="orchestrator")
            transaction.transition(TransactionState.POSTED, actor="orchestrator")
            await self._events.publish("transaction.posted", transaction)
        elif submission.status is TransactionStatus.FAILED:
            transaction.transition(TransactionState.FAILED, actor="orchestrator")
            await self._events.publish("transaction.failed", transaction)
        else:
            transaction.transition(TransactionState.CBS_PROCESSING, actor="orchestrator")
            await self._events.publish("transaction.processing", transaction)
        return WorkflowResult(transaction, integrity, risk, protective)


def _recovery_context(cbs: CBSAdapter) -> RecoveryContext:
    return RecoveryContext(
        reversal_supported=cbs.capabilities.reversal,
        retry_safe=False,
    )
