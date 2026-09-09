# Failover and Failback

## Failover

- Detect a failed active site or recovery event using health, routing, and database availability evidence.
- Promote the passive PostgreSQL replica and pass traffic to the healthy site.
- Validate idempotency and audit records before replaying the latest confirmed transaction metadata.
- Require a clear route switch and service endpoint health check before any new transaction is accepted.

## Failback

- Restore the primary site after the outage issue is confirmed closed.
- Synchronize PostgreSQL state from the passive site using the latest WAL or replay artifact.
- Move traffic back only after the primary site passes all health, reconciliation, and idempotency checks.

## Safety rule

No duplicate financial effect is allowed during failover or failback. Reuse the same idempotency key and transaction fingerprint semantics.
