"""Deterministic, non-authoritative CBS simulator adapter."""

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
class _StoredTransaction:
    request: TransactionRequest
    cbs_reference: str
    status: TransactionStatus
    submitted_at: datetime


class SimulatorCBSAdapter:
    """Minimal in-memory adapter for contract and integration development.

    The simulator never claims to be an authoritative ledger and does not post
    balances automatically. Production adapters must implement their own bank
    protocol behind the same port.
    """

    capabilities = CBSAdapterCapabilities(reversal=False, reconciliation=True)

    def __init__(self, balances: dict[str, tuple[Decimal, str]] | None = None) -> None:
        self._balances = dict(balances or {})
        self._transactions: dict[str, _StoredTransaction] = {}
        self._idempotency: dict[str, str] = {}

    async def submit_transaction(
        self,
        request: TransactionRequest,
        *,
        idempotency_key: str,
    ) -> TransactionSubmission:
        existing_id = self._idempotency.get(idempotency_key)
        if existing_id is not None:
            stored = self._transactions[existing_id]
            return TransactionSubmission(
                stored.request.transaction_id,
                stored.cbs_reference,
                stored.status,
                stored.submitted_at,
            )
        reference = f"sim-{request.transaction_id}"
        submitted_at = utc_now()
        stored = _StoredTransaction(request, reference, TransactionStatus.ACCEPTED, submitted_at)
        self._transactions[request.transaction_id] = stored
        self._idempotency[idempotency_key] = request.transaction_id
        return TransactionSubmission(request.transaction_id, reference, stored.status, submitted_at)

    async def get_transaction_status(self, transaction_id: str) -> TransactionLookup:
        return await self.lookup_transaction(transaction_id)

    async def get_account_balance(self, account_id: str, *, currency: str) -> AccountBalance:
        try:
            balance, stored_currency = self._balances[account_id]
        except KeyError as error:
            raise CBSOperationError(f"unknown simulator account: {account_id}") from error
        if stored_currency != currency:
            raise CBSOperationError(f"currency mismatch for simulator account: {account_id}")
        return AccountBalance(account_id, balance, stored_currency, utc_now())

    async def get_account_status(self, account_id: str) -> AccountStatus:
        if account_id not in self._balances:
            raise CBSOperationError(f"unknown simulator account: {account_id}")
        return AccountStatus(account_id, "ACTIVE", utc_now())

    async def lookup_transaction(self, transaction_id: str) -> TransactionLookup:
        try:
            stored = self._transactions[transaction_id]
        except KeyError as error:
            raise CBSOperationError(f"unknown simulator transaction: {transaction_id}") from error
        request = stored.request
        return TransactionLookup(
            request.transaction_id,
            stored.cbs_reference,
            stored.status,
            request.source_account,
            request.destination_account,
            request.amount,
            request.currency,
            utc_now(),
        )

    async def request_reversal(
        self,
        transaction_id: str,
        *,
        reversal_transaction_id: str,
        idempotency_key: str,
    ) -> ReversalResult:
        raise CBSOperationError("simulator does not support reversal")

    async def reconcile_transaction(self, transaction_id: str) -> ReconciliationResult:
        lookup = await self.lookup_transaction(transaction_id)
        return ReconciliationResult(
            transaction_id,
            lookup.status,
            None,
            None,
            "simulator does not infer posting effects",
            utc_now(),
        )
