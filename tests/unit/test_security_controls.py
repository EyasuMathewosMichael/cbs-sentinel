from datetime import UTC, datetime, timedelta

import pytest

from sentinel.config import Settings
from sentinel.security import (
    BreakGlassRequest,
    CertificatePolicy,
    DualControlApproval,
    EnterpriseSecurityPolicy,
    IAMPrincipal,
    PrivilegedAccessController,
    RBACAuthorizer,
    SecurityControlError,
    SecurityEvent,
    ServiceIdentity,
)


def test_production_security_policy_requires_external_controls():
    with pytest.raises(SecurityControlError):
        EnterpriseSecurityPolicy(
            environment="production",
            min_tls_version="TLSv1.2",
            secrets_backend="environment",
            kms_provider="local",
            hsm_required=False,
        ).validate()

    EnterpriseSecurityPolicy(environment="production").validate()


def test_settings_load_and_validate_security_controls(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTINEL_MIN_TLS_VERSION", "TLSv1.2")
    settings = Settings.from_environment()

    with pytest.raises(SecurityControlError):
        settings.validate_security()


def test_rbac_denies_unknown_or_insufficient_roles():
    authorizer = RBACAuthorizer()
    reader = IAMPrincipal("reader", frozenset({"transaction:read"}))

    authorizer.authorize(reader, "transaction:read")
    with pytest.raises(SecurityControlError):
        authorizer.authorize(reader, "transaction:write")
    with pytest.raises(SecurityControlError):
        authorizer.authorize(reader, "security:unknown")

    with pytest.raises(SecurityControlError):
        authorizer.authorize(
            IAMPrincipal("operator", frozenset({"security:admin"})),
            "security:admin",
        )


def test_service_identity_requires_certificate_binding():
    with pytest.raises(SecurityControlError):
        ServiceIdentity("sentinel", "production", "")


def test_certificate_policy_rejects_expired_and_short_lived_certificates():
    policy = CertificatePolicy(min_validity_seconds=300)
    now = datetime.now(UTC)

    with pytest.raises(SecurityControlError):
        policy.validate_expiry(now - timedelta(seconds=1), now=now)
    with pytest.raises(SecurityControlError):
        policy.validate_expiry(now + timedelta(seconds=299), now=now)

    policy.validate_expiry(now + timedelta(seconds=301), now=now)


def test_break_glass_requires_privileged_role_and_independent_dual_control():
    events: list[SecurityEvent] = []

    class EventSink:
        def record(self, event):
            events.append(event)

    controller = PrivilegedAccessController(event_sink=EventSink())
    requester = IAMPrincipal("operator", frozenset({"security:break-glass"}), privileged=True)
    approver = IAMPrincipal("admin", frozenset({"security:admin"}), privileged=True)
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    request = BreakGlassRequest("bg-1", requester.subject, "CBS outage", expires_at)

    controller.request_break_glass(requester, request)
    with pytest.raises(SecurityControlError):
        controller.approve_break_glass(
            requester,
            DualControlApproval("bg-1", requester.subject, datetime.now(UTC)),
        )

    controller.approve_break_glass(
        approver,
        DualControlApproval("bg-1", approver.subject, datetime.now(UTC)),
    )
    assert controller.is_active("bg-1")
    assert [event.event_type for event in events] == [
        "break_glass_requested",
        "break_glass_approved",
    ]
    with pytest.raises(SecurityControlError):
        controller.approve_break_glass(
            approver,
            DualControlApproval("bg-1", approver.subject, datetime.now(UTC)),
        )


def test_settings_repr_does_not_expose_connection_secrets(monkeypatch):
    monkeypatch.setenv(
        "SENTINEL_DATABASE_URL",
        "postgresql+asyncpg://user:super-secret@localhost/sentinel",
    )
    monkeypatch.setenv("SENTINEL_REDIS_URL", "rediss://:redis-secret@localhost:6380/0")
    rendered = repr(Settings.from_environment())

    assert "super-secret" not in rendered
    assert "redis-secret" not in rendered