"""Idempotent single-column additions across feature tables."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool

_BAO_TASK_FOLLOWUP_COLUMNS = (
    ("followup_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_followup_at", "INTEGER"),
    ("eval_status", "TEXT"),
    ("eval_at", "INTEGER"),
)


def _ensure_usage_cache_schema(db: DatabasePool) -> None:
    """Backfill cache-aware usage columns for upgraded and repaired databases."""
    if not _table_exists(db, "usage_log"):
        return
    token_type = "BIGINT" if db.dialect == "postgresql" else "INTEGER"
    for column in (
        "uncached_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    ):
        _ensure_column(
            db,
            "usage_log",
            column,
            f"{token_type} NOT NULL DEFAULT 0",
        )
    _ensure_column(db, "usage_log", "model_calls", "INTEGER NOT NULL DEFAULT 1")
    with db.connect() as conn:
        conn.execute(
            "UPDATE usage_log SET uncached_input_tokens = input_tokens "
            "WHERE uncached_input_tokens = 0 AND input_tokens > 0 "
            "AND cache_read_tokens = 0 AND cache_write_tokens = 0"
        )


def _ensure_agent_teams_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "agents"):
        return
    _ensure_column(db, "agents", "kind", "TEXT NOT NULL DEFAULT 'expert'")


def _ensure_thread_conversation_mode_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "threads"):
        return
    _ensure_column(db, "threads", "conversation_mode", "TEXT")
    _ensure_column(db, "threads", "pending_plan_path", "TEXT")
    _ensure_column(db, "threads", "hitl_policy", "TEXT")


def _ensure_skill_copy_policy_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "skill_packages"):
        return
    _ensure_column(db, "skill_packages", "copy_policy", "TEXT NOT NULL DEFAULT 'snapshot'")


def _ensure_skill_package_download_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "skill_packages"):
        return
    _ensure_column(db, "skill_packages", "allow_download", "INTEGER NOT NULL DEFAULT 1")


def _ensure_skill_package_shared_schema(db: DatabasePool) -> None:
    if not _table_exists(db, "skill_packages"):
        return
    _ensure_column(db, "skill_packages", "shared", "INTEGER NOT NULL DEFAULT 0")


def _ensure_user_group_profile_schema(db: DatabasePool) -> None:
    """Enable flag and preset avatar on user groups. Idempotent."""
    if not _table_exists(db, "user_group"):
        return
    _ensure_column(db, "user_group", "enabled", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "user_group", "avatar_icon", "TEXT")


def _ensure_knowledge_base_icon_url_schema(db: DatabasePool) -> None:
    """Optional portrait URL on knowledge bases. Idempotent."""
    if not _table_exists(db, "knowledge_bases"):
        return
    _ensure_column(db, "knowledge_bases", "icon_url", "TEXT NOT NULL DEFAULT ''")


def _ensure_bridge_icon_url_schema(db: DatabasePool) -> None:
    """Optional portrait URL on bridge connections. Idempotent."""
    if not _table_exists(db, "bridge_connections"):
        return
    _ensure_column(db, "bridge_connections", "icon_url", "TEXT NOT NULL DEFAULT ''")


def _ensure_bridge_shared_schema(db: DatabasePool) -> None:
    """Owner can share a bridge link with everyone or selected groups. Idempotent."""
    if not _table_exists(db, "bridge_connections"):
        return
    _ensure_column(db, "bridge_connections", "shared", "INTEGER NOT NULL DEFAULT 0")


def _ensure_bao_task_followup_columns(db: DatabasePool) -> None:
    """v28 follow-up/eval columns; SQLite cannot express ADD COLUMN IF NOT EXISTS."""
    if not _table_exists(db, "bao_tasks"):
        return
    for column, definition in _BAO_TASK_FOLLOWUP_COLUMNS:
        _ensure_column(db, "bao_tasks", column, definition)
