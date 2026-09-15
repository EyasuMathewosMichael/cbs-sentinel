# Authoritative Transaction Lifecycle Contract

This document defines the minimum lifecycle semantics that any future bank adapter must satisfy.

## Required lifecycle states

SENTINEL distinguishes the following states:

- request received
- validation
- accepted
- rejected
- submitted to CBS
- processing
- posted
- destination credited
- settled
- failed
- timeout
- unknown
- partial failure
- retry pending
- reconciliation pending
- reversal pending
- reversal completed
- compensation pending
- compensation completed
- manual review
- reconciled success
- reconciled failure

## Critical rules

- A successful HTTP response does not mean the money was posted.
- A timeout or lost response creates an `UNKNOWN` state until the authoritative CBS is queried.
- Duplicate submission must be handled via duplicate detection and idempotency semantics.
- Partial failure requires reconciliation, reversal, or compensation review.
- The authoritative CBS remains the source of truth for final financial outcome.

## Placeholder values

For a future bank adapter, the following semantics must be approved by the bank:

- `BANK_DEFINED_DEBIT_COMMIT_SEMANTIC: TBD`
- `BANK_DEFINED_CREDIT_COMMIT_SEMANTIC: TBD`
- `BANK_DEFINED_UNKNOWN_QUERY: TBD`
- `BANK_DEFINED_RETRY_POLICY: TBD`
- `BANK_DEFINED_PARTIAL_FAILURE_POLICY: TBD`

## Authority

The authoritative financial system is the approved bank ledger, not the SENTINEL application database or synthetic simulator state.
