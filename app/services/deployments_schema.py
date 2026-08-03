"""
Single source of truth for the `data/deployments.db` schema.

Rationale: ServerService and DeploymentService both need access to the
same tables; having each class CREATE IF NOT EXISTS in its own shape led
to divergent definitions (FK vs no-FK, and similar) depending on which
service initialised first. Centralising avoids silent drift.

Migrations are driven by ``PRAGMA user_version``: bump ``SCHEMA_VERSION``
and add an idempotent block to ``_migrate``.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


SCHEMA_VERSION = 4


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with FK enforcement on and row factory set.

    SQLite disables foreign keys per-connection by default, so without
    this pragma every ON DELETE CASCADE in the schema is a no-op.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init(db_path: str) -> None:
    """Create any missing tables + run pending migrations."""
    conn = connect(db_path)
    try:
        _create_tables(conn)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS servers (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            label                 TEXT NOT NULL UNIQUE,
            env                   TEXT NOT NULL CHECK(env IN ('staging','production')),
            hostname              TEXT NOT NULL,
            ssh_port              INTEGER NOT NULL DEFAULT 22,
            ssh_user              TEXT NOT NULL,
            ssh_private_key_enc   BLOB NOT NULL,
            host_fingerprint      TEXT,
            deploy_base_path      TEXT NOT NULL,
            created_by            INTEGER,
            created_at            TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deployments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name   TEXT NOT NULL,
            server_id      INTEGER NOT NULL,
            branch         TEXT NOT NULL,
            commit_sha     TEXT,
            status         TEXT NOT NULL
                           CHECK(status IN ('running','success','failed','timeout','cancelled')),
            triggered_by   INTEGER,
            started_at     TEXT NOT NULL,
            finished_at    TEXT,
            log_file       TEXT,
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_deploy_project "
        "ON deployments(project_name, started_at DESC)"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS project_deployment_config (
            project_name         TEXT PRIMARY KEY,
            git_remote_url       TEXT,
            git_default_branch   TEXT DEFAULT 'main',
            updated_at           TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS project_server_deploy_paths (
            project_name   TEXT NOT NULL,
            server_id      INTEGER NOT NULL,
            deploy_path    TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            PRIMARY KEY (project_name, server_id),
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
        """
    )
    # A named, reusable deployment configuration ("target"): freeze a
    # (project, server, branch) triple once and re-deploy it in one
    # click. The UNIQUE constraint keeps the list free of duplicates;
    # the FK cascades a target away when its server is deleted.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_targets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            label          TEXT NOT NULL,
            project_name   TEXT NOT NULL,
            server_id      INTEGER NOT NULL,
            branch         TEXT NOT NULL DEFAULT 'main',
            created_by     INTEGER,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            UNIQUE(project_name, server_id, branch),
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_target_project "
        "ON deployment_targets(project_name)"
    )
    # A registered deployment "project" — a folder that groups one or
    # more connections (deployment_targets). A project can exist with
    # zero connections (freshly created). The main view lists these; a
    # project maps 1:1 to a real launcher project by name.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_projects (
            project_name  TEXT PRIMARY KEY,
            created_by    INTEGER,
            created_at    TEXT NOT NULL
        )
        """
    )


def _migrate(conn: sqlite3.Connection) -> None:
    """Run any pending PRAGMA-user_version bumps."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return

    # --- v1 -----------------------------------------------------------
    # Baseline schema (everything in _create_tables). Databases created
    # before the FK-on-deploy-paths change need the table rebuilt so the
    # FK takes effect. We only rebuild if the column list matches (no
    # user-authored alterations) to stay idempotent and safe.
    if current < 1 and _needs_deploy_paths_fk_rebuild(conn):
        _rebuild_project_server_deploy_paths(conn)

    # --- v2 -----------------------------------------------------------
    # The status CHECK gains 'cancelled' (deployment cancel feature).
    # SQLite can't ALTER a CHECK constraint; rebuild the table.
    if current < 2 and _needs_cancelled_status_rebuild(conn):
        _rebuild_deployments_with_cancelled(conn)

    # --- v3 -----------------------------------------------------------
    # Adds the `deployment_targets` table (reusable one-click deploy
    # configs). Nothing to backfill: `_create_tables` already ran its
    # CREATE IF NOT EXISTS above, so the bump just records the version.

    # --- v4 -----------------------------------------------------------
    # Adds the `deployment_projects` folder registry. Back-populate it
    # from any existing targets so pre-v4 connections stay visible under
    # their project after the UI switches to the folder view.
    if current < 4:
        conn.execute(
            "INSERT OR IGNORE INTO deployment_projects (project_name, created_by, created_at) "
            "SELECT DISTINCT project_name, NULL, "
            "       COALESCE(MIN(created_at), datetime('now')) "
            "FROM deployment_targets GROUP BY project_name"
        )

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _needs_deploy_paths_fk_rebuild(conn: sqlite3.Connection) -> bool:
    """True if the existing table is missing the FK we want."""
    fks = conn.execute(
        "PRAGMA foreign_key_list('project_server_deploy_paths')"
    ).fetchall()
    for fk in fks:
        if (
            fk["table"] == "servers"
            and fk["from"] == "server_id"
            and fk["on_delete"].upper() == "CASCADE"
        ):
            return False
    return True


def _needs_cancelled_status_rebuild(conn: sqlite3.Connection) -> bool:
    """True if the deployments CHECK doesn't yet allow 'cancelled'."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='deployments'"
    ).fetchone()
    if not row or not row["sql"]:
        return False
    return "'cancelled'" not in row["sql"]


def _rebuild_deployments_with_cancelled(conn: sqlite3.Connection) -> None:
    """Rebuild the deployments table so the status CHECK accepts
    'cancelled'. Same INSERT/DROP/RENAME dance as the deploy-paths
    rebuild; the index is recreated afterwards."""
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _new_deployments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name   TEXT NOT NULL,
                server_id      INTEGER NOT NULL,
                branch         TEXT NOT NULL,
                commit_sha     TEXT,
                status         TEXT NOT NULL
                               CHECK(status IN ('running','success','failed','timeout','cancelled')),
                triggered_by   INTEGER,
                started_at     TEXT NOT NULL,
                finished_at    TEXT,
                log_file       TEXT,
                FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "INSERT INTO _new_deployments "
            "(id, project_name, server_id, branch, commit_sha, status, "
            " triggered_by, started_at, finished_at, log_file) "
            "SELECT id, project_name, server_id, branch, commit_sha, status, "
            "       triggered_by, started_at, finished_at, log_file "
            "FROM deployments"
        )
        conn.execute("DROP TABLE deployments")
        conn.execute("ALTER TABLE _new_deployments RENAME TO deployments")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deploy_project "
            "ON deployments(project_name, started_at DESC)"
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _rebuild_project_server_deploy_paths(conn: sqlite3.Connection) -> None:
    """SQLite can't ALTER an FK in; rebuild the table via the classic
    ``INSERT INTO new ... DROP old ... RENAME new`` dance."""
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _new_psdp (
                project_name   TEXT NOT NULL,
                server_id      INTEGER NOT NULL,
                deploy_path    TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                PRIMARY KEY (project_name, server_id),
                FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "INSERT INTO _new_psdp (project_name, server_id, deploy_path, updated_at) "
            "SELECT project_name, server_id, deploy_path, updated_at "
            "FROM project_server_deploy_paths"
        )
        conn.execute("DROP TABLE project_server_deploy_paths")
        conn.execute("ALTER TABLE _new_psdp RENAME TO project_server_deploy_paths")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
