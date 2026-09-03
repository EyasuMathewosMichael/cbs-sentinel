"""Abstract Core Banking System adapter port."""

from typing import Protocol, runtime_checkable

from sentinel.adapters.cbs.contracts import (
    AccountBalance,
    AccountStatus,
    CBSAdapterCapabilities,
    ReconciliationResult,
    ReversalResult,
    TransactionLookup,
    TransactionSubmission,
)
from sentinel.domain.integrity import TransactionRequest


@runtime_checkable
class CBSAdapter(Protocol):
    """Bank-neutral asynchronous CBS integration contract."""

    @property
    def capabilities(self) -> CBSAdapterCapabilities:
        """Return explicitly supported operations."""
        ...

    async def submit_transaction(
        self,
        request: TransactionRequest,
        *,
        idempotency_key: str,
    ) -> TransactionSubmission:
        """Submit a transaction using the adapter's bank-specific protocol."""
        ...

    async def get_transaction_status(self, transaction_id: str) -> TransactionLookup:
        """Query authoritative CBS transaction status."""
        ...

    async def get_account_balance(self, account_id: str, *, currency: str) -> AccountBalance:
        """Query an authoritative CBS account balance."""
        ...

    async def get_account_status(self, account_id: str) -> AccountStatus:
        """Query authoritative CBS account status."""
        ...

    async def lookup_transaction(self, transaction_id: str) -> TransactionLookup:
        """Look up a transaction by SENTINEL or CBS identity."""
        ...

    async def request_reversal(
        self,
        transaction_id: str,
        *,
        reversal_transaction_id: str,
        idempotency_key: str,
    ) -> ReversalResult:
        """Request a separately identified reversal when supported."""
        ...

    async def reconcile_transaction(self, transaction_id: str) -> ReconciliationResult:
        """Query adapter-approved evidence for reconciliation."""
        ...
