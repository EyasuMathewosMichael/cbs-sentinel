"""Deterministic, non-authoritative CBS simulator adapter."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sentinel.adapters.cbs.contracts import (
    AccountBalance,
    AccountStatus,
    CBSAdapterCapabilities,
    CBSOperationError,
    CBSOperationTimeout,
    CBSUnavailableError,
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
    protocol behind the same port. The simulator can be configured with a
    deterministic scenario label for Phase 20 documentation and replay-safe
    review tests.
    """

    capabilities = CBSAdapterCapabilities(reversal=True, reconciliation=True)

    _SCENARIOS = {
        "normal_transaction",
        "partial_failure",
        "unknown",
        "timeout",
        "delayed_response",
        "delayed_posting",
        "debit_without_credit",
        "lost_response",
        "duplicate_request",
        "duplicate_posting",
        "reversal",
        "reconciliation",
        "cbs_unavailable",
        "incorrect_balance_response",
    }

    def __init__(
        self,
        balances: dict[str, tuple[Decimal, str]] | None = None,
        *,
        scenario: str = "normal_transaction",
    ) -> None:
        self._balances = dict(balances or {})
        self._transactions: dict[str, _StoredTransaction] = {}
        self._idempotency: dict[str, str] = {}
        self._scenario = scenario

    def supported_scenarios(self) -> set[str]:
        return set(self._SCENARIOS)

    async def submit_transaction(
        self,
        request: TransactionRequest,
        *,
        idempotency_key: str,
    ) -> TransactionSubmission:
        if self._scenario == "timeout":
            raise CBSOperationTimeout("simulator transaction timed out")
        if self._scenario == "cbs_unavailable":
            raise CBSUnavailableError("simulator bank endpoint unavailable")
        if self._scenario == "lost_response":
            raise CBSOperationError("simulator response was lost")
        if self._scenario == "unknown":
            reference = f"sim-{request.transaction_id}"
            submitted_at = utc_now()
            stored = _StoredTransaction(
                request, reference, TransactionStatus.UNKNOWN, submitted_at
            )
            self._transactions[request.transaction_id] = stored
            self._idempotency[idempotency_key] = request.transaction_id
            return TransactionSubmission(
                request.transaction_id, reference, stored.status, submitted_at
            )
        if self._scenario == "duplicate_request" or self._scenario == "duplicate_posting":
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                stored = self._transactions[existing_id]
                return TransactionSubmission(
                    stored.request.transaction_id,
                    stored.cbs_reference,
                    stored.status,
                    stored.submitted_at,
                )
        if self._scenario == "partial_failure":
            reference = f"sim-{request.transaction_id}"
            submitted_at = utc_now()
            stored = _StoredTransaction(
                request, reference, TransactionStatus.ACCEPTED, submitted_at
            )
            self._transactions[request.transaction_id] = stored
            self._idempotency[idempotency_key] = request.transaction_id
            return TransactionSubmission(
                request.transaction_id, reference, stored.status, submitted_at
            )
        if self._scenario == "debit_without_credit":
            return TransactionSubmission(
                request.transaction_id,
                f"sim-{request.transaction_id}",
                TransactionStatus.ACCEPTED,
                utc_now(),
            )
        if self._scenario == "incorrect_balance_response":
            if request.source_account not in self._balances:
                raise CBSOperationError("incorrect simulator balance response")
        if self._scenario == "delayed_response" or self._scenario == "delayed_posting":
            await asyncio.sleep(0)

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
        if self._scenario == "reversal":
            return ReversalResult(
                original_transaction_id=transaction_id,
                reversal_transaction_id=reversal_transaction_id,
                status=TransactionStatus.POSTED,
                cbs_reference=f"sim-reverse-{reversal_transaction_id.removeprefix('reverse-')}",
                completed_at=utc_now(),
            )
        raise CBSOperationError("simulator does not support reversal")

    async def reconcile_transaction(self, transaction_id: str) -> ReconciliationResult:
        if self._scenario == "partial_failure":
            return ReconciliationResult(
                transaction_id,
                TransactionStatus.UNKNOWN,
                True,
                False,
                "partial failure: debit observed without destination credit",
                utc_now(),
            )
        if self._scenario == "unknown":
            return ReconciliationResult(
                transaction_id,
                TransactionStatus.UNKNOWN,
                None,
                None,
                "authoritative status remains unknown; retry is prohibited",
                utc_now(),
            )
        if self._scenario == "duplicate_posting":
            return ReconciliationResult(
                transaction_id,
                TransactionStatus.POSTED,
                True,
                True,
                "duplicate posting evidence detected; require human review",
                utc_now(),
            )
        if self._scenario == "delayed_posting":
            return ReconciliationResult(
                transaction_id,
                TransactionStatus.PROCESSING,
                None,
                None,
                "delayed posting still pending authoritative evidence",
                utc_now(),
            )
        if self._scenario == "reconciliation":
            return ReconciliationResult(
                transaction_id,
                TransactionStatus.POSTED,
                True,
                True,
                "reconciliation evidence confirms debit and credit completeness",
                utc_now(),
            )

        lookup = await self.lookup_transaction(transaction_id)
        return ReconciliationResult(
            transaction_id,
            lookup.status,
            None,
            None,
            "simulator does not infer posting effects",
            utc_now(),
        )

    async def _delay(self) -> None:
        return None
