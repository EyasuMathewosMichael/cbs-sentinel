# Backup and Restore

SENTINEL must treat PostgreSQL and the durable SENTINEL metadata store as the recovery source of truth. The objective is to produce a recoverable metadata and audit chain without inventing a new financial ledger.

## Backup

- Run a nightly full PostgreSQL logical or physical backup.
- Continuously ship Write-Ahead Logs (WAL) to the passive site for point-in-time recovery.
- Verify encrypted backups and credential isolation before archive rotation.

## Restore

- Restore the PostgreSQL cluster to the last consistent WAL point that satisfies the RPO target.
- Rehydrate the durable idempotency records and transaction-state history.
- Validate that replaying a request reuses the same idempotency keys and does not create a new financial effect.

## Recovery acceptance

- Restore succeeds only when PostgreSQL health, audit chain completeness, and idempotency stores are all verified.
- If the restore target is older than the configured RPO threshold, declare the recovery as failed and escalate to the incident owner.
