from decimal import Decimal

from sentinel.adapters.cbs import PlaceholderCBSAdapter, TransactionStatus
from sentinel.application.api import create_api
from sentinel.application.api.app import AllowAllAuthentication
from sentinel.application.orchestration.workflow import TransactionOrchestrator
from sentinel.domain.integrity import IntegrityEngine, TransactionRequest
from sentinel.domain.protection import ProtectiveAction, ProtectiveResponseEngine
from sentinel.domain.risk import RiskEngine


class _Policy:
    async def decide(self, request, risk):
        return ProtectiveAction.ALLOW


class _Hooks:
    async def publish(self, event_type, transaction):
        return None

    async def request_reconciliation(self, transaction):
        return None


def test_placeholder_cbs_adapter_implements_bank_contract():
    async def _run():
        adapter = PlaceholderCBSAdapter()
        request = TransactionRequest(
            "ph-txn-1",
            "idem-ph-1",
            "source-001",
            "destination-001",
            Decimal("25.50"),
            "ETB",
            "TRANSFER",
        )

        submission = await adapter.submit_transaction(request, idempotency_key="idem-ph-1")
        assert submission.transaction_id == "ph-txn-1"
        assert submission.status in {TransactionStatus.ACCEPTED, TransactionStatus.UNKNOWN}
        assert adapter.capabilities.reconciliation is True

        lookup = await adapter.lookup_transaction("ph-txn-1")
        assert lookup.transaction_id == "ph-txn-1"
        assert lookup.status in {TransactionStatus.ACCEPTED, TransactionStatus.UNKNOWN}

        balance = await adapter.get_account_balance("source-001", currency="ETB")
        assert isinstance(balance.balance, Decimal)
        assert balance.currency == "ETB"

        account = await adapter.get_account_status("source-001")
        assert account.account_id == "source-001"
        assert account.status == "ACTIVE"

    __import__("asyncio").run(_run())


def test_placeholder_bank_ui_uses_clear_environment_banner():
    orchestrator = TransactionOrchestrator(
        cbs=PlaceholderCBSAdapter(),
        integrity=IntegrityEngine(),
        risk=RiskEngine(),
        protection=ProtectiveResponseEngine(),
        policy=_Policy(),
        reconciliation=_Hooks(),
        events=_Hooks(),
    )
    app = create_api(orchestrator, authentication=AllowAllAuthentication())

    client = __import__("httpx").ASGITransport(app=app)
    # Request through a temporary client to verify the banking UI page and environment signage.
    async def _request():
        async with __import__("httpx").AsyncClient(
            transport=client, base_url="http://testserver"
        ) as http:
            page = await http.get("/banking-ui")
            health = await http.get("/api/v1/cbs/health")
            return page, health

    import asyncio

    page, health = asyncio.run(_request())
    assert page.status_code == 200
    assert "PLACEHOLDER CBS" in page.text or "SIMULATION" in page.text
    assert health.status_code == 200
    assert health.json()["provider"] in {"placeholder", "simulation"}
