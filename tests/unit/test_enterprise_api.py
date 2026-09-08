import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from sentinel.application.api import create_api
from sentinel.application.api.app import APIError, DefaultPrincipal
from sentinel.domain.integrity import IntegrityDecision, IntegrityDecisionCode
from sentinel.domain.protection import ProtectiveAction, ProtectiveDecision
from sentinel.domain.transactions import Transaction


class FakeOrchestrator:
    def __init__(self, *, delay=0):
        self.calls = []
        self.delay = delay

    async def process(self, request):
        import asyncio

        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return type(
            "Result",
            (),
            {
                "transaction": Transaction(request.transaction_id),
                "integrity": IntegrityDecision(
                    IntegrityDecisionCode.ALLOW, request.transaction_id
                ),
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


class InvalidTransactionOrchestrator:
    async def process(self, request):
        raise ValueError("transaction is invalid")


class Auth:
    async def authenticate(self, authorization):
        if authorization != "Bearer valid":
            raise APIError("AUTHENTICATION_REQUIRED", "invalid credentials", 401)
        return DefaultPrincipal("user-1", frozenset({"transaction:write", "transaction:read"}))


class ReadOnlyAuth:
    async def authenticate(self, authorization):
        return DefaultPrincipal("reader", frozenset({"transaction:read"}))


class LimitedRedis:
    async def rate_limit(self, key, *, limit, window_seconds):
        from sentinel.infrastructure.coordination.redis import RedisRateLimitResult

        return RedisRateLimitResult(False, limit + 1, limit, 30)


class ApiTestClient:
    def __init__(self, app):
        self._app = app

    def request(self, method, url, **kwargs):
        async def _request():
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(_request())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def body():
    return {
        "transaction_id": "api-txn-1",
        "source_account": "source",
        "destination_account": "destination",
        "amount": "10.00",
        "currency": "ETB",
    }


def test_versioned_health_and_transaction_idempotency():
    orchestrator = FakeOrchestrator()
    client = ApiTestClient(create_api(orchestrator, authentication=Auth()))
    headers = {
        "Authorization": "Bearer valid",
        "Idempotency-Key": "api-idem-1",
        "X-Correlation-ID": "corr-1",
        "X-Trace-ID": "trace-1",
    }

    assert client.get("/api/v1/health").status_code == 200
    first = client.post("/api/v1/transactions", json=body(), headers=headers)
    second = client.post("/api/v1/transactions", json=body(), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(orchestrator.calls) == 1
    assert first.json()["correlation_id"] == "corr-1"
    assert first.headers["X-Correlation-ID"] == "corr-1"
    assert first.headers["X-Trace-ID"] == "trace-1"


def test_idempotency_key_cannot_be_reused_for_a_different_request():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    headers = {
        "Authorization": "Bearer valid",
        "Idempotency-Key": "same-key",
        "X-Correlation-ID": "corr-conflict",
        "X-Trace-ID": "trace-conflict",
    }

    first = client.post("/api/v1/transactions", json=body(), headers=headers)
    conflicting = client.post(
        "/api/v1/transactions",
        json={**body(), "amount": "11.00"},
        headers=headers,
    )

    assert first.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert conflicting.json()["correlation_id"] == "corr-conflict"
    assert conflicting.headers["X-Trace-ID"] == "trace-conflict"


def test_authentication_authorization_and_required_idempotency():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    assert client.post("/api/v1/transactions", json=body()).status_code == 401
    assert client.post(
        "/api/v1/transactions", json=body(), headers={"Authorization": "Bearer valid"}
    ).status_code == 400

    read_only = ApiTestClient(create_api(FakeOrchestrator(), authentication=ReadOnlyAuth()))
    response = read_only.post(
        "/api/v1/transactions",
        json=body(),
        headers={"Authorization": "Bearer valid", "Idempotency-Key": "idem"},
    )
    assert response.status_code == 403


def test_validation_and_timeout_errors_are_standardized():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    invalid = client.post(
        "/api/v1/transactions",
        json={**body(), "amount": "not-money"},
        headers={"Authorization": "Bearer valid", "Idempotency-Key": "idem"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_REQUEST"

    malformed = client.post(
        "/api/v1/transactions",
        json={**body(), "unexpected": "value"},
        headers={
            "Authorization": "Bearer valid",
            "Idempotency-Key": "malformed",
            "X-Correlation-ID": "corr-malformed",
            "X-Trace-ID": "trace-malformed",
        },
    )
    assert malformed.status_code == 422
    assert malformed.json() == {
        "code": "INVALID_REQUEST",
        "message": "request validation failed",
        "correlation_id": "corr-malformed",
        "trace_id": "trace-malformed",
    }
    assert malformed.headers["X-Correlation-ID"] == "corr-malformed"
    assert malformed.headers["X-Trace-ID"] == "trace-malformed"

    delayed = ApiTestClient(
        create_api(
            FakeOrchestrator(delay=0.05),
            authentication=Auth(),
            request_timeout_seconds=0.001,
        )
    )
    timeout = delayed.post(
        "/api/v1/transactions",
        json=body(),
        headers={"Authorization": "Bearer valid", "Idempotency-Key": "timeout"},
    )
    assert timeout.status_code == 504
    assert timeout.json()["code"] == "CBS_TIMEOUT"


def test_invalid_transaction_from_orchestrator_is_standardized():
    client = ApiTestClient(create_api(InvalidTransactionOrchestrator(), authentication=Auth()))
    response = client.post(
        "/api/v1/transactions",
        json=body(),
        headers={
            "Authorization": "Bearer valid",
            "Idempotency-Key": "invalid-transaction",
            "X-Correlation-ID": "corr-invalid",
            "X-Trace-ID": "trace-invalid",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "transaction is invalid",
        "correlation_id": "corr-invalid",
        "trace_id": "trace-invalid",
    }


def test_rate_limit_returns_structured_error_before_orchestration():
    orchestrator = FakeOrchestrator()
    client = ApiTestClient(create_api(orchestrator, authentication=Auth(), redis=LimitedRedis()))
    response = client.post(
        "/api/v1/transactions",
        json=body(),
        headers={"Authorization": "Bearer valid", "Idempotency-Key": "limited"},
    )

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert orchestrator.calls == []


def test_unknown_transaction_status_is_explicit_and_authenticated():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    response = client.get(
        "/api/v1/transactions/does-not-exist/status",
        headers={
            "Authorization": "Bearer valid",
            "X-Correlation-ID": "corr-unknown",
            "X-Trace-ID": "trace-unknown",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "transaction_id": "does-not-exist",
        "status": "UNKNOWN",
    }


def test_error_responses_are_standardized_for_unauthorized_requests():
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    response = client.post(
        "/api/v1/transactions",
        json=body(),
        headers={"X-Correlation-ID": "corr-unauthorized", "X-Trace-ID": "trace-unauthorized"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "invalid credentials",
        "correlation_id": "corr-unauthorized",
        "trace_id": "trace-unauthorized",
    }
    assert response.headers["X-Correlation-ID"] == "corr-unauthorized"
    assert response.headers["X-Trace-ID"] == "trace-unauthorized"


@pytest.mark.parametrize("path", ["/api/v1/ready", "/api/v1/transactions/api-txn-1/status"])
def test_versioned_read_endpoints(path):
    client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth()))
    response = client.get(path, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200