import asyncio
import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sentinel.adapters.cbs import (
    CBSAdapter,
    CBSAdapterCapabilities,
    CBSAuthenticationError,
    CBSMalformedResponseError,
    CBSOperationTimeout,
    CBSUnavailableError,
    SimulatorCBSAdapter,
    TransactionStatus,
    TransactionSubmission,
    execute_cbs_call,
)
from sentinel.domain.integrity import TransactionRequest


class FakeCBSAdapter:
    capabilities = CBSAdapterCapabilities(reversal=True, reconciliation=True)

    async def submit_transaction(self, request, *, idempotency_key):
        return TransactionSubmission(
            request.transaction_id,
            "cbs-ref-1",
            TransactionStatus.ACCEPTED,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def get_transaction_status(self, transaction_id):
        raise NotImplementedError

    async def get_account_balance(self, account_id, *, currency):
        raise NotImplementedError

    async def get_account_status(self, account_id):
        raise NotImplementedError

    async def lookup_transaction(self, transaction_id):
        raise NotImplementedError

    async def request_reversal(self, transaction_id, *, reversal_transaction_id, idempotency_key):
        raise NotImplementedError

    async def reconcile_transaction(self, transaction_id):
        raise NotImplementedError


def test_fake_adapter_satisfies_bank_neutral_protocol():
    adapter = FakeCBSAdapter()

    assert isinstance(adapter, CBSAdapter)
    assert adapter.capabilities.reversal
    assert adapter.capabilities.reconciliation


@pytest.mark.parametrize(
    "method_name",
    [
        "submit_transaction",
        "get_transaction_status",
        "get_account_balance",
        "get_account_status",
        "lookup_transaction",
        "request_reversal",
        "reconcile_transaction",
    ],
)
def test_cbs_operations_are_async(method_name):
    assert inspect.iscoroutinefunction(getattr(FakeCBSAdapter, method_name))


def test_accepted_submission_is_distinct_from_posted():
    submission = TransactionSubmission(
        "txn-1",
        "cbs-ref-1",
        TransactionStatus.ACCEPTED,
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert submission.status is TransactionStatus.ACCEPTED
    assert submission.status is not TransactionStatus.POSTED


def test_timeout_is_normalized_without_claiming_financial_failure():
    async def slow_operation():
        await asyncio.sleep(0.05)

    with pytest.raises(CBSOperationTimeout):
        asyncio.run(execute_cbs_call(slow_operation(), timeout_seconds=0.001))


def test_unavailability_is_normalized():
    async def unavailable_operation():
        raise ConnectionError("connection refused")

    with pytest.raises(CBSUnavailableError):
        asyncio.run(execute_cbs_call(unavailable_operation(), timeout_seconds=1))


def test_authentication_error_is_preserved_at_adapter_boundary():
    async def authentication_failure():
        raise CBSAuthenticationError("authentication failed")

    with pytest.raises(CBSAuthenticationError):
        asyncio.run(execute_cbs_call(authentication_failure(), timeout_seconds=1))


def test_malformed_response_is_rejected():
    with pytest.raises(CBSMalformedResponseError):
        TransactionSubmission("", "ref", TransactionStatus.ACCEPTED, datetime.now(UTC))


def test_simulator_submission_is_idempotent_and_not_posted():
    adapter = SimulatorCBSAdapter({"source": (Decimal("100"), "ETB")})
    request = TransactionRequest(
        "txn-sim", "idem-sim", "source", "destination", Decimal("10"), "ETB"
    )

    import asyncio

    first, second = asyncio.run(_submit_twice(adapter, request))

    assert first == second
    assert first.status is TransactionStatus.ACCEPTED


async def _submit_twice(adapter, request):
    first = await adapter.submit_transaction(request, idempotency_key=request.idempotency_key)
    second = await adapter.submit_transaction(request, idempotency_key=request.idempotency_key)
    return first, second
