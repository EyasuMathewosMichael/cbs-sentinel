CREATE TABLE IF NOT EXISTS sentinel_transactions (
    transaction_id VARCHAR(128) PRIMARY KEY,
    request_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL UNIQUE,
    source_account VARCHAR(256) NOT NULL,
    destination_account VARCHAR(256) NOT NULL,
    amount NUMERIC(38, 18) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL,
    transaction_type VARCHAR(64) NOT NULL,
    state VARCHAR(64) NOT NULL,
    cbs_reference VARCHAR(256),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_sentinel_transactions_state ON sentinel_transactions (state);
CREATE INDEX IF NOT EXISTS ix_sentinel_transactions_created_at ON sentinel_transactions (created_at);

CREATE TABLE IF NOT EXISTS sentinel_transaction_state_history (
    history_id BIGSERIAL PRIMARY KEY,
    transaction_id VARCHAR(128) NOT NULL REFERENCES sentinel_transactions(transaction_id) ON DELETE CASCADE,
    previous_state VARCHAR(64),
    new_state VARCHAR(64) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_sentinel_state_history_transaction
    ON sentinel_transaction_state_history (transaction_id, occurred_at);

CREATE TABLE IF NOT EXISTS sentinel_idempotency_records (
    idempotency_key VARCHAR(256) PRIMARY KEY,
    transaction_id VARCHAR(128) NOT NULL UNIQUE,
    request_fingerprint VARCHAR(128) NOT NULL,
    response_status VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_sentinel_idempotency_expires_at
    ON sentinel_idempotency_records (expires_at);