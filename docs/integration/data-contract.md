# Data Contract

The future bank adapter must define a safe data contract that does not leak protected information into the SENTINEL domain or browser UI.

## Required attributes

- transaction_id
- source_account
- destination_account
- amount
- currency
- transaction_type
- idempotency_key
- correlation_id
- trace_id
- created_at
- updated_at
- status
- failure_code
- failure_reason
- reconciliation_state
- adapter/provider
- policy_version

## Prohibited exposure

- passwords
- tokens
- certificates
- private keys
- raw bank credentials
- unnecessary PII

Only masked account identifiers and safe metadata may appear in logs or responses.
