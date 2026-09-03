"""Deterministic transaction validation and duplicate detection."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from threading import Lock

from sentinel.domain.transactions import Transaction, TransactionState


class IntegrityDecisionCode(StrEnum):
    """Stable decision codes emitted by the integrity engine."""

    ALLOW = "ALLOW"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    INVALID_STATE = "INVALID_STATE"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


@dataclass(frozen=True, slots=True)
class TransactionRequest:
    """Financial request data required for deterministic integrity checks."""

    transaction_id: str
    idempotency_key: str
    source_account: str
    destination_account: str
    amount: Decimal
    currency: str
    transaction_type: str = "TRANSFER"


@dataclass(frozen=True, slots=True)
class ProcessingObservation:
    """Observed posting effects used to detect partial processing."""

    debit_posted: bool
    credit_posted: bool


@dataclass(frozen=True, slots=True)
class IntegrityDecision:
    """An explainable integrity result for one transaction request."""

    code: IntegrityDecisionCode
    transaction_id: str
    reasons: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """Whether deterministic integrity checks allow processing to continue."""
        return self.code is IntegrityDecisionCode.ALLOW


class DuplicateRegistry:
    """Thread-safe identity registry for the lifetime of one application process.

    Durable duplicate prevention belongs to the persistence phase. This registry
    provides deterministic coordination for the Phase 2 engine and is designed
    to be replaceable by a durable implementation later.
    """

    def __init__(self) -> None:
        self._transaction_fingerprints: dict[str, tuple[str, ...]] = {}
        self._idempotency_fingerprints: dict[str, tuple[str, ...]] = {}
        self._lock = Lock()

    def reserve(self, request: TransactionRequest) -> IntegrityDecisionCode | None:
        """Atomically reserve request identities or return the duplicate reason."""
        fingerprint = _fingerprint(request)
        with self._lock:
            existing_transaction = self._transaction_fingerprints.get(request.transaction_id)
            if existing_transaction is not None:
                if existing_transaction == fingerprint:
                    return IntegrityDecisionCode.DUPLICATE_TRANSACTION
                return IntegrityDecisionCode.DUPLICATE_TRANSACTION

            existing_idempotency = self._idempotency_fingerprints.get(request.idempotency_key)
            if existing_idempotency is not None:
                if existing_idempotency == fingerprint:
                    return IntegrityDecisionCode.DUPLICATE_TRANSACTION
                return IntegrityDecisionCode.IDEMPOTENCY_KEY_CONFLICT

            self._transaction_fingerprints[request.transaction_id] = fingerprint
            self._idempotency_fingerprints[request.idempotency_key] = fingerprint
        return None


class IntegrityEngine:
    """Evaluate transaction invariants and duplicate identities."""

    def __init__(self, duplicate_registry: DuplicateRegistry | None = None) -> None:
        self._duplicate_registry = duplicate_registry or DuplicateRegistry()

    def evaluate(
        self,
        request: TransactionRequest,
        *,
        transaction: Transaction | None = None,
        processing: ProcessingObservation | None = None,
    ) -> IntegrityDecision:
        """Return a deterministic decision without performing a financial effect.

        ALLOW means the request passed integrity checks; it never means that a
        transaction was accepted by, or posted to, the authoritative CBS.
        """
        validation_errors = _validate_request(request)
        if validation_errors:
            code = (
                IntegrityDecisionCode.INVALID_AMOUNT
                if any(error.startswith("amount:") for error in validation_errors)
                else IntegrityDecisionCode.INVALID_REQUEST
            )
            return IntegrityDecision(code, request.transaction_id, tuple(validation_errors))

        if transaction is not None:
            if transaction.transaction_id != request.transaction_id:
                return IntegrityDecision(
                    IntegrityDecisionCode.INVALID_STATE,
                    request.transaction_id,
                    ("transaction_id: does not match transaction entity",),
                )
            if transaction.state not in {
                TransactionState.RECEIVED,
                TransactionState.VALIDATING,
            }:
                return IntegrityDecision(
                    IntegrityDecisionCode.INVALID_STATE,
                    request.transaction_id,
                    (f"state: integrity check not valid in {transaction.state.value}",),
                )

        if processing is not None and processing.debit_posted != processing.credit_posted:
            return IntegrityDecision(
                IntegrityDecisionCode.PARTIAL_FAILURE,
                request.transaction_id,
                ("debit and credit effects do not match",),
            )

        duplicate_code = self._duplicate_registry.reserve(request)
        if duplicate_code is not None:
            return IntegrityDecision(
                duplicate_code,
                request.transaction_id,
                (duplicate_code.value.lower(),),
            )
        return IntegrityDecision(IntegrityDecisionCode.ALLOW, request.transaction_id)


def _validate_request(request: TransactionRequest) -> list[str]:
    errors: list[str] = []
    text_fields = {
        "transaction_id": request.transaction_id,
        "idempotency_key": request.idempotency_key,
        "source_account": request.source_account,
        "destination_account": request.destination_account,
        "currency": request.currency,
        "transaction_type": request.transaction_type,
    }
    for field_name, value in text_fields.items():
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            errors.append(f"{field_name}: must not be empty")

    if (
        isinstance(request.source_account, str)
        and isinstance(request.destination_account, str)
        and request.source_account == request.destination_account
    ):
        errors.append("accounts: source and destination must differ")

    if not isinstance(request.amount, Decimal) or not request.amount.is_finite():
        errors.append("amount: must be a finite Decimal")
    elif request.amount <= Decimal("0"):
        errors.append("amount: must be greater than zero")
    if not isinstance(request.currency, str) or not _is_iso_currency(request.currency):
        errors.append("currency: must be a three-letter uppercase ISO code")
    return errors


def _is_iso_currency(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()


def _fingerprint(request: TransactionRequest) -> tuple[str, ...]:
    return (
        request.transaction_id,
        request.source_account,
        request.destination_account,
        str(request.amount),
        request.currency.upper(),
        request.transaction_type.upper(),
    )
