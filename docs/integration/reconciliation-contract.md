# Reconciliation Contract

This contract defines the SENTINEL-side reconciliation model for any future bank implementation.

## Canonical canonical outcomes

Possible outcomes include:

- `RECONCILED_SUCCESS`
- `RECONCILED_FAILURE`
- `REVERSAL_REQUIRED`
- `COMPENSATION_REQUIRED`
- `MANUAL_REVIEW`
- `UNKNOWN_REQUIRES_INVESTIGATION`

## Requirements from the bank side

The bank-specific adapter must later provide:

- authoritative transaction query
- reconciliation API or file export
- posting status
- debit status
- credit status
- settlement status
- reversal status
- discrepancy metadata
- timestamps and reference identifiers

## Safety rule

SENTINEL must not fabricate a successful reconciliation outcome. Only authoritative evidence from the bank can determine whether a posting or reversal is complete.
