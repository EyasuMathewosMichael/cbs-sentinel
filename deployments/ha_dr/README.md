# High Availability and Disaster Recovery Architecture

This Phase 19 HA / DR architecture defines the SENTINEL operating model for:

- RPO: Recovery Point Objective of 15 minutes for PostgreSQL and audit metadata.
- RTO: Recovery Time Objective of 30 minutes for service restoration.
- Backup: nightly full backup plus continuous WAL archiving and point-in-time restore.
- Restore: restore the latest durable PostgreSQL metadata store and audit chain.
- Failover: promote the passive region and reroute traffic through the active service mesh endpoint.
- Failback: return primary traffic routing after the active region is verified healthy.
- Site failure: treat the complete outage of one region as a controlled route-away event.

Architecture principles:

1. Keep the CBS authoritative and SENTINEL non-authoritative.
2. Persist the idempotency and audit records in PostgreSQL with WAL archiving.
3. Prefer deterministic replay of requests over duplicate financial effects.
4. Require health-gated failover and explicit reversal of traffic only after recovery evidence.

## Required operating gates

- Validate PostgreSQL WAL archiving and restore point.
- Validate backup restore artifact in the passive site.
- Validate service mesh routing or DNS switch before promoting traffic.
- Validate the integrity engine replays the same idempotency and transaction identities without new effect.
