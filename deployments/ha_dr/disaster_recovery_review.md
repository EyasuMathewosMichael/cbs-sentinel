# Disaster Recovery Review

This review exercises the HA / DR contract and proves that a transaction state transition and financial effect remain consistent during recovery.

## Required simulations

1. Database failure: stop PostgreSQL and confirm recovery proceeds through durable WAL replay, not a new financial effect.
2. Node failure: remove or drain an application node and confirm no duplicate retry is accepted.
3. Service failure: stop the SENTINEL service endpoint and confirm the traffic gate rejects new posting until health is recovered.
4. Kubernetes failure: simulate the deployment controller failing pods and confirm no duplicate financial effect occurs.
5. Site failure: route traffic away from the failed site and ensure recovery uses the passive site with replay-safe idempotency.
6. Recovery: rotate traffic back to the healed site only after health checks and data consistency checks both pass.

## Safety invariants

- Every transaction must carry a stable transaction_id and idempotency_key.
- The duplicate registry must reject a repeated request with the same identity as DUPLICATE_TRANSACTION.
- The recovery action must produce no new debit or credit posting outside the already-observed state.
- The rollback route must be governed by RPO and RTO evidence before failback.

## Evidence gates

- RPO <= 15 minutes for PostgreSQL metadata/audit replay.
- RTO <= 30 minutes for route and service recovery.
- Backup restore evidence is accepted only when the idempotency and audit chain remain consistent.
