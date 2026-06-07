CREATE TABLE IF NOT EXISTS jobs_seen (
    slug          TEXT PRIMARY KEY,
    title         TEXT,
    url           TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    state         TEXT NOT NULL    -- 'open' | 'already_bid' | 'skipped' | 'drafted' | 'sent'
);

CREATE TABLE IF NOT EXISTS drafts (
    slug          TEXT PRIMARY KEY,
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL    -- 'pending' | 'approved' | 'sent' | 'rejected'
);

CREATE TABLE IF NOT EXISTS submissions (
    slug          TEXT PRIMARY KEY,
    sent_at       TEXT NOT NULL,
    amount        REAL,
    delivery_time TEXT,
    content       TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs_seen(state);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
