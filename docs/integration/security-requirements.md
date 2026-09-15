# Security Requirements for Future CBS Integration

The placeholder implementation must never weaken the production security design.

## Required controls

- mTLS
- OAuth2 or signed requests
- service identity and certificate validation
- certificate rotation
- secret management and HSM/KMS
- RBAC/least privilege
- network allowlisting
- TLS 1.3 minimum
- audit logging

## Prohibited behavior

- no secrets in source control
- no production credentials in sample configuration
- no placeholder tokens used in production
- no exposure of private keys or certificates in the UI
- no silent fallback from production to simulation
