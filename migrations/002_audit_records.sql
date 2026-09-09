CREATE TABLE IF NOT EXISTS sentinel_audit_records (
    event_id VARCHAR(128) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor VARCHAR(256) NOT NULL,
    why VARCHAR(512) NOT NULL,
    action VARCHAR(128) NOT NULL,
    what VARCHAR(128) NOT NULL,
    transaction_id VARCHAR(128),
    correlation_id VARCHAR(128),
    policy VARCHAR(128),
    rule VARCHAR(128),
    model VARCHAR(128),
    payload JSONB NOT NULL,
    previous_hash VARCHAR(128),
    event_hash VARCHAR(128) NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS ix_sentinel_audit_transaction_occurred
    ON sentinel_audit_records (transaction_id, occurred_at);

CREATE INDEX IF NOT EXISTS ix_sentinel_audit_event_type_occurred
    ON sentinel_audit_records (event_type, occurred_at);