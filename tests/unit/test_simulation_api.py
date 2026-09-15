from tests.unit.test_enterprise_api import ApiTestClient, Auth, body

from sentinel.application.api import create_api


def test_simulator_health_and_scenario_catalog():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))

    health = client.get("/api/v1/simulator/health")
    scenarios = client.get("/api/v1/simulator/scenarios")

    assert health.status_code == 200
    assert health.json()["mode"] == "simulation"
    assert health.json()["warning"] == "SIMULATION MODE ONLY — no real bank ledger"
    assert scenarios.status_code == 200
    names = {item["name"] for item in scenarios.json()["scenarios"]}
    assert "normal_transaction" in names
    assert "timeout" in names
    assert "reconciliation" in names


def test_simulator_transaction_submission_uses_scenario_and_returns_provenance():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    headers = {
        "Authorization": "Bearer valid",
        "Idempotency-Key": "sim-transaction-1",
        "X-Correlation-ID": "sim-corr-1",
        "X-Trace-ID": "sim-trace-1",
    }

    response = client.post(
        "/api/v1/simulator/transactions",
        json={**body(), "scenario": "normal_transaction"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "normal_transaction"
    assert payload["mode"] == "simulation"
    assert payload["transaction_id"] == "api-txn-1"
    assert payload["state"] in {
        "RECEIVED",
        "VALIDATING",
        "ACCEPTED",
        "SUBMITTED_TO_CBS",
        "CBS_PROCESSING",
    }
    assert payload["correlation_id"] == "sim-corr-1"
    assert payload["trace_id"] == "sim-trace-1"


def test_simulator_timeout_scenario_returns_timeout_error():
    client = ApiTestClient(create_api(_real_orchestrator(), authentication=Auth()))
    headers = {
        "Authorization": "Bearer valid",
        "Idempotency-Key": "sim-timeout-1",
    }

    response = client.post(
        "/api/v1/simulator/transactions",
        json={**body(), "scenario": "timeout"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "UNKNOWN"
    assert payload["reconciliation"] == "pending"


def test_debit_without_credit_requires_reconciliation():
    client = ApiTestClient(create_api(_real_orchestrator(), authentication=Auth()))
    response = client.post(
        "/api/v1/simulator/transactions",
        json={
            **body(),
            "transaction_id": "sim-debit-without-credit",
            "scenario": "debit_without_credit",
        },
        headers={
            "Authorization": "Bearer valid",
            "Idempotency-Key": "sim-debit-without-credit-idem",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "CBS_PROCESSING"
    assert response.json()["reconciliation"] == "pending"


class FakeOrchestrator:
    async def process(self, request):
        from datetime import UTC, datetime

        from sentinel.domain.integrity import IntegrityDecision, IntegrityDecisionCode
        from sentinel.domain.protection import ProtectiveAction, ProtectiveDecision
        from sentinel.domain.transactions import Transaction

        return type(
            "Result",
            (),
            {
                "transaction": Transaction(request.transaction_id),
                "integrity": IntegrityDecision(IntegrityDecisionCode.ALLOW, request.transaction_id),
                "protective": ProtectiveDecision(
                    "action-1",
                    request.transaction_id,
                    ProtectiveAction.ALLOW,
                    "test",
                    datetime.now(UTC),
                    "test",
                ),
            },
        )()


def _real_orchestrator():
    from sentinel.adapters.cbs import SimulatorCBSAdapter
    from sentinel.application.orchestration.workflow import TransactionOrchestrator
    from sentinel.domain.integrity import IntegrityEngine
    from sentinel.domain.protection import ProtectiveAction, ProtectiveResponseEngine
    from sentinel.domain.risk import RiskEngine

    class Policy:
        async def decide(self, request, risk):
            return ProtectiveAction.ALLOW

    class Hooks:
        async def publish(self, event_type, transaction):
            return None

        async def request_reconciliation(self, transaction):
            return None

    return TransactionOrchestrator(
        cbs=SimulatorCBSAdapter(),
        integrity=IntegrityEngine(),
        risk=RiskEngine(),
        protection=ProtectiveResponseEngine(),
        policy=Policy(),
        reconciliation=Hooks(),
        events=Hooks(),
    )
