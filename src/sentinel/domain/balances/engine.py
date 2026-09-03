"""Expected-versus-observed balance integrity checks."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sentinel.domain.integrity import TransactionRequest


class BalanceDecisionCode(StrEnum):
    """Stable outcomes from balance consistency evaluation."""

    CONSISTENT = "CONSISTENT"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_OBSERVATION = "INVALID_OBSERVATION"
    STALE_OBSERVATION = "STALE_OBSERVATION"


@dataclass(frozen=True, slots=True)
class ExpectedBalanceEffect:
    """Expected transfer deltas derived from the transaction request."""

    source_account: str
    destination_account: str
    amount: Decimal
    currency: str

    @property
    def source_delta(self) -> Decimal:
        """Expected source-account balance change."""
        return -self.amount

    @property
    def destination_delta(self) -> Decimal:
        """Expected destination-account balance change."""
        return self.amount


@dataclass(frozen=True, slots=True)
class ObservedBalance:
    """A balance observation obtained from the authoritative CBS."""

    account_id: str
    balance_before: Decimal
    balance_after: Decimal
    currency: str
    observed_at: datetime | None = None

    @property
    def delta(self) -> Decimal:
        """Observed balance change reported by CBS."""
        return self.balance_after - self.balance_before


@dataclass(frozen=True, slots=True)
class BalanceDecision:
    """An explainable balance consistency result."""

    code: BalanceDecisionCode
    transaction_id: str
    expected_effect: ExpectedBalanceEffect | None = None
    observed_balances: tuple[ObservedBalance, ...] = ()
    mismatched_accounts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def consistent(self) -> bool:
        """Whether all supplied CBS observations match the expected effect."""
        return self.code is BalanceDecisionCode.CONSISTENT


class BalanceIntegrityEngine:
    """Compare expected transfer effects with authoritative CBS observations."""

    def evaluate(
        self,
        request: TransactionRequest,
        observed_balances: tuple[ObservedBalance, ...],
        *,
        minimum_observed_at: datetime | None = None,
    ) -> BalanceDecision:
        """Evaluate balances without mutating the request or CBS observations."""
        expected = ExpectedBalanceEffect(
            source_account=request.source_account,
            destination_account=request.destination_account,
            amount=request.amount,
            currency=request.currency,
        )
        request_errors = _validate_request(request)
        if request_errors:
            return BalanceDecision(
                BalanceDecisionCode.INVALID_REQUEST,
                request.transaction_id,
                expected,
                observed_balances,
                reasons=tuple(request_errors),
            )
        observation_errors = _validate_observations(request, observed_balances)
        if observation_errors:
            return BalanceDecision(
                BalanceDecisionCode.INVALID_OBSERVATION,
                request.transaction_id,
                expected,
                observed_balances,
                reasons=tuple(observation_errors),
            )
        if minimum_observed_at is not None:
            if minimum_observed_at.tzinfo is None:
                return BalanceDecision(
                    BalanceDecisionCode.INVALID_OBSERVATION,
                    request.transaction_id,
                    expected,
                    observed_balances,
                    reasons=("minimum_observed_at: must be timezone-aware",),
                )
            stale_accounts = tuple(
                observation.account_id
                for observation in observed_balances
                if observation.observed_at is None
                or observation.observed_at < minimum_observed_at
            )
            if stale_accounts:
                return BalanceDecision(
                    BalanceDecisionCode.STALE_OBSERVATION,
                    request.transaction_id,
                    expected,
                    observed_balances,
                    stale_accounts,
                    ("CBS balance observation is older than the required cutoff",),
                )

        expected_deltas = {
            expected.source_account: expected.source_delta,
            expected.destination_account: expected.destination_delta,
        }
        mismatched_accounts = tuple(
            observation.account_id
            for observation in observed_balances
            if observation.delta != expected_deltas[observation.account_id]
        )
        if mismatched_accounts:
            return BalanceDecision(
                BalanceDecisionCode.BALANCE_MISMATCH,
                request.transaction_id,
                expected,
                observed_balances,
                mismatched_accounts,
                ("observed balance delta differs from expected transfer effect",),
            )
        return BalanceDecision(
            BalanceDecisionCode.CONSISTENT,
            request.transaction_id,
            expected,
            observed_balances,
        )


def _validate_request(
    request: TransactionRequest,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(request.transaction_id, str) or not request.transaction_id.strip():
        errors.append("transaction_id: must not be empty")
    if not isinstance(request.source_account, str) or not request.source_account.strip():
        errors.append("source_account: must not be empty")
    if not isinstance(request.destination_account, str) or not request.destination_account.strip():
        errors.append("destination_account: must not be empty")
    if request.source_account == request.destination_account:
        errors.append("accounts: source and destination must differ")
    if not isinstance(request.amount, Decimal) or not request.amount.is_finite():
        errors.append("amount: must be a finite Decimal")
    elif request.amount <= Decimal("0"):
        errors.append("amount: must be greater than zero")
    if not isinstance(request.currency, str) or not _is_currency_format(request.currency):
        errors.append("currency: must be a three-letter uppercase code")
    if (
        not isinstance(request.transaction_type, str)
        or request.transaction_type.upper() != "TRANSFER"
    ):
        errors.append("transaction_type: balance effects require TRANSFER")
    return errors


def _is_currency_format(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()


def _validate_observations(
    request: TransactionRequest,
    observations: tuple[ObservedBalance, ...],
) -> list[str]:
    errors: list[str] = []
    expected_accounts = {request.source_account, request.destination_account}
    observed_accounts = [observation.account_id for observation in observations]
    if len(observations) != 2:
        errors.append("observations: exactly source and destination balances are required")
    if len(set(observed_accounts)) != len(observed_accounts):
        errors.append("observations: duplicate account observation")
    if set(observed_accounts) != expected_accounts:
        errors.append("observations: accounts do not match the transaction")

    for observation in observations:
        if not isinstance(observation.account_id, str) or not observation.account_id.strip():
            errors.append("observations: account identifier must not be empty")
        if not isinstance(observation.currency, str) or observation.currency != request.currency:
            errors.append(f"{observation.account_id}: currency does not match request")
        if not isinstance(observation.balance_before, Decimal):
            errors.append(f"{observation.account_id}: before balance must be a Decimal")
        elif not observation.balance_before.is_finite():
            errors.append(f"{observation.account_id}: before balance must be finite")
        if not isinstance(observation.balance_after, Decimal):
            errors.append(f"{observation.account_id}: after balance must be a Decimal")
        elif not observation.balance_after.is_finite():
            errors.append(f"{observation.account_id}: after balance must be finite")
        if observation.observed_at is not None and observation.observed_at.tzinfo is None:
            errors.append(f"{observation.account_id}: observed_at must be timezone-aware")
    return errors
