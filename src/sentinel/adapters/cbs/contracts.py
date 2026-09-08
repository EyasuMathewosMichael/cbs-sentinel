"""Bank-neutral CBS adapter request and response contracts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class CBSOperationError(RuntimeError):
    """Base error for adapter operations; financial outcome may remain unknown."""


class CBSOperationTimeout(CBSOperationError):
    """The CBS did not respond within the adapter timeout."""


class CBSUnavailableError(CBSOperationError):
    """The CBS or its network endpoint was unavailable."""


class CBSAuthenticationError(CBSOperationError):
    """The adapter could not authenticate with the CBS."""


class CBSMalformedResponseError(CBSOperationError):
    """The CBS response violated the bank-neutral adapter contract."""


class TransactionStatus(StrEnum):
    """Transport-neutral status reported by a CBS adapter."""

    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CBSAdapterCapabilities:
    """Capabilities an adapter explicitly supports."""

    status_query: bool = True
    transaction_lookup: bool = True
    balance_query: bool = True
    account_status_query: bool = True
    reversal: bool = False
    compensation: bool = False
    reconciliation: bool = False


@dataclass(frozen=True, slots=True)
class TransactionSubmission:
    """CBS submission response; accepted is not equivalent to posted."""

    transaction_id: str
    cbs_reference: str | None
    status: TransactionStatus
    submitted_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.transaction_id, "transaction_id")
        _validate_status(self.status)
        _validate_timestamp(self.submitted_at, "submitted_at")


@dataclass(frozen=True, slots=True)
class TransactionLookup:
    """Authoritative transaction lookup response."""

    transaction_id: str
    cbs_reference: str | None
    status: TransactionStatus
    source_account: str | None
    destination_account: str | None
    amount: Decimal | None
    currency: str | None
    looked_up_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.transaction_id, "transaction_id")
        _validate_status(self.status)
        _validate_timestamp(self.looked_up_at, "looked_up_at")
        if self.amount is not None and (
            not isinstance(self.amount, Decimal) or not self.amount.is_finite()
        ):
            raise CBSMalformedResponseError("amount must be a finite Decimal when present")


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Balance observation returned by CBS."""

    account_id: str
    balance: Decimal
    currency: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.account_id, "account_id")
        _validate_identifier(self.currency, "currency")
        if not isinstance(self.balance, Decimal) or not self.balance.is_finite():
            raise CBSMalformedResponseError("balance must be a finite Decimal")
        _validate_timestamp(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class AccountStatus:
    """Account status returned by CBS."""

    account_id: str
    status: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.account_id, "account_id")
        _validate_identifier(self.status, "status")
        _validate_timestamp(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class ReversalResult:
    """Result of a separately identified reversal request."""

    original_transaction_id: str
    reversal_transaction_id: str
    status: TransactionStatus
    cbs_reference: str | None
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _validate_identifier(self.original_transaction_id, "original_transaction_id")
        _validate_identifier(self.reversal_transaction_id, "reversal_transaction_id")
        _validate_status(self.status)
        if self.completed_at is not None:
            _validate_timestamp(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Bank-neutral result of an adapter reconciliation query."""

    transaction_id: str
    status: TransactionStatus
    source_debited: bool | None
    destination_credited: bool | None
    details: str
    reconciled_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.transaction_id, "transaction_id")
        _validate_status(self.status)
        _validate_identifier(self.details, "details")
        _validate_timestamp(self.reconciled_at, "reconciled_at")


def utc_now() -> datetime:
    """Return an aware UTC timestamp for adapter implementations."""
    return datetime.now(UTC)


def _validate_identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CBSMalformedResponseError(f"{field_name} must not be empty")


def _validate_status(value: object) -> None:
    if not isinstance(value, TransactionStatus):
        raise CBSMalformedResponseError("status must be a known TransactionStatus")


def _validate_timestamp(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CBSMalformedResponseError(f"{field_name} must be timezone-aware")
