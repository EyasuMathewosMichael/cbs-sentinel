# CBS Adapter Contract

The canonical contract for any external Core Banking System is defined through the adapter layer in `src/sentinel/adapters/cbs`.

## Canonical methods

The adapter must support:

- `submit_transaction(...)`
- `get_transaction_status(...)`
- `get_account_balance(...)`
- `get_account_status(...)`
- `lookup_transaction(...)`
- `request_reversal(...)`
- `reconcile_transaction(...)`

The adapter contract is intentionally transport-neutral and bank-agnostic. Bank-specific protocols are abstracted behind the adapter implementation.

## Canonical data contracts

The contract includes stable models such as:

- `TransactionSubmission`
- `TransactionLookup`
- `AccountBalance`
- `AccountStatus`
- `ReconciliationResult`
- `ReversalResult`
- `TransactionStatus`

These models must remain the authoritative result types exposed to the SENTINEL domain layer.

## Safety requirements

- `UNKNOWN` is a first-class financial state
- a timeout does not imply success
- duplicate requests must be detected and handled safely
- no hidden financial ledger is created inside SENTINEL
- a placeholder or simulator adapter must never be mistaken for production
