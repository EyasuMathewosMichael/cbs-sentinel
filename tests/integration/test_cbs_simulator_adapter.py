import asyncio
from decimal import Decimal

import pytest

from sentinel.adapters.cbs import (
    CBSOperationError,
    SimulatorCBSAdapter,
    TransactionStatus,
)
from sentinel.domain.integrity import TransactionRequest


def test_simulator_adapter_supports_cbs_queries_and_reconciliation():
    adapter = SimulatorCBSAdapter({"source": (Decimal("100"), "ETB")})
    request = TransactionRequest(
        "txn-integration",
        "idem-integration",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )

    async def exercise():
        submission = await adapter.submit_transaction(request, idempotency_key="idem-integration")
        status = await adapter.get_transaction_status(request.transaction_id)
        lookup = await adapter.lookup_transaction(request.transaction_id)
        balance = await adapter.get_account_balance("source", currency="ETB")
        account_status = await adapter.get_account_status("source")
        reconciliation = await adapter.reconcile_transaction(request.transaction_id)
        return submission, status, lookup, balance, account_status, reconciliation

    submission, status, lookup, balance, account_status, reconciliation = asyncio.run(exercise())

    assert submission.status is TransactionStatus.ACCEPTED
    assert status.status is TransactionStatus.ACCEPTED
    assert lookup.cbs_reference == submission.cbs_reference
    assert balance.balance == Decimal("100")
    assert account_status.status == "ACTIVE"
    assert reconciliation.source_debited is None
    assert reconciliation.destination_credited is None


def test_simulator_reversal_capability_is_explicitly_unsupported():
    adapter = SimulatorCBSAdapter()

    async def request_reversal():
        return await adapter.request_reversal(
            "txn-integration",
            reversal_transaction_id="reverse-integration",
            idempotency_key="idem-reverse-integration",
        )

    with pytest.raises(CBSOperationError):
        asyncio.run(request_reversal())
