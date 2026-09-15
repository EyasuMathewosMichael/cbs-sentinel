"""Synthetic placeholder CBS adapter for safe development and integration validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sentinel.adapters.cbs.contracts import (
    AccountBalance,
    AccountStatus,
    CBSAdapterCapabilities,
    CBSOperationError,
    ReconciliationResult,
    ReversalResult,
    TransactionLookup,
    TransactionStatus,
    TransactionSubmission,
    utc_now,
)
from sentinel.domain.integrity import TransactionRequest


@dataclass(frozen=True, slots=True)
class _PlaceholderRecord:
    request: TransactionRequest
    cbs_reference: str
    status: TransactionStatus
    submitted_at: datetime


class PlaceholderCBSAdapter:
    """Synthetic bank adapter that follows the canonical CBS contract.

    This adapter is intentionally non-authoritative and clearly labeled as a
    placeholder. It is safe for development, integration validation, and UI
    workflow tests, but never represents a real bank ledger.
    """

    provider = "placeholder"
    authoritative = False
    capabilities = CBSAdapterCapabilities(reversal=True, reconciliation=True)

    def __init__(self, *, balances: dict[str, tuple[Decimal, str]] | None = None) -> None:
        self._balances = dict(balances or {"source-001": (Decimal("10000.00"), "ETB")})
        self._transactions: dict[str, _PlaceholderRecord] = {}
        self._idempotency: dict[str, str] = {}

    async def submit_transaction(
        self,
        request: TransactionRequest,
        *,
        idempotency_key: str,
    ) -> TransactionSubmission:
        existing_id = self._idempotency.get(idempotency_key)
        if existing_id is not None:
            record = self._transactions[existing_id]
            return TransactionSubmission(
                record.request.transaction_id,
                record.cbs_reference,
                record.status,
                record.submitted_at,
            )

        if request.amount <= Decimal("0"):
            raise CBSOperationError("placeholder CBS rejects non-positive amounts")

        reference = f"placeholder-{request.transaction_id}"
        submitted_at = utc_now()
        status = TransactionStatus.ACCEPTED
        record = _PlaceholderRecord(request, reference, status, submitted_at)
        self._transactions[request.transaction_id] = record
        self._idempotency[idempotency_key] = request.transaction_id
        return TransactionSubmission(request.transaction_id, reference, status, submitted_at)

    async def get_transaction_status(self, transaction_id: str) -> TransactionLookup:
        return await self.lookup_transaction(transaction_id)

    async def get_account_balance(self, account_id: str, *, currency: str) -> AccountBalance:
        try:
            balance, stored_currency = self._balances[account_id]
        except KeyError as exc:
            raise CBSOperationError(f"unknown placeholder account: {account_id}") from exc
        if stored_currency != currency:
            raise CBSOperationError(f"currency mismatch for placeholder account: {account_id}")
        return AccountBalance(account_id, balance, stored_currency, utc_now())

    async def get_account_status(self, account_id: str) -> AccountStatus:
        if account_id not in self._balances:
            raise CBSOperationError(f"unknown placeholder account: {account_id}")
        return AccountStatus(account_id, "ACTIVE", utc_now())

    async def lookup_transaction(self, transaction_id: str) -> TransactionLookup:
        try:
            record = self._transactions[transaction_id]
        except KeyError as exc:
            raise CBSOperationError(f"unknown placeholder transaction: {transaction_id}") from exc
        return TransactionLookup(
            record.request.transaction_id,
            record.cbs_reference,
            record.status,
            record.request.source_account,
            record.request.destination_account,
            record.request.amount,
            record.request.currency,
            utc_now(),
        )

    async def request_reversal(
        self,
        transaction_id: str,
        *,
        reversal_transaction_id: str,
        idempotency_key: str,
    ) -> ReversalResult:
        del idempotency_key
        record = self._transactions.get(transaction_id)
        if record is None:
            raise CBSOperationError(f"unknown placeholder transaction: {transaction_id}")
        return ReversalResult(
            original_transaction_id=transaction_id,
            reversal_transaction_id=reversal_transaction_id,
            status=TransactionStatus.POSTED,
            cbs_reference=f"placeholder-reversal-{reversal_transaction_id}",
            completed_at=utc_now(),
        )

    async def reconcile_transaction(self, transaction_id: str) -> ReconciliationResult:
        record = self._transactions.get(transaction_id)
        if record is None:
            raise CBSOperationError(f"unknown placeholder transaction: {transaction_id}")
        return ReconciliationResult(
            transaction_id,
            record.status,
            True,
            True,
            "placeholder adapter confirms synthetic debit and credit evidence",
            utc_now(),
        )
