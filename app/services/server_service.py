"""Server inventory service — CRUD over the ``servers`` SQLite table.

Follows the same shape as ``user_service.py`` (raw sqlite3, no ORM).
Lives in ``data/deployments.db`` so the deployments feature stays
self-contained and doesn't drift into ``projects.db`` migrations.

Schema is defined in ``app.services.deployments_schema``; both
``ServerService`` and ``DeploymentService`` share that single source of
truth so their FK definitions can never drift apart.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from app.models.server import Server
from app.services import deployments_schema

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/deployments.db"
_VALID_ENVS = {"staging", "production"}


class ServerService:
    """Small wrapper around the ``servers`` table."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        deployments_schema.init(self.db_path)

    # ─── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _row_to_server(row: sqlite3.Row) -> Server:
        return Server(
            id=row["id"],
            label=row["label"],
            env=row["env"],
            hostname=row["hostname"],
            ssh_port=row["ssh_port"],
            ssh_user=row["ssh_user"],
            ssh_private_key_enc=row["ssh_private_key_enc"],
            host_fingerprint=row["host_fingerprint"],
            deploy_base_path=row["deploy_base_path"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    def _connect(self) -> sqlite3.Connection:
        """Delegates to the shared schema connector so FK enforcement
        and row_factory are set identically everywhere."""
        return deployments_schema.connect(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ─── public API ──────────────────────────────────────────────────

    def create(
        self,
        *,
        label: str,
        env: str,
        hostname: str,
        ssh_user: str,
        ssh_private_key_enc: bytes,
        deploy_base_path: str,
        ssh_port: int = 22,
        host_fingerprint: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> Server:
        if env not in _VALID_ENVS:
            raise ValueError(f"Invalid env {env!r}. Expected one of {sorted(_VALID_ENVS)}.")
        if not label or not hostname or not ssh_user or not deploy_base_path:
            raise ValueError("label, hostname, ssh_user and deploy_base_path are required.")
        if not ssh_private_key_enc:
            raise ValueError("ssh_private_key_enc is required (encrypted with Fernet).")

        created_at = self._now()
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO servers
                        (label, env, hostname, ssh_port, ssh_user,
                         ssh_private_key_enc, host_fingerprint,
                         deploy_base_path, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        label, env, hostname, ssh_port, ssh_user,
                        ssh_private_key_enc, host_fingerprint,
                        deploy_base_path, created_by, created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"A server named {label!r} already exists.") from exc
            conn.commit()
            new_id = cur.lastrowid

        return self.get_by_id(new_id)  # type: ignore[return-value]

    def update(
        self,
        server_id: int,
        *,
        label: Optional[str] = None,
        env: Optional[str] = None,
        hostname: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_user: Optional[str] = None,
        deploy_base_path: Optional[str] = None,
        ssh_private_key_enc: Optional[bytes] = None,
        host_fingerprint: Optional[str] = None,
    ) -> Optional[Server]:
        fields: list[tuple[str, object]] = []
        if label is not None:
            fields.append(("label", label))
        if env is not None:
            if env not in _VALID_ENVS:
                raise ValueError(f"Invalid env {env!r}.")
            fields.append(("env", env))
        if hostname is not None:
            fields.append(("hostname", hostname))
        if ssh_port is not None:
            fields.append(("ssh_port", int(ssh_port)))
        if ssh_user is not None:
            fields.append(("ssh_user", ssh_user))
        if deploy_base_path is not None:
            fields.append(("deploy_base_path", deploy_base_path))
        if ssh_private_key_enc is not None:
            fields.append(("ssh_private_key_enc", ssh_private_key_enc))
        if host_fingerprint is not None:
            fields.append(("host_fingerprint", host_fingerprint))
        if not fields:
            return self.get_by_id(server_id)

        set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
        values: list[object] = [val for _, val in fields]
        values.append(server_id)

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE servers SET {set_clause} WHERE id = ?",
                values,
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_by_id(server_id)

    def delete(self, server_id: int) -> bool:
        """Delete a server. FK cascade removes deployment rows and
        per-(project, server) deploy-path overrides automatically."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_by_id(self, server_id: int) -> Optional[Server]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
            row = cur.fetchone()
        return self._row_to_server(row) if row else None

    def get_by_label(self, label: str) -> Optional[Server]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM servers WHERE label = ?", (label,))
            row = cur.fetchone()
        return self._row_to_server(row) if row else None

    def list_servers(self) -> List[Server]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM servers ORDER BY env DESC, label ASC")
            rows = cur.fetchall()
        return [self._row_to_server(row) for row in rows]
