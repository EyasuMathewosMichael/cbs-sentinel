# Bank Integration Contract

This document defines the minimum contractual requirements for any future approved bank integration with SENTINEL. The bank must explicitly approve this contract before production use.

## 1. Integration interface

The bank must provide:

- the official API or protocol specification
- sandbox and production endpoints
- SDK or contract artifacts if applicable
- transaction operations and message examples
- status, balance, reversal, and reconciliation behavior

The integration boundary remains a bank-specific adapter behind the canonical CBS port defined in `src/sentinel/adapters/cbs/port.py`.

## 2. Financial contract

The bank must specify authoritative semantics for:

- debit commit timing
- credit commit timing
- processing states
- posted states
- failed states
- timeout handling
- unknown handling
- compensation and reversal behavior
- settlement and reconciliation timing

This contract must explicitly resolve the required business ambiguity and may include placeholders such as:

- `BANK_DEFINED_DEBIT_COMMIT_SEMANTIC: TBD`
- `BANK_DEFINED_CREDIT_COMMIT_SEMANTIC: TBD`
- `BANK_DEFINED_UNKNOWN_QUERY: TBD`

## 3. Security and access

The bank must provide:

- mTLS or equivalent mutual authentication
- OAuth2, signed requests, or approved service identity scheme
- certificate lifecycle and rotation ownership
- network allowlisting and firewall rules
- secret management and HSM/KMS policy
- RBAC and least-privilege access rules

No production credentials may be stored in source control.

## 4. Connectivity and infrastructure

The bank must provide:

- production connectivity requirements
- sandbox connectivity and test data separation
- endpoint hostnames, ports, and DNS policy
- timeout and retry behavior
- failure isolation and DR posture
- SLA/availability commitments

## 5. Data and compliance

The bank must provide data contract details for:

- account identifiers
- transaction identifiers
- correlation and trace identifiers
- settlement details
- fees and taxes
- required PII handling and retention
- audit retention and regulatory obligations

## 6. Testing and certification

The bank must provide evidence for:

- sandbox testing
- failure testing
- performance testing
- security testing
- certification and operational signoff
- incident response and rollback ownership

## 7. Operational ownership

The bank and the SENTINEL operator must agree on:

- support ownership
- incident escalation paths
- rollback and compensation procedures
- disaster recovery expectations
- production change control and approvals

Production integration remains blocked until all required items are approved by the bank and the SENTINEL operator.
