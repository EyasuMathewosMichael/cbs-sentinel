ALTER TABLE sentinel_audit_records
    ADD COLUMN IF NOT EXISTS why VARCHAR(512),
    ADD COLUMN IF NOT EXISTS action VARCHAR(128),
    ADD COLUMN IF NOT EXISTS what VARCHAR(128),
    ADD COLUMN IF NOT EXISTS policy VARCHAR(128),
    ADD COLUMN IF NOT EXISTS rule VARCHAR(128),
    ADD COLUMN IF NOT EXISTS model VARCHAR(128);

UPDATE sentinel_audit_records
SET why = COALESCE(why, 'legacy audit event'),
    action = COALESCE(action, event_type),
    what = COALESCE(what, event_type);

ALTER TABLE sentinel_audit_records
    ALTER COLUMN why SET NOT NULL,
    ALTER COLUMN action SET NOT NULL,
    ALTER COLUMN what SET NOT NULL;