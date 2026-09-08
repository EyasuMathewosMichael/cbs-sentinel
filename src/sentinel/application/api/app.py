"""FastAPI application for the versioned SENTINEL transaction API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "version": "v1"}

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