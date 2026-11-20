"""Knowledge base identity schema rebuild and membership cleanup."""

from __future__ import annotations

from octop.infra.db.migrate.introspect import (
    _ensure_column,
    _integer_pk_sql,
    _relation_columns,
    _relation_exists,
)
from octop.infra.db.pool import DatabasePool


def _knowledge_identity_ready(db: DatabasePool) -> bool:
    if not _relation_exists(db, "knowledge_bases"):
        return False
    cols = _relation_columns(db, "knowledge_bases")
    doc_cols = (
        _relation_columns(db, "knowledge_documents")
        if _relation_exists(db, "knowledge_documents")
        else set()
    )
    return "knowledge_base_id" in cols and "document_id" in doc_cols and "path" in doc_cols


def _create_knowledge_identity_tables(db: DatabasePool) -> None:
    pk = _integer_pk_sql(db)
    with db.connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
              id {pk},
              knowledge_base_id TEXT NOT NULL UNIQUE,
              owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              default_open INTEGER NOT NULL DEFAULT 0,
              shared INTEGER NOT NULL DEFAULT 0,
              icon_name TEXT NOT NULL DEFAULT '',
              embedding_model TEXT NOT NULL DEFAULT '',
              embedding_dim INTEGER NOT NULL DEFAULT 0,
              doc_count INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(owner_user_id, name)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_owner ON knowledge_bases(owner_user_id)"
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS knowledge_documents (
              id {pk},
              document_id TEXT NOT NULL UNIQUE,
              kb_id TEXT NOT NULL REFERENCES knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
              path TEXT NOT NULL,
              filename TEXT NOT NULL,
              is_dir INTEGER NOT NULL DEFAULT 0,
              content_type TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              content_hash TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              error_message TEXT NOT NULL DEFAULT '',
              chunk_count INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(kb_id, path)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb ON knowledge_documents(kb_id)"
        )


def _rebuild_knowledge_identity_schema(db: DatabasePool) -> None:
    """Give knowledge tables integer PKs + public string ids; add document folders."""
    if _knowledge_identity_ready(db):
        return
    if not _relation_exists(db, "knowledge_bases"):
        _create_knowledge_identity_tables(db)
        return
    pk = _integer_pk_sql(db)
    with db.transaction() as conn:
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = OFF")
        if _relation_exists(db, "knowledge_base_members", conn):
            conn.execute("DROP TABLE knowledge_base_members")
        conn.execute("ALTER TABLE knowledge_bases RENAME TO knowledge_bases_legacy")
        if _relation_exists(db, "knowledge_documents", conn):
            conn.execute("ALTER TABLE knowledge_documents RENAME TO knowledge_documents_legacy")
        else:
            conn.execute(
                """
                CREATE TABLE knowledge_documents_legacy (
                  id TEXT PRIMARY KEY,
                  kb_id TEXT NOT NULL,
                  filename TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  byte_size INTEGER NOT NULL,
                  content_hash TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'pending',
                  error_message TEXT NOT NULL DEFAULT '',
                  chunk_count INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
        conn.execute(
            f"""
            CREATE TABLE knowledge_bases (
              id {pk},
              knowledge_base_id TEXT NOT NULL UNIQUE,
              owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              default_open INTEGER NOT NULL DEFAULT 0,
              shared INTEGER NOT NULL DEFAULT 0,
              icon_name TEXT NOT NULL DEFAULT '',
              embedding_model TEXT NOT NULL DEFAULT '',
              embedding_dim INTEGER NOT NULL DEFAULT 0,
              doc_count INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(owner_user_id, name)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_bases(
              knowledge_base_id, owner_user_id, name, description, default_open,
              shared, icon_name, embedding_model, embedding_dim, doc_count,
              created_at, updated_at
            )
            SELECT id, owner_user_id, name, description, default_open,
              COALESCE(shared, 0), COALESCE(icon_name, ''), embedding_model,
              embedding_dim, doc_count, created_at, updated_at
            FROM knowledge_bases_legacy
            """
        )
        conn.execute(
            f"""
            CREATE TABLE knowledge_documents (
              id {pk},
              document_id TEXT NOT NULL UNIQUE,
              kb_id TEXT NOT NULL REFERENCES knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
              path TEXT NOT NULL,
              filename TEXT NOT NULL,
              is_dir INTEGER NOT NULL DEFAULT 0,
              content_type TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              content_hash TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              error_message TEXT NOT NULL DEFAULT '',
              chunk_count INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(kb_id, path)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_documents(
              document_id, kb_id, path, filename, is_dir, content_type, byte_size,
              content_hash, status, error_message, chunk_count, created_at, updated_at
            )
            SELECT id, kb_id, filename, filename, 0, content_type, byte_size,
              content_hash, status, error_message, chunk_count, created_at, updated_at
            FROM knowledge_documents_legacy
            """
        )
        conn.execute("DROP TABLE knowledge_documents_legacy")
        conn.execute("DROP TABLE knowledge_bases_legacy")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_owner ON knowledge_bases(owner_user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb ON knowledge_documents(kb_id)"
        )
        if db.dialect == "sqlite":
            conn.execute("PRAGMA foreign_keys = ON")


def _drop_knowledge_base_members(db: DatabasePool) -> None:
    if not _relation_exists(db, "knowledge_base_members"):
        return
    with db.connect() as conn:
        conn.execute("DROP TABLE knowledge_base_members")


def _ensure_knowledge_bases_schema(db: DatabasePool) -> None:
    """Create or rebuild knowledge tables to the integer-PK identity schema."""
    _rebuild_knowledge_identity_schema(db)
    _drop_knowledge_base_members(db)
    # Schema v10: per-knowledge-base configurable document limit.
    _ensure_column(db, "knowledge_bases", "max_documents", "INTEGER NOT NULL DEFAULT 100")
