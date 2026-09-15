import asyncio
from decimal import Decimal

import pytest

from sentinel.adapters.cbs import (
    CBSOperationTimeout,
    CBSUnavailableError,
    ReversalResult,
    SimulatorCBSAdapter,
    TransactionStatus,
)
from sentinel.domain.integrity import TransactionRequest


def test_phase_20_cbs_bank_simulator_supports_requested_scenarios():
    adapter = SimulatorCBSAdapter()
    scenarios = adapter.supported_scenarios()

    required = {
        "normal_transaction",
        "timeout",
        "delayed_response",
        "debit_without_credit",
        "lost_response",
        "duplicate_request",
        "duplicate_posting",
        "reversal",
        "cbs_unavailable",
        "incorrect_balance_response",
    }
    assert required.issubset(set(scenarios))


def test_phase_20_simulator_timeout_scenario_normalizes_timeout():
    adapter = SimulatorCBSAdapter(scenario="timeout")
    request = TransactionRequest(
        "txn-timeout",
        "idem-timeout",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )

    async def run_submit():
        await adapter.submit_transaction(request, idempotency_key=request.idempotency_key)

    with pytest.raises(CBSOperationTimeout):
        asyncio.run(run_submit())


def test_phase_20_simulator_reversal_scenario_returns_reversal_evidence():
    adapter = SimulatorCBSAdapter(scenario="reversal")
    request = TransactionRequest(
        "txn-reversal",
        "idem-reversal",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )

    async def run_submit():
        return await adapter.request_reversal(
            request.transaction_id,
            reversal_transaction_id="reverse-1",
            idempotency_key="idem-reversal-1",
        )

    result = asyncio.run(run_submit())
    assert isinstance(result, ReversalResult)
    assert result.status is TransactionStatus.POSTED
    assert result.cbs_reference == "sim-reverse-1"


def test_phase_20_cbs_bank_simulator_supports_real_banking_failure_scenarios():
    adapter = SimulatorCBSAdapter()
    scenarios = adapter.supported_scenarios()

    required = {
        "partial_failure",
        "unknown",
        "timeout",
        "duplicate_posting",
        "delayed_posting",
        "reconciliation",
    }
    assert required.issubset(set(scenarios))


def test_phase_20_simulator_partial_failure_and_reconciliation_scenarios_expose_evidence():
    adapter = SimulatorCBSAdapter(scenario="partial_failure")
    request = TransactionRequest(
        "txn-partial",
        "idem-partial",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )

    async def run_scenario():
        submission = await adapter.submit_transaction(
            request, idempotency_key=request.idempotency_key
        )
        reconciliation = await adapter.reconcile_transaction(request.transaction_id)
        return submission, reconciliation

    submission, reconciliation = asyncio.run(run_scenario())
    assert submission.status is TransactionStatus.ACCEPTED
    assert reconciliation.status is TransactionStatus.UNKNOWN
    assert reconciliation.source_debited is True
    assert reconciliation.destination_credited is False


def test_phase_20_simulator_unavailable_scenario_normalizes_unavailability():
    adapter = SimulatorCBSAdapter(scenario="cbs_unavailable")
    request = TransactionRequest(
        "txn-unavailable",
        "idem-unavailable",
        "source",
        "destination",
        Decimal("10"),
        "ETB",
    )

    async def run_submit():
        await adapter.submit_transaction(request, idempotency_key=request.idempotency_key)

    with pytest.raises(CBSUnavailableError):
        asyncio.run(run_submit())
