"""SQLite schema definitions for Medina."""
from __future__ import annotations

TABLES: list[str] = [
    # ── Tenants ───────────────────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS tenants (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Users ─────────────────────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS users (
        id              TEXT PRIMARY KEY,
        email           TEXT UNIQUE NOT NULL,
        name            TEXT NOT NULL,
        hashed_password TEXT NOT NULL,
        tenant_id       TEXT NOT NULL REFERENCES tenants(id),
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Projects ──────────────────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS projects (
        id            TEXT PRIMARY KEY,
        source_path   TEXT NOT NULL,
        source_key    TEXT NOT NULL,
        project_name  TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'pending',
        tenant_id     TEXT NOT NULL DEFAULT 'default',
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Chat messages ─────────────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS chat_messages (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       TEXT NOT NULL,
        role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content          TEXT NOT NULL,
        intent           TEXT DEFAULT NULL,
        context_snapshot TEXT DEFAULT NULL,
        metadata         TEXT DEFAULT NULL,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )""",

    # ── Corrections (per-project) ─────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS corrections (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id    TEXT NOT NULL,
        source_key    TEXT NOT NULL DEFAULT '',
        action        TEXT NOT NULL,
        fixture_code  TEXT NOT NULL,
        reason        TEXT NOT NULL DEFAULT 'other',
        reason_detail TEXT NOT NULL DEFAULT '',
        fixture_data  TEXT NOT NULL DEFAULT '{}',
        spec_patches  TEXT NOT NULL DEFAULT '{}',
        origin        TEXT NOT NULL DEFAULT 'user',
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Learnings (per source file) ───────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS learnings (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        source_key       TEXT NOT NULL UNIQUE,
        source_name      TEXT NOT NULL DEFAULT '',
        source_path      TEXT NOT NULL DEFAULT '',
        corrections_json TEXT NOT NULL DEFAULT '[]',
        times_applied    INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Global patterns ───────────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS global_patterns (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_type    TEXT NOT NULL,
        fixture_code    TEXT NOT NULL DEFAULT '',
        description     TEXT NOT NULL DEFAULT '',
        source_count    INTEGER NOT NULL DEFAULT 0,
        examples_json   TEXT NOT NULL DEFAULT '[]',
        global_hint_json TEXT NOT NULL DEFAULT '{}',
        source_keys_json TEXT NOT NULL DEFAULT '[]',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(pattern_type, fixture_code)
    )""",

    # ── COVE verification results ─────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS cove_results (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id    TEXT NOT NULL,
        agent_id      INTEGER NOT NULL,
        agent_name    TEXT NOT NULL DEFAULT '',
        passed        INTEGER NOT NULL DEFAULT 0,
        confidence    REAL NOT NULL DEFAULT 0.0,
        issues_json   TEXT NOT NULL DEFAULT '[]',
        reasoning     TEXT NOT NULL DEFAULT '',
        retry_count   INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Agent plans (pre-execution reasoning) ─────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS agent_plans (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id           TEXT NOT NULL,
        agent_id             INTEGER NOT NULL,
        agent_name           TEXT NOT NULL DEFAULT '',
        plan_text            TEXT NOT NULL DEFAULT '',
        strategy_json        TEXT NOT NULL DEFAULT '{}',
        expected_challenges  TEXT NOT NULL DEFAULT '[]',
        created_at           TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Password reset tokens ────────────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    TEXT NOT NULL REFERENCES users(id),
        token      TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        used       INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # ── Runtime parameter overrides ───────────────────────────────────
    """\
    CREATE TABLE IF NOT EXISTS runtime_params (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scope       TEXT NOT NULL DEFAULT 'global',
        scope_key   TEXT NOT NULL DEFAULT '',
        param_key   TEXT NOT NULL,
        param_value TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(scope, scope_key, param_key)
    )""",
]

INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_corrections_project ON corrections(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_corrections_source ON corrections(source_key)",
    "CREATE INDEX IF NOT EXISTS idx_learnings_source ON learnings(source_key)",
    "CREATE INDEX IF NOT EXISTS idx_cove_project ON cove_results(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_plans_project ON agent_plans(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_params_scope ON runtime_params(scope, scope_key)",
    "CREATE INDEX IF NOT EXISTS idx_reset_tokens_token ON password_reset_tokens(token)",
]
