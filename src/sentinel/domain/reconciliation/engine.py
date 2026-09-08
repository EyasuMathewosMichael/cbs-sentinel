"""Idempotent reconciliation against authoritative CBS evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from sentinel.adapters.cbs import CBSAdapter
from sentinel.adapters.cbs.contracts import ReconciliationResult, ReversalResult, TransactionStatus
from sentinel.domain.transactions import Transaction, TransactionState


class ReconciliationOutcome(StrEnum):
    """Stable reconciliation and recovery outcomes."""

    RECONCILED_SUCCESS = "RECONCILED_SUCCESS"
    RECONCILED_FAILURE = "RECONCILED_FAILURE"
    REVERSAL_REQUIRED = "REVERSAL_REQUIRED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNKNOWN_REQUIRES_INVESTIGATION = "UNKNOWN_REQUIRES_INVESTIGATION"


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    """Immutable decision based only on observed CBS evidence."""

    transaction_id: str
    outcome: ReconciliationOutcome
    reason: str
    observed_status: TransactionStatus
    source_debited: bool | None
    destination_credited: bool | None
    duplicate_posting: bool
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Idempotent result of a controlled reversal or compensation attempt."""

    transaction_id: str
    outcome: ReconciliationOutcome
    action_id: str | None
    reversal: ReversalResult | None = None


class CompensationHandler(Protocol):
    async def compensate(self, transaction_id: str, *, idempotency_key: str) -> str:
        """Execute a separately identified compensation through an approved boundary."""
        ...


class ReconciliationEngine:
    """Compare expected transaction state to CBS evidence and recover safely."""

    def __init__(self) -> None:
        self._recovery_results: dict[str, RecoveryResult] = {}
        self._decisions: dict[str, ReconciliationDecision] = {}
        self._unresolved: set[str] = set()

    def decide(
        self,
        transaction: Transaction,
        observed: ReconciliationResult,
        *,
        duplicate_posting: bool = False,
        delayed_response: bool = False,
    ) -> ReconciliationDecision:
        """Return a repeatable decision without retrying or changing CBS state."""
        if observed.transaction_id != transaction.transaction_id:
            raise ValueError("reconciliation evidence belongs to another transaction")
        if duplicate_posting:
            outcome = ReconciliationOutcome.MANUAL_REVIEW
            reason = "duplicate posting evidence requires investigation"
        elif observed.source_debited is True and observed.destination_credited is False:
            if transaction.state not in {
                TransactionState.UNKNOWN,
                TransactionState.PARTIAL_FAILURE,
                TransactionState.RECONCILIATION_PENDING,
            }:
                outcome = ReconciliationOutcome.MANUAL_REVIEW
                reason = "debit without credit is unsafe outside recovery states"
            elif transaction.state is TransactionState.UNKNOWN:
                outcome = ReconciliationOutcome.UNKNOWN_REQUIRES_INVESTIGATION
                reason = "authoritative CBS evidence shows a partial effect"
            else:
                outcome = ReconciliationOutcome.REVERSAL_REQUIRED
                reason = "source debited but destination not credited"
        elif observed.status is TransactionStatus.POSTED and (
            observed.source_debited is True and observed.destination_credited is True
        ):
            outcome = ReconciliationOutcome.RECONCILED_SUCCESS
            reason = "CBS confirms debit and destination credit"
        elif observed.status is TransactionStatus.FAILED and not any(
            value is True for value in (observed.source_debited, observed.destination_credited)
        ):
            outcome = ReconciliationOutcome.RECONCILED_FAILURE
            reason = "CBS confirms failure with no observed posting effect"
        elif delayed_response or observed.status in {
            TransactionStatus.UNKNOWN,
            TransactionStatus.ACCEPTED,
            TransactionStatus.PROCESSING,
        }:
            outcome = ReconciliationOutcome.UNKNOWN_REQUIRES_INVESTIGATION
            reason = "authoritative outcome remains unresolved; retry is prohibited"
        else:
            outcome = ReconciliationOutcome.MANUAL_REVIEW
            reason = "CBS evidence is inconsistent or incomplete"
        decision = ReconciliationDecision(
            transaction.transaction_id,
            outcome,
            reason,
            observed.status,
            observed.source_debited,
            observed.destination_credited,
            duplicate_posting,
            datetime.now(UTC),
        )
        self._decisions[transaction.transaction_id] = decision
        if outcome is ReconciliationOutcome.UNKNOWN_REQUIRES_INVESTIGATION:
            self._unresolved.add(transaction.transaction_id)
        else:
            self._unresolved.discard(transaction.transaction_id)
        return decision

    @property
    def unresolved_transactions(self) -> frozenset[str]:
        """Return transaction IDs awaiting authoritative resolution."""
        return frozenset(self._unresolved)

    @property
    def decision_audit(self) -> tuple[ReconciliationDecision, ...]:
        """Return the latest auditable decision for each transaction."""
        return tuple(self._decisions.values())

    async def recover(
        self,
        transaction: Transaction,
        decision: ReconciliationDecision,
        cbs: CBSAdapter,
        *,
        compensation: CompensationHandler | None = None,
    ) -> RecoveryResult:
        """Execute at most one separately identified recovery action."""
        if decision.transaction_id != transaction.transaction_id:
            raise ValueError("recovery decision belongs to another transaction")
        existing = self._recovery_results.get(transaction.transaction_id)
        if existing is not None:
            return existing
        action_id = _action_id(transaction.transaction_id, decision.outcome)
        if decision.outcome is ReconciliationOutcome.REVERSAL_REQUIRED:
            if not cbs.capabilities.reversal:
                return self._store(transaction.transaction_id, RecoveryResult(
                    transaction.transaction_id, ReconciliationOutcome.MANUAL_REVIEW, None
                ))
            reversal = await cbs.request_reversal(
                transaction.transaction_id,
                reversal_transaction_id=f"reversal-{action_id}",
                idempotency_key=f"idem-{action_id}",
            )
            result = RecoveryResult(
                transaction.transaction_id,
                ReconciliationOutcome.REVERSAL_REQUIRED,
                action_id,
                reversal,
            )
            return self._store(transaction.transaction_id, result)
        if decision.outcome is ReconciliationOutcome.COMPENSATION_REQUIRED:
            if not cbs.capabilities.compensation or compensation is None:
                return self._store(transaction.transaction_id, RecoveryResult(
                    transaction.transaction_id, ReconciliationOutcome.MANUAL_REVIEW, None
                ))
            await compensation.compensate(
                transaction.transaction_id,
                idempotency_key=f"idem-{action_id}",
            )
            return self._store(transaction.transaction_id, RecoveryResult(
                transaction.transaction_id, ReconciliationOutcome.COMPENSATION_REQUIRED, action_id
            ))
        return self._store(transaction.transaction_id, RecoveryResult(
            transaction.transaction_id, decision.outcome, None
        ))

    def _store(self, transaction_id: str, result: RecoveryResult) -> RecoveryResult:
        self._recovery_results[transaction_id] = result
        return result


def _action_id(transaction_id: str, outcome: ReconciliationOutcome) -> str:
    return sha256(f"{transaction_id}|{outcome.value}".encode()).hexdigest()