# Site Failure

SENTINEL treats site failure as a full regional outage event that may affect the application, PostgreSQL store, Redis coordination cache, or event stream relay.

## Incident steps

1. Declare a site failure and stop routing new traffic to the failed region.
2. Switch traffic to the passive site by DNS or service routing only after the replica and health checks are verified.
3. Verify that the PostgreSQL WAL stream is recoverable and that the RPO is within the tolerance target.
4. Restore the idempotency and transaction-state metadata from the most recent accepted WAL-consistent record.
5. Validate failback after service health and reconciliation status are restored to the primary site.

## Governance

- Route changes must have an incident owner and explicit operator evidence.
- Financial effects remain non-authoritative and idempotent.
- A site failure record must include the route, transaction replay evidence, RPO/RTO, and restoration decision.
