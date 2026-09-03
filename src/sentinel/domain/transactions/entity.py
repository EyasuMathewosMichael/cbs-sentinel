"""Transaction state machine and immutable state history."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import ClassVar


class TransactionState(StrEnum):
    """States in the SENTINEL transaction lifecycle."""

    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUBMITTED_TO_CBS = "SUBMITTED_TO_CBS"
    CBS_PROCESSING = "CBS_PROCESSING"
    POSTED = "POSTED"
    DESTINATION_CREDITED = "DESTINATION_CREDITED"
    SETTLED = "SETTLED"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    RETRY_PENDING = "RETRY_PENDING"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"
    REVERSAL_PENDING = "REVERSAL_PENDING"
    REVERSAL_COMPLETED = "REVERSAL_COMPLETED"
    COMPENSATION_PENDING = "COMPENSATION_PENDING"
    COMPENSATION_COMPLETED = "COMPENSATION_COMPLETED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class InvalidStateTransition(ValueError):
    """Raised when a transaction attempts an undefined state transition."""


class InvalidTransactionState(ValueError):
    """Raised when a transaction is created with an invalid state value."""


@dataclass(frozen=True, slots=True)
class StateHistoryEntry:
    """An immutable record of one transaction state change."""

    previous_state: TransactionState | None
    new_state: TransactionState
    timestamp: datetime
    actor: str


@dataclass(slots=True)
class Transaction:
    """A transaction with explicit, validated lifecycle transitions."""

    transaction_id: str
    _state: TransactionState = field(default=TransactionState.RECEIVED, init=False, repr=False)
    _history: list[StateHistoryEntry] = field(init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    _TRANSITIONS: ClassVar[dict[TransactionState, frozenset[TransactionState]]] = {
        TransactionState.RECEIVED: frozenset({
            TransactionState.VALIDATING,
            TransactionState.REJECTED,
        }),
        TransactionState.VALIDATING: frozenset({
            TransactionState.ACCEPTED,
            TransactionState.REJECTED,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.ACCEPTED: frozenset({TransactionState.SUBMITTED_TO_CBS}),
        TransactionState.SUBMITTED_TO_CBS: frozenset({
            TransactionState.CBS_PROCESSING,
            TransactionState.TIMEOUT,
            TransactionState.UNKNOWN,
            TransactionState.FAILED,
        }),
        TransactionState.CBS_PROCESSING: frozenset({
            TransactionState.POSTED,
            TransactionState.TIMEOUT,
            TransactionState.UNKNOWN,
            TransactionState.PARTIAL_FAILURE,
            TransactionState.FAILED,
        }),
        TransactionState.POSTED: frozenset({
            TransactionState.DESTINATION_CREDITED,
            TransactionState.PARTIAL_FAILURE,
            TransactionState.UNKNOWN,
        }),
        TransactionState.DESTINATION_CREDITED: frozenset({
            TransactionState.SETTLED,
            TransactionState.PARTIAL_FAILURE,
        }),
        TransactionState.SETTLED: frozenset({TransactionState.RECONCILED}),
        TransactionState.TIMEOUT: frozenset({TransactionState.UNKNOWN}),
        TransactionState.UNKNOWN: frozenset({
            TransactionState.CBS_PROCESSING,
            TransactionState.POSTED,
            TransactionState.DESTINATION_CREDITED,
            TransactionState.SETTLED,
            TransactionState.FAILED,
            TransactionState.PARTIAL_FAILURE,
            TransactionState.RETRY_PENDING,
            TransactionState.RECONCILIATION_PENDING,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.PARTIAL_FAILURE: frozenset({
            TransactionState.RECONCILIATION_PENDING,
            TransactionState.REVERSAL_PENDING,
            TransactionState.COMPENSATION_PENDING,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.RETRY_PENDING: frozenset({
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.RECONCILIATION_PENDING: frozenset({
            TransactionState.RECONCILED,
            TransactionState.REVERSAL_PENDING,
            TransactionState.COMPENSATION_PENDING,
            TransactionState.FAILED,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.REVERSAL_PENDING: frozenset({
            TransactionState.REVERSAL_COMPLETED,
            TransactionState.UNKNOWN,
            TransactionState.MANUAL_REVIEW,
        }),
        TransactionState.COMPENSATION_PENDING: frozenset({
            TransactionState.COMPENSATION_COMPLETED,
            TransactionState.UNKNOWN,
            TransactionState.MANUAL_REVIEW,
        }),
    }
    _TERMINAL_STATES: ClassVar[frozenset[TransactionState]] = frozenset({
        TransactionState.REJECTED,
        TransactionState.FAILED,
        TransactionState.RECONCILED,
        TransactionState.REVERSAL_COMPLETED,
        TransactionState.COMPENSATION_COMPLETED,
        TransactionState.MANUAL_REVIEW,
    })

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_id, str) or not self.transaction_id.strip():
            raise ValueError("transaction_id must not be empty")
        timestamp = datetime.now(UTC)
        self._history = [StateHistoryEntry(None, self._state, timestamp, "system")]

    @property
    def state(self) -> TransactionState:
        """Return the current state without exposing direct mutation."""
        return self._state

    @property
    def history(self) -> tuple[StateHistoryEntry, ...]:
        """Return state history as an immutable snapshot."""
        return tuple(self._history)

    @property
    def is_terminal(self) -> bool:
        """Whether the transaction has reached a state with no further transitions."""
        return self.state in self._TERMINAL_STATES

    def transition(
        self,
        new_state: TransactionState,
        *,
        actor: str = "system",
        timestamp: datetime | None = None,
    ) -> None:
        """Move to a valid next state and append an auditable history entry."""
        if not isinstance(new_state, TransactionState):
            raise InvalidTransactionState(f"Unsupported transaction state: {new_state!r}")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor must not be empty")
        with self._lock:
            if new_state not in self._TRANSITIONS.get(self._state, frozenset()):
                raise InvalidStateTransition(
                    f"Invalid transition for {self.transaction_id}: "
                    f"{self._state.value} -> {new_state.value}"
                )
            transition_time = timestamp or datetime.now(UTC)
            if transition_time.tzinfo is None:
                raise ValueError("timestamp must be timezone-aware")
            self._history.append(StateHistoryEntry(self._state, new_state, transition_time, actor))
            self._state = new_state
