from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentinel.domain.transactions import (
    InvalidStateTransition,
    InvalidTransactionState,
    Transaction,
    TransactionState,
)


def test_normal_transfer_lifecycle_records_history():
    transaction = Transaction("txn-001")
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)

    for state in (
        TransactionState.VALIDATING,
        TransactionState.ACCEPTED,
        TransactionState.SUBMITTED_TO_CBS,
        TransactionState.CBS_PROCESSING,
        TransactionState.POSTED,
        TransactionState.DESTINATION_CREDITED,
        TransactionState.SETTLED,
        TransactionState.RECONCILED,
    ):
        transaction.transition(state, actor="workflow", timestamp=timestamp)

    assert transaction.state is TransactionState.RECONCILED
    assert transaction.is_terminal
    assert len(transaction.history) == 9
    assert transaction.history[0].previous_state is None
    assert transaction.history[-1].previous_state is TransactionState.SETTLED
    assert transaction.history[-1].actor == "workflow"


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (TransactionState.RECEIVED, TransactionState.SETTLED),
        (TransactionState.ACCEPTED, TransactionState.POSTED),
        (TransactionState.TIMEOUT, TransactionState.SUBMITTED_TO_CBS),
        (TransactionState.RECONCILED, TransactionState.RECEIVED),
    ],
)
def test_invalid_transition_does_not_change_state_or_history(current_state, next_state):
    transaction = Transaction("txn-invalid")
    if current_state is TransactionState.ACCEPTED:
        transaction.transition(TransactionState.VALIDATING)
        transaction.transition(current_state)
    elif current_state is TransactionState.TIMEOUT:
        for state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            current_state,
        ):
            transaction.transition(state)
    elif current_state is TransactionState.RECONCILED:
        for state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.CBS_PROCESSING,
            TransactionState.POSTED,
            TransactionState.DESTINATION_CREDITED,
            TransactionState.SETTLED,
            current_state,
        ):
            transaction.transition(state)
    history_before = transaction.history

    with pytest.raises(InvalidStateTransition):
        transaction.transition(next_state)

    assert transaction.state is current_state
    assert transaction.history == history_before


@pytest.mark.parametrize(
    "terminal_state",
    [
        TransactionState.REJECTED,
        TransactionState.FAILED,
        TransactionState.RECONCILED,
        TransactionState.REVERSAL_COMPLETED,
        TransactionState.COMPENSATION_COMPLETED,
        TransactionState.MANUAL_REVIEW,
    ],
)
def test_terminal_states_are_marked_terminal(terminal_state):
    transaction = Transaction("txn-terminal")
    if terminal_state is TransactionState.REJECTED:
        transaction.transition(terminal_state)
    elif terminal_state is TransactionState.FAILED:
        for state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            terminal_state,
        ):
            transaction.transition(state)
    elif terminal_state is TransactionState.RECONCILED:
        for state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.CBS_PROCESSING,
            TransactionState.POSTED,
            TransactionState.DESTINATION_CREDITED,
            TransactionState.SETTLED,
            terminal_state,
        ):
            transaction.transition(state)
    else:
        for state in (
            TransactionState.VALIDATING,
            TransactionState.ACCEPTED,
            TransactionState.SUBMITTED_TO_CBS,
            TransactionState.CBS_PROCESSING,
            TransactionState.PARTIAL_FAILURE,
            TransactionState.RECONCILIATION_PENDING,
        ):
            transaction.transition(state)
        if terminal_state is TransactionState.REVERSAL_COMPLETED:
            transaction.transition(TransactionState.REVERSAL_PENDING)
        elif terminal_state is TransactionState.COMPENSATION_COMPLETED:
            transaction.transition(TransactionState.COMPENSATION_PENDING)
        transaction.transition(terminal_state)

    assert transaction.is_terminal


def test_transaction_rejects_empty_id_and_invalid_state():
    with pytest.raises(ValueError, match="transaction_id"):
        Transaction(" ")

    transaction = Transaction("txn-invalid-state")
    with pytest.raises(InvalidTransactionState):
        transaction.transition("POSTED")


def test_history_is_immutable_snapshot_and_timestamp_must_be_aware():
    transaction = Transaction("txn-history")

    with pytest.raises(AttributeError):
        transaction.history.append(None)

    with pytest.raises(ValueError, match="timezone-aware"):
        transaction.transition(
            TransactionState.VALIDATING,
            timestamp=datetime(2026, 1, 1),
        )


def test_unknown_transaction_must_pass_through_retry_pending():
    transaction = Transaction("txn-retry")
    for state in (
        TransactionState.VALIDATING,
        TransactionState.ACCEPTED,
        TransactionState.SUBMITTED_TO_CBS,
        TransactionState.TIMEOUT,
        TransactionState.UNKNOWN,
        TransactionState.RETRY_PENDING,
        TransactionState.SUBMITTED_TO_CBS,
    ):
        transaction.transition(state)

    assert transaction.state is TransactionState.SUBMITTED_TO_CBS


def test_state_cannot_be_assigned_directly():
    transaction = Transaction("txn-read-only")

    with pytest.raises(AttributeError):
        transaction.state = TransactionState.POSTED


def test_concurrent_transitions_are_atomic():
    transaction = Transaction("txn-concurrent")

    def attempt_transition():
        try:
            transaction.transition(TransactionState.VALIDATING, actor="worker")
        except InvalidStateTransition:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: attempt_transition(), range(32)))

    assert sum(results) == 1
    assert transaction.state is TransactionState.VALIDATING
    assert len(transaction.history) == 2