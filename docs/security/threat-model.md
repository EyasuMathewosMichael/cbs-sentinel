# Phase 13 Security Threat Model

## Assets

- Transaction requests, account identifiers, and idempotency keys
- IAM credentials and service identities
- TLS certificates and private key material
- Secrets used to reach CBS, PostgreSQL, Redis, and event infrastructure
- KMS/HSM-protected encryption keys
- Privileged and break-glass approvals

## Trust Boundaries

1. External callers cross the API boundary through IAM authentication and authorization.
2. Service-to-service callers cross the mTLS boundary through a server-verified peer certificate.
3. Application processes access secrets only through an external secret provider contract.
4. Encryption key operations cross into an external KMS/HSM provider; key material is not held by SENTINEL.
5. Administrative actions cross RBAC, privileged-principal, expiry, and dual-control checks.

## Threats And Controls

| Threat | Control |
| --- | --- |
| Arbitrary bearer token accepted | Default API authentication denies access; production requires external IAM injection. |
| Role-based privilege escalation | RBAC denies unknown actions and requires `privileged=True` for administrative actions. |
| Service impersonation | Production API construction requires mTLS; peer certificates are supplied by the TLS terminator, never request headers. |
| Expired or unbound certificate | Certificate policy rejects expired/short-lived certificates and requires a service identity fingerprint. |
| Secret leakage through configuration output | Connection URLs are excluded from `Settings` representations; production requires an external secret backend. |
| Local key substitution | Production requires an external KMS/HSM provider and HSM-backed keys. |
| Break-glass self-approval or replay | Requester and approver must differ; requests expire; duplicate requests and approvals are rejected. |
| Untraceable security administration | Break-glass decisions emit security events through an injectable event sink. Immutable audit persistence remains a Phase 14 concern. |
| Weak transport configuration | Production requires TLS 1.3 and mTLS. |

## Residual Assumptions

- The deployed TLS terminator validates the certificate chain, revocation status, key usage, and TLS version before placing the verified certificate in the ASGI scope.
- IAM, secret management, certificate issuance/revocation, and KMS/HSM providers are external authoritative systems.
- Phase 14 will provide durable, tamper-evident audit persistence for the security events emitted here.