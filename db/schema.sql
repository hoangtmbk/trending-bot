-- TrendBot SQLite Schema
-- Version: 1

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    description     TEXT DEFAULT '',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    times_seen      INTEGER DEFAULT 1,
    raw_metrics     TEXT,
    momentum_score  REAL DEFAULT 0.0,
    normalized_score REAL DEFAULT 0.0,
    status          TEXT DEFAULT 'new' CHECK(status IN ('new', 'tracking', 'archived', 'dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_last_seen ON items(last_seen);
CREATE INDEX IF NOT EXISTS idx_items_normalized_score ON items(normalized_score);

CREATE TABLE IF NOT EXISTS item_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    recorded_at     TEXT NOT NULL,
    momentum_score  REAL,
    normalized_score REAL,
    raw_metrics     TEXT
);

CREATE INDEX IF NOT EXISTS idx_item_scores_item_id ON item_scores(item_id);
CREATE INDEX IF NOT EXISTS idx_item_scores_recorded_at ON item_scores(recorded_at);

CREATE TABLE IF NOT EXISTS item_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    analysis_type   TEXT NOT NULL CHECK(analysis_type IN ('filter', 'deep_dive', 'connection', 'topic_report')),
    created_at      TEXT NOT NULL,
    content         TEXT NOT NULL,
    prompt_version  TEXT
);

CREATE INDEX IF NOT EXISTS idx_item_analysis_item_id ON item_analysis(item_id);
CREATE INDEX IF NOT EXISTS idx_item_analysis_type ON item_analysis(analysis_type);

CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT DEFAULT '',
    source          TEXT DEFAULT 'system' CHECK(source IN ('system', 'user', 'llm-inferred')),
    created_at      TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    confidence      REAL DEFAULT 1.0,
    PRIMARY KEY (item_id, topic_id)
);

CREATE TABLE IF NOT EXISTS user_interests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    weight          REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'explicit' CHECK(source IN ('explicit', 'inferred')),
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_interests_topic ON user_interests(topic_id);

CREATE TABLE IF NOT EXISTS item_connections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_a_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    item_b_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relationship    TEXT NOT NULL CHECK(relationship IN ('competes_with', 'builds_on', 'same_topic', 'evolves_from')),
    description     TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_connections_a ON item_connections(item_a_id);
CREATE INDEX IF NOT EXISTS idx_connections_b ON item_connections(item_b_id);

CREATE TABLE IF NOT EXISTS digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_type     TEXT NOT NULL CHECK(digest_type IN ('daily', 'weekly', 'on_demand', 'alert')),
    created_at      TEXT NOT NULL,
    content_md      TEXT,
    content_html    TEXT,
    item_ids        TEXT
);

CREATE TABLE IF NOT EXISTS user_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK(action IN ('bookmarked', 'dismissed', 'deep_dive_requested', 'feedback')),
    payload         TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_actions_item_id ON user_actions(item_id);

CREATE TABLE IF NOT EXISTS task_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    priority        INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    result          TEXT,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority DESC);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
