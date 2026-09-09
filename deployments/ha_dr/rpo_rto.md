# RPO and RTO

SENTINEL HA / DR target:

- RPO: 15 minutes maximum data loss tolerance for PostgreSQL metadata and audit records.
- RTO: 30 minutes maximum time to restore the primary control-plane endpoint after a site failure event.

Measurement:

- RPO is measured by the age of the latest successful PostgreSQL physical backup or WAL restore point.
- RTO is measured from incident declaration to verified system health and traffic acceptance.

Engineering policy:

- Continuous WAL shipping must be confirmed before a failover action is allowed.
- Recovery is a controlled restore operation only when the recovery artifacts satisfy the target RPO.
- RTO is considered a fail only when service endpoints remain unhealthy after the target threshold.
