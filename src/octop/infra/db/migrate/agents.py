"""Agent profile / welcome column repairs and the profile backfill."""

from __future__ import annotations

import json

from octop.infra.db.migrate.introspect import (
    _drop_column,
    _ensure_column,
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool

_AGENT_PROFILE_COLUMNS = (
    "color",
    "icon_name",
    "icon_url",
    "skill_package_ids",
    "published_expert_id",
    "welcome_message",
    "knowledge_base_ids",
    "mcp_servers",
)


def _ensure_agent_profile_columns(db: DatabasePool) -> None:
    if not _table_exists(db, "agents"):
        return
    for column in _AGENT_PROFILE_COLUMNS:
        _ensure_column(db, "agents", column, "TEXT")
    _collapse_legacy_agent_welcome_columns(db)


def _collapse_legacy_agent_welcome_columns(db: DatabasePool) -> None:
    """Fold welcome_message_zh/en into a single instance-owned welcome_message."""
    if not _table_exists(db, "agents"):
        return
    if db.dialect == "postgresql":
        with db.connect() as conn:
            conn.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS welcome_message TEXT")
    else:
        _ensure_column(db, "agents", "welcome_message", "TEXT")
    cols = _table_columns(db, "agents")
    has_zh = "welcome_message_zh" in cols
    has_en = "welcome_message_en" in cols
    if not has_zh and not has_en:
        return
    select_cols = ["agent_id", "welcome_message"]
    if has_zh:
        select_cols.append("welcome_message_zh")
    if has_en:
        select_cols.append("welcome_message_en")
    with db.transaction() as conn:
        rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM agents").fetchall()
        for row in rows:
            current = str(row["welcome_message"] or "").strip()
            if current:
                continue
            zh = str(row["welcome_message_zh"] or "").strip() if has_zh else ""
            en = str(row["welcome_message_en"] or "").strip() if has_en else ""
            picked = zh or en
            if not picked:
                continue
            conn.execute(
                "UPDATE agents SET welcome_message = ? WHERE agent_id = ?",
                (picked, row["agent_id"]),
            )
    _drop_column(db, "agents", "welcome_message_zh")
    _drop_column(db, "agents", "welcome_message_en")


def _backfill_agent_profile_from_config(db: DatabasePool) -> None:
    """Copy display metadata out of ``config_json`` into first-class columns."""
    if not _table_exists(db, "agents"):
        return
    cols = _table_columns(db, "agents")
    if "icon_name" not in cols:
        return
    from octop.infra.agents.settings.profile import (  # noqa: PLC0415
        PROFILE_CONFIG_KEYS,
        extract_profile_from_config,
        parse_config_json,
        strip_profile_config,
    )

    profile_columns = (
        "color",
        "icon_name",
        "icon_url",
        "skill_package_ids",
        "published_expert_id",
        "welcome_message",
        "knowledge_base_ids",
        "mcp_servers",
    )
    present = [column for column in profile_columns if column in cols]
    select_cols = ["agent_id", "template_name", *present, "config_json"]

    with db.transaction() as conn:
        rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM agents").fetchall()
        for row in rows:
            cfg = parse_config_json(row["config_json"])
            if not cfg:
                continue
            profile = extract_profile_from_config(cfg)
            needs_strip = any(key in cfg for key in PROFILE_CONFIG_KEYS)
            updates: dict[str, object] = {}
            for column in present:
                if column not in profile:
                    continue
                current = row[column]
                if current is None or not str(current).strip():
                    updates[column] = profile[column]
            template = row["template_name"]
            if (template is None or not str(template).strip()) and profile.get("template_name"):
                updates["template_name"] = profile["template_name"]
            if needs_strip:
                updates["config_json"] = json.dumps(
                    strip_profile_config(cfg),
                    ensure_ascii=False,
                )
            if not updates:
                continue
            assignments = ", ".join(f"{column} = ?" for column in updates)
            params: list[object] = [*updates.values(), row["agent_id"]]
            conn.execute(
                f"UPDATE agents SET {assignments} WHERE agent_id = ?",
                params,
            )
