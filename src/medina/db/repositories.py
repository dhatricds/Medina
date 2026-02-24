"""CRUD functions for all database domains.

Grouped by domain: chat, corrections, learnings, cove, plans, params.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from medina.db.engine import get_conn

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════
#  Projects
# ══════════════════════════════════════════════════════════════════════

def upsert_project(
    project_id: str,
    source_path: str,
    source_key: str,
    project_name: str = "",
    status: str = "pending",
) -> None:
    conn = get_conn()
    conn.execute(
        """\
        INSERT INTO projects (id, source_path, source_key, project_name, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            source_path=excluded.source_path,
            source_key=excluded.source_key,
            project_name=excluded.project_name,
            status=excluded.status,
            updated_at=datetime('now')
        """,
        (project_id, source_path, source_key, project_name, status),
    )
    conn.commit()


def get_project(project_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════
#  Chat messages
# ══════════════════════════════════════════════════════════════════════

def add_chat_message(
    project_id: str,
    role: str,
    content: str,
    intent: str | None = None,
    context_snapshot: dict | None = None,
    metadata: dict | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """\
        INSERT INTO chat_messages (project_id, role, content, intent, context_snapshot, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            role,
            content,
            intent,
            json.dumps(context_snapshot) if context_snapshot else None,
            json.dumps(metadata) if metadata else None,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_chat_history(project_id: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """\
        SELECT id, role, content, intent, context_snapshot, metadata, created_at
        FROM chat_messages WHERE project_id=?
        ORDER BY id ASC LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("context_snapshot"):
            d["context_snapshot"] = json.loads(d["context_snapshot"])
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return result


def get_recent_chat(project_id: str, n: int = 10) -> list[dict]:
    """Get the most recent N chat messages for context building."""
    conn = get_conn()
    rows = conn.execute(
        """\
        SELECT role, content, intent FROM chat_messages
        WHERE project_id=?
        ORDER BY id DESC LIMIT ?
        """,
        (project_id, n),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ══════════════════════════════════════════════════════════════════════
#  Corrections (per-project feedback)
# ══════════════════════════════════════════════════════════════════════

def add_correction(
    project_id: str,
    source_key: str,
    action: str,
    fixture_code: str,
    reason: str = "other",
    reason_detail: str = "",
    fixture_data: dict | None = None,
    spec_patches: dict | None = None,
    origin: str = "user",
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """\
        INSERT INTO corrections
            (project_id, source_key, action, fixture_code, reason, reason_detail,
             fixture_data, spec_patches, origin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            source_key,
            action,
            fixture_code,
            reason,
            reason_detail,
            json.dumps(fixture_data or {}),
            json.dumps(spec_patches or {}),
            origin,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_corrections(project_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM corrections WHERE project_id=? ORDER BY id",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["fixture_data"] = json.loads(d.get("fixture_data") or "{}")
        d["spec_patches"] = json.loads(d.get("spec_patches") or "{}")
        result.append(d)
    return result


def delete_correction(correction_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM corrections WHERE id=?", (correction_id,))
    conn.commit()
    return cur.rowcount > 0


def clear_corrections(project_id: str) -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM corrections WHERE project_id=?", (project_id,))
    conn.commit()
    return cur.rowcount


# ══════════════════════════════════════════════════════════════════════
#  Learnings (per source file)
# ══════════════════════════════════════════════════════════════════════

def upsert_learning(
    source_key: str,
    source_name: str = "",
    source_path: str = "",
    corrections_json: str = "[]",
    times_applied: int = 0,
) -> None:
    conn = get_conn()
    conn.execute(
        """\
        INSERT INTO learnings (source_key, source_name, source_path, corrections_json, times_applied)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_name=excluded.source_name,
            source_path=excluded.source_path,
            corrections_json=excluded.corrections_json,
            times_applied=excluded.times_applied,
            updated_at=datetime('now')
        """,
        (source_key, source_name, source_path, corrections_json, times_applied),
    )
    conn.commit()


def get_learning(source_key: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM learnings WHERE source_key=?", (source_key,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["corrections"] = json.loads(d.pop("corrections_json", "[]"))
    return d


def get_all_learnings() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM learnings ORDER BY source_key").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["corrections"] = json.loads(d.pop("corrections_json", "[]"))
        result.append(d)
    return result


def increment_learning_applied(source_key: str) -> None:
    conn = get_conn()
    conn.execute(
        """\
        UPDATE learnings SET times_applied = times_applied + 1,
        updated_at = datetime('now') WHERE source_key=?
        """,
        (source_key,),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════════════
#  Global patterns
# ══════════════════════════════════════════════════════════════════════

def upsert_global_pattern(
    pattern_type: str,
    fixture_code: str,
    description: str = "",
    source_count: int = 0,
    examples: list | None = None,
    global_hint: dict | None = None,
    source_keys: list | None = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """\
        INSERT INTO global_patterns
            (pattern_type, fixture_code, description, source_count,
             examples_json, global_hint_json, source_keys_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pattern_type, fixture_code) DO UPDATE SET
            description=excluded.description,
            source_count=excluded.source_count,
            examples_json=excluded.examples_json,
            global_hint_json=excluded.global_hint_json,
            source_keys_json=excluded.source_keys_json,
            updated_at=datetime('now')
        """,
        (
            pattern_type,
            fixture_code,
            description,
            source_count,
            json.dumps(examples or []),
            json.dumps(global_hint or {}),
            json.dumps(source_keys or []),
        ),
    )
    conn.commit()


def get_all_global_patterns() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM global_patterns ORDER BY id").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["examples"] = json.loads(d.pop("examples_json", "[]"))
        d["global_hint"] = json.loads(d.pop("global_hint_json", "{}"))
        d["source_keys"] = json.loads(d.pop("source_keys_json", "[]"))
        result.append(d)
    return result


# ══════════════════════════════════════════════════════════════════════
#  COVE results
# ══════════════════════════════════════════════════════════════════════

def save_cove_result(
    project_id: str,
    agent_id: int,
    agent_name: str = "",
    passed: bool = True,
    confidence: float = 1.0,
    issues: list | None = None,
    reasoning: str = "",
    retry_count: int = 0,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """\
        INSERT INTO cove_results
            (project_id, agent_id, agent_name, passed, confidence,
             issues_json, reasoning, retry_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            agent_id,
            agent_name,
            int(passed),
            confidence,
            json.dumps(issues or []),
            reasoning,
            retry_count,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_cove_results(project_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM cove_results WHERE project_id=? ORDER BY id",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["passed"] = bool(d["passed"])
        d["issues"] = json.loads(d.pop("issues_json", "[]"))
        result.append(d)
    return result


# ══════════════════════════════════════════════════════════════════════
#  Agent plans
# ══════════════════════════════════════════════════════════════════════

def save_agent_plan(
    project_id: str,
    agent_id: int,
    agent_name: str = "",
    plan_text: str = "",
    strategy: dict | None = None,
    expected_challenges: list | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """\
        INSERT INTO agent_plans
            (project_id, agent_id, agent_name, plan_text, strategy_json, expected_challenges)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            agent_id,
            agent_name,
            plan_text,
            json.dumps(strategy or {}),
            json.dumps(expected_challenges or []),
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_agent_plans(project_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_plans WHERE project_id=? ORDER BY id",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["strategy"] = json.loads(d.pop("strategy_json", "{}"))
        d["expected_challenges"] = json.loads(d.get("expected_challenges") or "[]")
        result.append(d)
    return result


# ══════════════════════════════════════════════════════════════════════
#  Runtime parameters
# ══════════════════════════════════════════════════════════════════════

def set_param(
    param_key: str,
    param_value: Any,
    scope: str = "global",
    scope_key: str = "",
) -> None:
    conn = get_conn()
    conn.execute(
        """\
        INSERT INTO runtime_params (scope, scope_key, param_key, param_value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(scope, scope_key, param_key) DO UPDATE SET
            param_value=excluded.param_value,
            updated_at=datetime('now')
        """,
        (scope, scope_key, param_key, json.dumps(param_value)),
    )
    conn.commit()


def get_params(scope: str = "global", scope_key: str = "") -> dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT param_key, param_value FROM runtime_params WHERE scope=? AND scope_key=?",
        (scope, scope_key),
    ).fetchall()
    return {row["param_key"]: json.loads(row["param_value"]) for row in rows}


def delete_param(
    param_key: str,
    scope: str = "global",
    scope_key: str = "",
) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM runtime_params WHERE scope=? AND scope_key=? AND param_key=?",
        (scope, scope_key, param_key),
    )
    conn.commit()
    return cur.rowcount > 0
