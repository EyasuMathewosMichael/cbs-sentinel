"""FastAPI application for the versioned SENTINEL transaction API."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from sentinel.adapters.cbs import SimulatorCBSAdapter
from sentinel.application.orchestration.workflow import TransactionOrchestrator, WorkflowResult
from sentinel.domain.integrity import TransactionRequest
from sentinel.infrastructure.coordination import RedisCoordinator
from sentinel.security import (
    CertificatePolicy,
    EnterpriseSecurityPolicy,
    MTLSVerifier,
    SecurityControlError,
    ServiceIdentity,
)


class APIPrincipal(Protocol):
    subject: str
    roles: frozenset[str]


class AuthenticationHook(Protocol):
    async def authenticate(self, authorization: str | None) -> APIPrincipal: ...


class AuthorizationHook(Protocol):
    async def authorize(self, principal: APIPrincipal, action: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DefaultPrincipal:
    subject: str
    roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    subject: str
    roles: frozenset[str]
    service_identity: ServiceIdentity


class AllowAllAuthentication:
    async def authenticate(self, authorization: str | None) -> DefaultPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            raise APIError("AUTHENTICATION_REQUIRED", "Bearer authentication is required", 401)
        token = authorization[7:].strip()
        if not token:
            raise APIError("AUTHENTICATION_REQUIRED", "Bearer token is empty", 401)
        return DefaultPrincipal(token, frozenset({"transaction:write", "transaction:read"}))


class DenyByDefaultAuthentication:
    async def authenticate(self, authorization: str | None) -> APIPrincipal:
        del authorization
        raise APIError(
            "AUTHENTICATION_REQUIRED",
            "an external IAM authentication hook is required",
            401,
        )


class RoleAuthorization:
    def __init__(self, required_roles: dict[str, str] | None = None) -> None:
        self._required_roles = required_roles or {
            "transaction:write": "transaction:write",
            "transaction:read": "transaction:read",
        }

    async def authorize(self, principal: APIPrincipal, action: str) -> None:
        required = self._required_roles.get(action, action)
        if required not in principal.roles:
            raise APIError("FORBIDDEN", "principal is not authorized", 403)


class APIError(RuntimeError):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class TransactionRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128)
    source_account: str = Field(min_length=1, max_length=256)
    destination_account: str = Field(min_length=1, max_length=256)
    amount: str = Field(pattern=r"^[0-9]+(\.[0-9]+)?$")
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    transaction_type: str = "TRANSFER"
    scenario: str | None = None


SIMULATION_SCENARIO_DESCRIPTIONS = {
    "normal_transaction": "Deterministic success path; no CBS error is injected.",
    "timeout": "The simulator times out before returning an authoritative CBS result.",
    "unknown": "The simulator returns an unknown authoritative result and triggers a reconciliation review.",
    "partial_failure": "Only one side of the posting effect is observed and must be investigated.",
    "duplicate_request": "The same logical request is repeated and must be idempotent.",
    "duplicate_posting": "A duplicate posting condition is detected and requires reconciliation review.",
    "delayed_response": "The adapter responds later than the normal request path.",
    "delayed_posting": "The posting effect is delayed and remains pending authoritative evidence.",
    "cbs_unavailable": "The CBS is unavailable and must never be treated as a financial success.",
    "reconciliation": "A deterministic reconciliation scenario returns evidence for review.",
}


class TransactionResponse(BaseModel):
    transaction_id: str
    state: str
    correlation_id: str
    trace_id: str
    integrity_code: str
    protective_action: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    correlation_id: str
    trace_id: str


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> TransactionResponse | None: ...

    async def put(self, key: str, response: TransactionResponse) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._values: dict[str, TransactionResponse] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> TransactionResponse | None:
        async with self._lock:
            return self._values.get(key)

    async def put(self, key: str, response: TransactionResponse) -> None:
        async with self._lock:
            self._values.setdefault(key, response)


def _request_fingerprint(body: TransactionRequestModel) -> str:
    material = "|".join(
        (
            body.transaction_id,
            body.source_account,
            body.destination_account,
            body.amount,
            body.currency,
            body.transaction_type,
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def create_api(
    orchestrator: TransactionOrchestrator,
    *,
    authentication: AuthenticationHook | None = None,
    authorization: AuthorizationHook | None = None,
    idempotency: IdempotencyStore | None = None,
    redis: RedisCoordinator | None = None,
    mtls_verifier: MTLSVerifier | None = None,
    certificate_policy: CertificatePolicy | None = None,
    security_policy: EnterpriseSecurityPolicy | None = None,
    request_timeout_seconds: float = 10,
) -> FastAPI:
    """Create the API boundary; all financial decisions remain in the orchestrator/CBS."""
    if request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be positive")
    policy = security_policy or EnterpriseSecurityPolicy()
    policy.validate()
    if policy.environment == "production" and authentication is None:
        raise SecurityControlError("production API requires an external IAM authentication hook")
    if policy.environment == "production" and mtls_verifier is None:
        raise SecurityControlError("production API requires an mTLS verifier")
    certificate_controls = certificate_policy or CertificatePolicy()
    auth = authentication or DenyByDefaultAuthentication()
    authorizer = authorization or RoleAuthorization()
    idempotency_store = idempotency or InMemoryIdempotencyStore()
    idempotency_lock = asyncio.Lock()
    idempotency_fingerprints: dict[str, str] = {}
    app = FastAPI(title="SENTINEL Enterprise Transaction API", version="1.0.0")
    simulation_store: dict[str, dict[str, object]] = {}
    simulation_event_store: dict[str, list[dict[str, object]]] = defaultdict(list)
    simulator_adapter = SimulatorCBSAdapter()

    def request_identifiers(request: Request) -> tuple[str, str]:
        return (
            request.headers.get("X-Correlation-ID") or str(uuid4()),
            request.headers.get("X-Trace-ID") or str(uuid4()),
        )

    def error_response(request: Request, error: APIError) -> JSONResponse:
        correlation_id, trace_id = request_identifiers(request)
        response = JSONResponse(
            status_code=error.http_status,
            content=ErrorResponse(
                code=error.code,
                message=error.message,
                correlation_id=correlation_id,
                trace_id=trace_id,
            ).model_dump(),
        )
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Trace-ID"] = trace_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, error: APIError) -> JSONResponse:
        return error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del error
        return error_response(
            request,
            APIError("INVALID_REQUEST", "request validation failed", 422),
        )

    async def principal_dependency(
        request: Request,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
    ) -> APIPrincipal:
        principal = await auth.authenticate(authorization_header)
        if mtls_verifier is None:
            return principal
        peer_certificate = request.scope.get("sentinel.peer_certificate")
        if not isinstance(peer_certificate, bytes):
            raise APIError("MTLS_REQUIRED", "verified client certificate is required", 401)
        try:
            service_identity = await mtls_verifier.verify(peer_certificate)
        except SecurityControlError as error:
            raise APIError("MTLS_INVALID", "client certificate was rejected", 401) from error
        if not service_identity.name or not service_identity.namespace:
            raise APIError("MTLS_INVALID", "client service identity is incomplete", 401)
        try:
            certificate_controls.validate_identity(service_identity)
        except SecurityControlError as error:
            raise APIError(
                "MTLS_INVALID", "client certificate identity was rejected", 401
            ) from error
        return cast(
            APIPrincipal,
            VerifiedPrincipal(principal.subject, principal.roles, service_identity),
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy", "version": "v1"}

    @app.get("/", include_in_schema=False)
    async def simulation_home() -> RedirectResponse:
        return RedirectResponse(
            url="/simulation-ui",
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "version": "v1"}

    @app.get("/api/v1/simulator/health")
    async def simulator_health() -> dict[str, str]:
        return {
            "status": "simulation-ready",
            "mode": "simulation",
            "warning": "SIMULATION MODE ONLY — no real bank ledger",
            "version": "v1",
            "simulator": "deterministic",
            "cbs_authority": "non-authoritative",
        }

    @app.get("/api/v1/simulator/scenarios")
    async def simulator_scenarios() -> dict[str, list[dict[str, str]]]:
        scenarios = []
        for scenario in sorted(simulator_adapter.supported_scenarios()):
            scenarios.append(
                {
                    "name": scenario,
                    "description": SIMULATION_SCENARIO_DESCRIPTIONS.get(
                        scenario,
                        "Deterministic simulator scenario for controlled validation.",
                    ),
                }
            )
        return {"scenarios": scenarios}

    @app.get("/api/v1/simulator/transactions/{transaction_id}")
    async def simulation_transaction_detail(
        transaction_id: str,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
    ) -> dict[str, object]:
        await authorizer.authorize(principal, "transaction:read")
        entry = simulation_store.get(transaction_id)
        if entry is None:
            raise APIError("NOT_FOUND", "simulation transaction was not found", 404)
        return entry

    @app.get("/api/v1/simulator/transactions/{transaction_id}/events")
    async def simulation_transaction_events(
        transaction_id: str,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
    ) -> dict[str, object]:
        await authorizer.authorize(principal, "transaction:read")
        events = simulation_event_store.get(transaction_id, [])
        return {"transaction_id": transaction_id, "events": events}

    @app.post("/api/v1/simulator/transactions")
    async def create_simulation_transaction(
        body: TransactionRequestModel,
        response: Response,
        request: Request,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        trace_id: str | None = Header(default=None, alias="X-Trace-ID"),
    ) -> dict[str, object]:
        if not idempotency_key:
            raise APIError("INVALID_REQUEST", "Idempotency-Key is required", 400)
        await authorizer.authorize(principal, "transaction:write")
        scenario_name = body.scenario or "normal_transaction"
        if scenario_name not in simulator_adapter.supported_scenarios():
            raise APIError("INVALID_REQUEST", "unsupported simulation scenario", 400)

        simulation_client = SimulatorCBSAdapter(scenario=scenario_name)
        transaction_request = TransactionRequest(
            body.transaction_id,
            idempotency_key,
            body.source_account,
            body.destination_account,
            __import__("decimal").Decimal(body.amount),
            body.currency,
            body.transaction_type,
        )
        try:
            if isinstance(orchestrator, TransactionOrchestrator):
                process = orchestrator.process(transaction_request, cbs=simulation_client)
            else:
                process = orchestrator.process(transaction_request)
            scenario_result = await asyncio.wait_for(process, timeout=request_timeout_seconds)
        except TimeoutError as error:
            raise APIError("CBS_TIMEOUT", "simulation processing timed out", 504) from error
        reconciliation_scenarios = {
            "debit_without_credit",
            "delayed_posting",
            "duplicate_posting",
            "incorrect_balance_response",
            "partial_failure",
            "reconciliation",
            "unknown",
        }
        reconciliation_pending = (
            scenario_name in reconciliation_scenarios
            or scenario_result.transaction.state.value
            in {"UNKNOWN", "RECONCILIATION_PENDING", "MANUAL_REVIEW"}
        )
        payload = {
            "transaction_id": scenario_result.transaction.transaction_id,
            "state": scenario_result.transaction.state.value,
            "correlation_id": correlation_id or str(uuid4()),
            "trace_id": trace_id or str(uuid4()),
            "integrity_code": scenario_result.integrity.code.value,
            "protective_action": scenario_result.protective.action.value,
            "mode": "simulation",
            "warning": "SIMULATION MODE ONLY — no real bank ledger",
            "scenario": scenario_name,
            "cbs_status": "simulator",
            "reconciliation": "pending" if reconciliation_pending else "not-required",
            "idempotency_key": idempotency_key,
            "event_count": len(scenario_result.transaction.history),
        }
        simulation_store[scenario_result.transaction.transaction_id] = payload
        simulation_event_store[scenario_result.transaction.transaction_id] = [
            {"timestamp": entry.timestamp.isoformat(), "previous": entry.previous_state.value if entry.previous_state else None, "new": entry.new_state.value, "actor": entry.actor}
            for entry in scenario_result.transaction.history
        ]
        response.headers["X-Correlation-ID"] = payload["correlation_id"]
        response.headers["X-Trace-ID"] = payload["trace_id"]
        return payload

    @app.post("/api/v1/simulator/scenarios/{scenario}/execute")
    async def execute_simulation_scenario(
        scenario: str,
        body: TransactionRequestModel,
        response: Response,
        request: Request,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        trace_id: str | None = Header(default=None, alias="X-Trace-ID"),
    ) -> dict[str, object]:
        body.scenario = scenario
        return await create_simulation_transaction(
            body,
            response,
            request,
            principal=principal,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

    @app.get("/simulation-ui", response_class=HTMLResponse)
    async def simulation_ui_page() -> HTMLResponse:
        return HTMLResponse("""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>SENTINEL Simulation UI</title>
            <style>
                :root { color-scheme: light dark; }
                body { font-family: Inter, Segoe UI, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
                .wrap { max-width: 1200px; margin: 0 auto; padding: 32px 20px 80px; }
                .header { display: flex; justify-content: space-between; align-items: end; margin-bottom: 24px; }
                .tag { background: #1d4ed8; color: white; padding: 6px 10px; border-radius: 999px; font-size: 12px; letter-spacing: 0.08em; }
                .grid { display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 22px; }
                .panel { background: rgba(15,23,42,0.72); border: 1px solid rgba(148,163,184,0.2); border-radius: 16px; padding: 18px; }
                form { display: grid; gap: 12px; }
                .row { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
                label { display: grid; gap: 6px; font-size: 13px; color: #cbd5e1; }
                input, select, button { border-radius: 10px; border: 1px solid #334155; background: #0b1220; color: #e2e8f0; padding: 10px 12px; }
                button { cursor: pointer; background: linear-gradient(135deg, #2563eb, #1d4ed8); border: none; font-weight: 600; }
                .result { white-space: pre-wrap; background: #020817; border: 1px solid #1e293b; border-radius: 14px; padding: 16px; min-height: 180px; }
                .badge { display: inline-block; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; background: #14532d; color: #bbf7d0; }
            </style>
        </head>
        <body>
            <div class="wrap">
                <div class="header">
                    <div>
                        <div class="tag">SIMULATION ENVIRONMENT</div>
                        <h1>SENTINEL CBS Simulation Console</h1>
                    </div>
                    <div class="badge">NO REAL BANK LEDGER</div>
                </div>

                <div class="grid">
                    <div class="panel">
                        <h3>Transaction Simulator</h3>
                        <form id="txn-form">
                            <div class="row">
                                <label>Transaction ID<input name="transaction_id" value="sim-txn-001" /></label>
                                <label>Idempotency Key<input name="idempotency_key" value="sim-idem-001" /></label>
                            </div>
                            <div class="row">
                                <label>Source Account<input name="source_account" value="source" /></label>
                                <label>Destination Account<input name="destination_account" value="destination" /></label>
                            </div>
                            <div class="row">
                                <label>Amount<input name="amount" value="10.00" /></label>
                                <label>Currency<select name="currency"><option>ETB</option><option>USD</option><option>EUR</option></select></label>
                            </div>
                            <div class="row">
                                <label>Transaction Type<select name="transaction_type"><option>TRANSFER</option><option>PAYMENT</option></select></label>
                                <label>Scenario<select id="scenario"></select></label>
                            </div>
                            <div class="row">
                                <label>Correlation ID<input name="correlation_id" value="corr-sim-001" /></label>
                                <label>Trace ID<input name="trace_id" value="trace-sim-001" /></label>
                            </div>
                            <button type="submit">Submit simulation transaction</button>
                        </form>
                    </div>
                    <div class="panel">
                        <h3>System Status</h3>
                        <div id="status" class="result">Loading...</div>
                    </div>
                </div>

                <div class="panel" style="margin-top: 22px;">
                    <h3>Transaction Result</h3>
                    <div id="result" class="result">No transaction submitted yet.</div>
                </div>
            </div>

            <script>
                async function loadStatus() {
                    const res = await fetch('/api/v1/simulator/health');
                    const data = await res.json();
                    document.getElementById('status').textContent = JSON.stringify(data, null, 2);
                }

                async function loadScenarios() {
                    const res = await fetch('/api/v1/simulator/scenarios');
                    const payload = await res.json();
                    const select = document.getElementById('scenario');
                    payload.scenarios.forEach(item => {
                        const option = document.createElement('option');
                        option.value = item.name;
                        option.textContent = item.name;
                        select.appendChild(option);
                    });
                }

                document.getElementById('txn-form').addEventListener('submit', async (event) => {
                    event.preventDefault();
                    const form = new FormData(event.target);
                    const body = {
                        transaction_id: form.get('transaction_id'),
                        source_account: form.get('source_account'),
                        destination_account: form.get('destination_account'),
                        amount: form.get('amount'),
                        currency: form.get('currency'),
                        transaction_type: form.get('transaction_type'),
                        scenario: document.getElementById('scenario').value,
                    };
                    const res = await fetch('/api/v1/simulator/transactions', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer valid',
                            'Idempotency-Key': form.get('idempotency_key'),
                            'X-Correlation-ID': form.get('correlation_id'),
                            'X-Trace-ID': form.get('trace_id')
                        },
                        body: JSON.stringify(body)
                    });
                    const data = await res.json();
                    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
                });

                loadStatus();
                loadScenarios();
            </script>
        </body>
        </html>
        """)

    @app.post(
        "/api/v1/transactions",
        response_model=TransactionResponse,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    )
    async def create_transaction(
        body: TransactionRequestModel,
        response: Response,
        request: Request,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        trace_id: str | None = Header(default=None, alias="X-Trace-ID"),
    ) -> TransactionResponse:
        if not idempotency_key:
            raise APIError("INVALID_REQUEST", "Idempotency-Key is required", 400)
        await authorizer.authorize(principal, "transaction:write")
        if redis is not None:
            limit_result = await redis.rate_limit(
                f"api:{principal.subject}",
                limit=100,
                window_seconds=60,
            )
            if not limit_result.allowed:
                raise APIError("RATE_LIMITED", "request rate limit exceeded", 429)
        async with idempotency_lock:
            fingerprint = _request_fingerprint(body)
            existing_fingerprint = idempotency_fingerprints.get(idempotency_key)
            if existing_fingerprint is not None and existing_fingerprint != fingerprint:
                raise APIError(
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "Idempotency-Key was already used for a different request",
                    409,
                )
            cached = await idempotency_store.get(idempotency_key)
            if cached is not None:
                response.status_code = status.HTTP_200_OK
                response.headers["X-Correlation-ID"] = cached.correlation_id
                response.headers["X-Trace-ID"] = cached.trace_id
                return cached
            idempotency_fingerprints[idempotency_key] = fingerprint
            try:
                from decimal import Decimal

                result: WorkflowResult = await asyncio.wait_for(
                    orchestrator.process(
                        TransactionRequest(
                            body.transaction_id,
                            idempotency_key,
                            body.source_account,
                            body.destination_account,
                            Decimal(body.amount),
                            body.currency,
                            body.transaction_type,
                        )
                    ),
                    timeout=request_timeout_seconds,
                )
            except TimeoutError as error:
                raise APIError("CBS_TIMEOUT", "transaction processing timed out", 504) from error
            except ValueError as error:
                raise APIError("INVALID_REQUEST", str(error), 400) from error
            result_model = TransactionResponse(
                transaction_id=result.transaction.transaction_id,
                state=result.transaction.state.value,
                correlation_id=correlation_id or str(uuid4()),
                trace_id=trace_id or str(uuid4()),
                integrity_code=result.integrity.code.value,
                protective_action=result.protective.action.value,
            )
            await idempotency_store.put(idempotency_key, result_model)
        response.headers["X-Correlation-ID"] = result_model.correlation_id
        response.headers["X-Trace-ID"] = result_model.trace_id
        return result_model

    @app.get("/api/v1/transactions/{transaction_id}/status")
    async def transaction_status(
        transaction_id: str,
        principal: APIPrincipal = Depends(principal_dependency),  # noqa: B008
    ) -> dict[str, str]:
        await authorizer.authorize(principal, "transaction:read")
        return {"transaction_id": transaction_id, "status": "UNKNOWN"}

    return app