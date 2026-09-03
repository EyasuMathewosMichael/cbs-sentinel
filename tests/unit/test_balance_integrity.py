from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sentinel.domain.balances import (
    BalanceDecisionCode,
    BalanceIntegrityEngine,
    ObservedBalance,
)
from sentinel.domain.integrity import TransactionRequest


def make_request(**overrides):
    values = {
        "transaction_id": "txn-balance-001",
        "idempotency_key": "idem-balance-001",
        "source_account": "acct-source",
        "destination_account": "acct-destination",
        "amount": Decimal("100.00"),
        "currency": "ETB",
    }
    values.update(overrides)
    return TransactionRequest(**values)


def make_observations(source_after="900.00", destination_after="600.00", observed_at=None):
    return (
        ObservedBalance(
            "acct-source", Decimal("1000.00"), Decimal(source_after), "ETB", observed_at
        ),
        ObservedBalance(
            "acct-destination", Decimal("500.00"), Decimal(destination_after), "ETB", observed_at
        ),
    )


def test_expected_transfer_effect_is_consistent_with_cbs_observations():
    decision = BalanceIntegrityEngine().evaluate(make_request(), make_observations())

    assert decision.code is BalanceDecisionCode.CONSISTENT
    assert decision.consistent
    assert decision.expected_effect.source_delta == Decimal("-100.00")
    assert decision.expected_effect.destination_delta == Decimal("100.00")
    assert decision.mismatched_accounts == ()


def test_normal_debit_and_credit_are_checked_as_separate_effects():
    decision = BalanceIntegrityEngine().evaluate(make_request(), make_observations())

    source_observation, destination_observation = decision.observed_balances
    assert source_observation.delta == decision.expected_effect.source_delta
    assert destination_observation.delta == decision.expected_effect.destination_delta


@pytest.mark.parametrize(
    ("source_after", "destination_after", "account"),
    [
        ("950.00", "600.00", "acct-source"),
        ("900.00", "550.00", "acct-destination"),
    ],
)
def test_balance_mismatch_identifies_the_affected_account(source_after, destination_after, account):
    decision = BalanceIntegrityEngine().evaluate(
        make_request(),
        make_observations(source_after, destination_after),
    )

    assert decision.code is BalanceDecisionCode.BALANCE_MISMATCH
    assert not decision.consistent
    assert decision.mismatched_accounts == (account,)


def test_double_debit_is_a_balance_mismatch():
    decision = BalanceIntegrityEngine().evaluate(
        make_request(),
        make_observations(source_after="800.00"),
    )

    assert decision.code is BalanceDecisionCode.BALANCE_MISMATCH
    assert decision.mismatched_accounts == ("acct-source",)


def test_missing_credit_is_a_balance_mismatch_not_consistent():
    decision = BalanceIntegrityEngine().evaluate(
        make_request(),
        make_observations(destination_after="500.00"),
    )

    assert decision.code is BalanceDecisionCode.BALANCE_MISMATCH
    assert decision.mismatched_accounts == ("acct-destination",)


def test_unexpected_balance_change_is_reported_for_the_changed_account():
    decision = BalanceIntegrityEngine().evaluate(
        make_request(),
        make_observations(source_after="1100.00"),
    )

    assert decision.code is BalanceDecisionCode.BALANCE_MISMATCH
    assert decision.mismatched_accounts == ("acct-source",)


@pytest.mark.parametrize(
    "observations",
    [
        (),
        (ObservedBalance("acct-source", Decimal("1000"), Decimal("900"), "ETB"),),
        (
            ObservedBalance("acct-source", Decimal("1000"), Decimal("900"), "ETB"),
            ObservedBalance("acct-source", Decimal("1000"), Decimal("900"), "ETB"),
        ),
        (
            ObservedBalance("acct-other", Decimal("1000"), Decimal("900"), "ETB"),
            ObservedBalance("acct-destination", Decimal("500"), Decimal("600"), "ETB"),
        ),
    ],
)
def test_missing_duplicate_or_unrelated_observations_are_invalid(observations):
    decision = BalanceIntegrityEngine().evaluate(make_request(), observations)

    assert decision.code is BalanceDecisionCode.INVALID_OBSERVATION


def test_observation_currency_must_match_request():
    observations = (
        ObservedBalance("acct-source", Decimal("1000"), Decimal("900"), "USD"),
        ObservedBalance("acct-destination", Decimal("500"), Decimal("600"), "ETB"),
    )

    decision = BalanceIntegrityEngine().evaluate(make_request(), observations)

    assert decision.code is BalanceDecisionCode.INVALID_OBSERVATION
    assert "currency" in decision.reasons[0]


def test_non_transfer_request_is_invalid_for_two_account_effects():
    decision = BalanceIntegrityEngine().evaluate(
        make_request(transaction_type="WITHDRAWAL"),
        make_observations(),
    )

    assert decision.code is BalanceDecisionCode.INVALID_REQUEST
    assert any(reason.startswith("transaction_type:") for reason in decision.reasons)


def test_nonfinite_observation_is_invalid():
    observations = (
        ObservedBalance("acct-source", Decimal("NaN"), Decimal("900"), "ETB"),
        ObservedBalance("acct-destination", Decimal("500"), Decimal("600"), "ETB"),
    )

    decision = BalanceIntegrityEngine().evaluate(make_request(), observations)

    assert decision.code is BalanceDecisionCode.INVALID_OBSERVATION


def test_non_decimal_observation_is_invalid():
    observations = (
        ObservedBalance("acct-source", 1000, Decimal("900"), "ETB"),
        ObservedBalance("acct-destination", Decimal("500"), Decimal("600"), "ETB"),
    )

    decision = BalanceIntegrityEngine().evaluate(make_request(), observations)

    assert decision.code is BalanceDecisionCode.INVALID_OBSERVATION


def test_stale_cbs_balance_is_not_used_for_consistency():
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    observations = make_observations(observed_at=datetime(2026, 1, 1, tzinfo=UTC))

    decision = BalanceIntegrityEngine().evaluate(
        make_request(), observations, minimum_observed_at=cutoff
    )

    assert decision.code is BalanceDecisionCode.STALE_OBSERVATION
    assert decision.mismatched_accounts == ("acct-source", "acct-destination")


def test_balance_engine_does_not_change_cbs_observations_or_request():
    request = make_request()
    observations = make_observations()

    BalanceIntegrityEngine().evaluate(request, observations)

    assert request.amount == Decimal("100.00")
    assert observations[0].balance_after == Decimal("900.00")


def test_cbs_disagreement_is_reported_without_overwriting_cbs_values():
    observations = make_observations(source_after="950.00")

    decision = BalanceIntegrityEngine().evaluate(make_request(), observations)

    assert decision.code is BalanceDecisionCode.BALANCE_MISMATCH
    assert decision.observed_balances[0].balance_after == Decimal("950.00")


def test_concurrent_transactions_are_independent():
    engine = BalanceIntegrityEngine()
    requests_and_observations = [
        (
            make_request(transaction_id=f"txn-{index}"),
            make_observations(),
        )
        for index in range(32)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        decisions = list(
            executor.map(lambda item: engine.evaluate(*item), requests_and_observations)
        )

    assert all(decision.code is BalanceDecisionCode.CONSISTENT for decision in decisions)
