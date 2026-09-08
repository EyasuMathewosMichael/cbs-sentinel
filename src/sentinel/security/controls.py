"""Fail-closed enterprise security control contracts and policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class SecurityControlError(RuntimeError):
    """Raised when an enterprise security control denies an operation."""


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    name: str
    namespace: str
    certificate_fingerprint: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.namespace.strip():
            raise SecurityControlError("service identity name and namespace are required")
        if not self.certificate_fingerprint.strip():
            raise SecurityControlError("service identity certificate fingerprint is required")


@dataclass(frozen=True, slots=True)
class IAMPrincipal:
    subject: str
    roles: frozenset[str]
    service_identity: ServiceIdentity | None = None
    privileged: bool = False


class MTLSVerifier(Protocol):
    async def verify(self, peer_certificate: bytes) -> ServiceIdentity: ...


class SecretProvider(Protocol):
    async def get_secret(self, name: str) -> str: ...


class CertificateManager(Protocol):
    async def issue(self, identity: ServiceIdentity) -> bytes: ...

    async def revoke(self, certificate_fingerprint: str) -> None: ...


class KMSHSMProvider(Protocol):
    async def encrypt(self, key_alias: str, plaintext: bytes) -> bytes: ...

    async def decrypt(self, key_alias: str, ciphertext: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    event_type: str
    subject: str
    request_id: str | None = None
    occurred_at: datetime = datetime.min.replace(tzinfo=UTC)


class SecurityEventSink(Protocol):
    def record(self, event: SecurityEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class EncryptionKeyReference:
    provider: str
    key_alias: str
    hardware_backed: bool


@dataclass(frozen=True, slots=True)
class CertificatePolicy:
    min_validity_seconds: int = 300
    require_client_auth: bool = True
    require_server_auth: bool = True

    def validate_expiry(self, not_after: datetime, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        if not_after.tzinfo is None or not_after <= current:
            raise SecurityControlError("certificate is expired or has no timezone")
        remaining = (not_after - current).total_seconds()
        if remaining < self.min_validity_seconds:
            raise SecurityControlError("certificate is too close to expiry")

    def validate_identity(self, identity: ServiceIdentity) -> None:
        if self.require_client_auth and not identity.certificate_fingerprint.strip():
            raise SecurityControlError("client certificate identity is missing")


@dataclass(frozen=True, slots=True)
class EnterpriseSecurityPolicy:
    environment: str = "development"
    mtls_required: bool = True
    min_tls_version: str = "TLSv1.3"
    secrets_backend: str = "external"
    kms_provider: str = "external-kms"
    hsm_required: bool = True
    iam_backend: str = "external-iam"

    def validate(self) -> None:
        if self.min_tls_version not in {"TLSv1.2", "TLSv1.3"}:
            raise SecurityControlError("unsupported minimum TLS version")
        if self.environment == "production":
            if not self.mtls_required:
                raise SecurityControlError("mTLS is required in production")
            if self.min_tls_version != "TLSv1.3":
                raise SecurityControlError("TLSv1.3 is required in production")
            if self.secrets_backend in {"environment", "plaintext"}:
                raise SecurityControlError("production secrets require an external manager")
            if self.kms_provider in {"local", "plaintext"}:
                raise SecurityControlError("production encryption requires KMS or HSM")
            if not self.hsm_required:
                raise SecurityControlError("production key material must be HSM-backed")
            if self.iam_backend in {"local", "none", "allow-all"}:
                raise SecurityControlError("production authentication requires external IAM")


class RBACAuthorizer:
    def __init__(self, permissions: dict[str, frozenset[str]] | None = None) -> None:
        self._permissions = permissions or {
            "transaction:read": frozenset({"transaction:read", "security:operator"}),
            "transaction:write": frozenset({"transaction:write"}),
            "security:admin": frozenset({"security:admin"}),
            "security:break-glass": frozenset({"security:break-glass"}),
        }

    def authorize(self, principal: IAMPrincipal, action: str) -> None:
        required_roles = self._permissions.get(action)
        if required_roles is None or not principal.roles.intersection(required_roles):
            raise SecurityControlError("principal is not authorized for this action")
        if action in {"security:admin", "security:break-glass"} and not principal.privileged:
            raise SecurityControlError("privileged principal is required for administrative access")


@dataclass(frozen=True, slots=True)
class BreakGlassRequest:
    request_id: str
    requester: str
    reason: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DualControlApproval:
    request_id: str
    approver: str
    approved_at: datetime


class PrivilegedAccessController:
    def __init__(
        self,
        authorizer: RBACAuthorizer | None = None,
        event_sink: SecurityEventSink | None = None,
    ) -> None:
        self._authorizer = authorizer or RBACAuthorizer()
        self._event_sink = event_sink
        self._requests: dict[str, BreakGlassRequest] = {}
        self._approvals: dict[str, DualControlApproval] = {}

    def request_break_glass(self, principal: IAMPrincipal, request: BreakGlassRequest) -> None:
        self._authorizer.authorize(principal, "security:break-glass")
        if not request.reason.strip() or request.expires_at <= datetime.now(UTC):
            raise SecurityControlError("break-glass request must have a future expiry and reason")
        if request.requester != principal.subject:
            raise SecurityControlError("break-glass requester does not match principal")
        if request.request_id in self._requests:
            raise SecurityControlError("break-glass request already exists")
        self._requests[request.request_id] = request
        self._record(SecurityEvent("break_glass_requested", principal.subject, request.request_id))

    def approve_break_glass(self, principal: IAMPrincipal, approval: DualControlApproval) -> None:
        self._authorizer.authorize(principal, "security:admin")
        request = self._requests.get(approval.request_id)
        if request is None:
            raise SecurityControlError("unknown break-glass request")
        if request.requester == approval.approver:
            raise SecurityControlError("dual control requires a separate approver")
        if approval.approved_at.tzinfo is None or approval.approved_at > request.expires_at:
            raise SecurityControlError("break-glass approval has expired")
        if approval.request_id in self._approvals:
            raise SecurityControlError("break-glass request is already approved")
        self._approvals[approval.request_id] = approval
        self._record(SecurityEvent("break_glass_approved", principal.subject, approval.request_id))

    def is_active(self, request_id: str, *, now: datetime | None = None) -> bool:
        request = self._requests.get(request_id)
        approval = self._approvals.get(request_id)
        current = now or datetime.now(UTC)
        return (
            request is not None
            and approval is not None
            and approval.approved_at <= current
            and current < request.expires_at
        )

    def _record(self, event: SecurityEvent) -> None:
        if self._event_sink is not None:
            self._event_sink.record(event)