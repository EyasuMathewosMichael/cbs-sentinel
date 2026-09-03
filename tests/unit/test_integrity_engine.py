from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from sentinel.domain.integrity import (
    DuplicateRegistry,
    IntegrityDecisionCode,
    IntegrityEngine,
    ProcessingObservation,
    TransactionRequest,
)
from sentinel.domain.transactions import Transaction, TransactionState


def make_request(**overrides):
    values = {
        "transaction_id": "txn-001",
        "idempotency_key": "idem-001",
        "source_account": "acct-source",
        "destination_account": "acct-destination",
        "amount": Decimal("100.00"),
        "currency": "ETB",
    }
    values.update(overrides)
    return TransactionRequest(**values)


def test_valid_request_is_allowed_once():
    engine = IntegrityEngine()

    decision = engine.evaluate(make_request())

    assert decision.code is IntegrityDecisionCode.ALLOW
    assert decision.allowed
    assert decision.reasons == ()


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("transaction_id", "", IntegrityDecisionCode.INVALID_REQUEST),
        ("idempotency_key", "", IntegrityDecisionCode.INVALID_REQUEST),
        ("source_account", "", IntegrityDecisionCode.INVALID_REQUEST),
        ("currency", "", IntegrityDecisionCode.INVALID_REQUEST),
        ("amount", Decimal("0"), IntegrityDecisionCode.INVALID_AMOUNT),
        ("amount", Decimal("-1"), IntegrityDecisionCode.INVALID_AMOUNT),
        ("amount", Decimal("NaN"), IntegrityDecisionCode.INVALID_AMOUNT),
    ],
)
def test_invalid_request_is_rejected(field, value, expected_code):
    decision = IntegrityEngine().evaluate(make_request(**{field: value}))

    assert decision.code is expected_code
    assert not decision.allowed


def test_source_and_destination_must_differ():
    decision = IntegrityEngine().evaluate(
        make_request(destination_account="acct-source")
    )

    assert decision.code is IntegrityDecisionCode.INVALID_REQUEST
    assert "accounts:" in decision.reasons[0]


@pytest.mark.parametrize("currency", ["etb", "US", "US$", "US1"])
def test_currency_must_be_three_letter_uppercase_ascii(currency):
    decision = IntegrityEngine().evaluate(make_request(currency=currency))

    assert decision.code is IntegrityDecisionCode.INVALID_REQUEST
    assert any(reason.startswith("currency:") for reason in decision.reasons)


def test_account_identifiers_must_not_have_outer_whitespace():
    decision = IntegrityEngine().evaluate(make_request(source_account=" acct-source"))

    assert decision.code is IntegrityDecisionCode.INVALID_REQUEST
    assert any(reason.startswith("source_account:") for reason in decision.reasons)


def test_duplicate_request_is_rejected_without_second_reservation():
    engine = IntegrityEngine()
    request = make_request()

    first = engine.evaluate(request)
    second = engine.evaluate(request)

    assert first.code is IntegrityDecisionCode.ALLOW
    assert second.code is IntegrityDecisionCode.DUPLICATE_TRANSACTION


def test_reusing_idempotency_key_for_different_request_is_rejected():
    engine = IntegrityEngine()
    engine.evaluate(make_request())

    decision = engine.evaluate(
        make_request(transaction_id="txn-002", amount=Decimal("200.00"))
    )

    assert decision.code is IntegrityDecisionCode.IDEMPOTENCY_KEY_CONFLICT


def test_reusing_transaction_identity_for_different_request_is_rejected():
    engine = IntegrityEngine()
    engine.evaluate(make_request())

    decision = engine.evaluate(
        make_request(idempotency_key="idem-002", amount=Decimal("200.00"))
    )

    assert decision.code is IntegrityDecisionCode.DUPLICATE_TRANSACTION


def test_invalid_request_does_not_consume_identity():
    engine = IntegrityEngine()
    invalid_request = make_request(amount=Decimal("0"))

    assert engine.evaluate(invalid_request).code is IntegrityDecisionCode.INVALID_AMOUNT
    assert engine.evaluate(make_request()).code is IntegrityDecisionCode.ALLOW


def test_concurrent_duplicate_requests_allow_exactly_one():
    engine = IntegrityEngine(DuplicateRegistry())
    request = make_request()

    with ThreadPoolExecutor(max_workers=8) as executor:
        decisions = list(executor.map(engine.evaluate, [request] * 32))

    assert sum(decision.allowed for decision in decisions) == 1
    assert sum(
        decision.code is IntegrityDecisionCode.DUPLICATE_TRANSACTION
        for decision in decisions
    ) == 31


def test_integrity_requires_phase_one_transaction_identity_and_pre_posting_state():
    engine = IntegrityEngine()
    transaction = Transaction("txn-001")

    allowed = engine.evaluate(make_request(), transaction=transaction)
    transaction.transition(TransactionState.VALIDATING)
    transaction.transition(TransactionState.ACCEPTED)
    rejected = engine.evaluate(make_request(), transaction=transaction)

    assert allowed.code is IntegrityDecisionCode.ALLOW
    assert transaction.state is TransactionState.ACCEPTED
    assert rejected.code is IntegrityDecisionCode.INVALID_STATE


def test_integrity_rejects_mismatched_transaction_entity():
    decision = IntegrityEngine().evaluate(
        make_request(),
        transaction=Transaction("txn-other"),
    )

    assert decision.code is IntegrityDecisionCode.INVALID_STATE


def test_debit_without_credit_is_partial_failure_not_failed():
    decision = IntegrityEngine().evaluate(
        make_request(),
        processing=ProcessingObservation(debit_posted=True, credit_posted=False),
    )

    assert decision.code is IntegrityDecisionCode.PARTIAL_FAILURE
    assert decision.code is not IntegrityDecisionCode.INVALID_REQUEST
