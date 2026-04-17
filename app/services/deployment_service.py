"""
Deployment service — runs a git-based deployment on a remote server.

Workflow:
  1. Insert a `deployments` row with status=running.
  2. Spawn a daemon thread inside app.app_context() that:
     - decrypts the server's private key (Fernet)
     - opens a pinned SSH channel via ssh_service.open_client
     - runs `git fetch && git reset --hard origin/<branch>` on the remote
     - streams stdout/stderr lines to a Socket.IO room `deploy_<id>`
     - appends each line to logs/deployments/<id>.log
     - updates the DB row with status/finished_at/commit_sha on exit
  3. Hard timeout after 600s.

Permission helper `can_user_deploy` lives here so routes can gate
per-project deploys (admin OR dev-instance owner on that project).
"""
from __future__ import annotations

import logging
import os
import re
import select
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from flask import Flask, current_app

from app.services import ssh_service

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/deployments.db"
_LOG_DIR = "logs/deployments"
_DEPLOY_TIMEOUT_SECONDS = 600  # 10 minutes
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


class DeploymentService:
    """Runs and tracks git-based deployments over SSH."""

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        log_dir: str = _LOG_DIR,
        server_service=None,
        socketio=None,
    ):
        self.db_path = db_path
        self.log_dir = log_dir
        self.server_service = server_service
        self.socketio = socketio
        os.makedirs(self.log_dir, exist_ok=True)
        self._init_db()

    # ─── schema ──────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Tables are also created by ServerService._init_db; running
        the same CREATE IF NOT EXISTS here keeps the service usable
        standalone (e.g. in tests)."""
        conn = sqlite3.connect(self.db_path)
        try:
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
                                   CHECK(status IN ('running','success','failed','timeout')),
                    triggered_by   INTEGER,
                    started_at     TEXT NOT NULL,
                    finished_at    TEXT,
                    log_file       TEXT
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
            conn.commit()
        finally:
            conn.close()

    # ─── helpers ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ─── project git config ─────────────────────────────────────────

    def get_project_git_config(self, project_name: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT git_remote_url, git_default_branch "
                "FROM project_deployment_config WHERE project_name = ?",
                (project_name,),
            ).fetchone()
        if not row:
            return {"git_remote_url": None, "git_default_branch": "main"}
        return dict(row)

    def set_project_git_config(
        self,
        project_name: str,
        *,
        git_remote_url: Optional[str],
        git_default_branch: Optional[str] = "main",
    ) -> dict:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_deployment_config
                    (project_name, git_remote_url, git_default_branch, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name) DO UPDATE SET
                    git_remote_url = excluded.git_remote_url,
                    git_default_branch = excluded.git_default_branch,
                    updated_at = excluded.updated_at
                """,
                (project_name, git_remote_url, git_default_branch or "main", self._now()),
            )
            conn.commit()
        return self.get_project_git_config(project_name)

    # ─── permissions ─────────────────────────────────────────────────

    def can_user_deploy(self, user, project_name: str) -> bool:
        """Admin can deploy anything; developers can deploy only projects
        where they own an active dev-instance."""
        if user is None:
            return False
        if getattr(user, "role", None) == "admin":
            return True
        try:
            svc = current_app.extensions.get("dev_instance_service")
        except RuntimeError:
            svc = None
        if svc is None:
            return False
        instances = []
        for method in ("list_instances_by_user", "list_for_user", "list_instances"):
            fn = getattr(svc, method, None)
            if callable(fn):
                try:
                    instances = fn(user.username) if method != "list_instances" else fn()
                except TypeError:
                    instances = fn()
                break
        username = user.username
        for inst in instances or []:
            parent = getattr(inst, "parent_project", None) or (inst.get("parent_project") if isinstance(inst, dict) else None)
            owner = getattr(inst, "owner_username", None) or (inst.get("owner_username") if isinstance(inst, dict) else None)
            if parent == project_name and owner == username:
                return True
        return False

    # ─── deployment history ──────────────────────────────────────────

    def list_deployments(
        self,
        *,
        project_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        q = (
            "SELECT d.*, s.label AS server_label, s.env AS server_env "
            "FROM deployments d LEFT JOIN servers s ON s.id = d.server_id "
        )
        args: Tuple = ()
        if project_name:
            q += "WHERE d.project_name = ? "
            args = (project_name,)
        q += "ORDER BY d.started_at DESC LIMIT ?"
        args = args + (int(limit),)

        with self._connect() as conn:
            rows = conn.execute(q, args).fetchall()

        return [dict(r) for r in rows]

    def get_deployment(self, deployment_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT d.*, s.label AS server_label, s.env AS server_env "
                "FROM deployments d LEFT JOIN servers s ON s.id = d.server_id "
                "WHERE d.id = ?",
                (deployment_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_log(self, deployment_id: int) -> Optional[str]:
        dep = self.get_deployment(deployment_id)
        if not dep or not dep.get("log_file"):
            return None
        path = dep["log_file"]
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    # ─── run ─────────────────────────────────────────────────────────

    def run(
        self,
        *,
        project_name: str,
        server_id: int,
        branch: str,
        triggered_by: Optional[int],
        app: Flask,
    ) -> int:
        """Insert the deployment row and fire off the worker thread."""
        if not _BRANCH_RE.match(branch or ""):
            raise ValueError("Invalid branch name.")

        if self.server_service is None:
            raise RuntimeError("DeploymentService is missing its ServerService dependency.")

        server = self.server_service.get_by_id(server_id)
        if not server:
            raise ValueError(f"Server id={server_id} does not exist.")
        if not server.host_fingerprint:
            raise RuntimeError(
                "Server has no pinned host fingerprint. "
                "Run Test connection and save the fingerprint first."
            )

        now = self._now()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO deployments
                    (project_name, server_id, branch, status,
                     triggered_by, started_at, log_file)
                VALUES (?, ?, ?, 'running', ?, ?, ?)
                """,
                (project_name, server_id, branch, triggered_by, now, ""),
            )
            conn.commit()
            deployment_id = cur.lastrowid

        log_path = os.path.join(self.log_dir, f"{deployment_id}.log")
        with self._connect() as conn:
            conn.execute(
                "UPDATE deployments SET log_file = ? WHERE id = ?",
                (log_path, deployment_id),
            )
            conn.commit()

        thread = threading.Thread(
            target=self._execute_wrapped,
            args=(app, deployment_id, server, project_name, branch, log_path),
            daemon=True,
            name=f"deploy-{deployment_id}",
        )
        thread.start()
        return deployment_id

    # ─── internals ───────────────────────────────────────────────────

    def _execute_wrapped(self, app, deployment_id, server, project_name, branch, log_path):
        """Thread target: establishes app context then delegates."""
        with app.app_context():
            try:
                self._execute(deployment_id, server, project_name, branch, log_path)
            except Exception as exc:  # noqa: BLE001
                log.exception("Deployment %s crashed", deployment_id)
                self._emit(deployment_id, f"[deployment crashed: {exc}]", stream="stderr")
                self._finalize(deployment_id, status="failed", commit_sha=None)

    def _execute(self, deployment_id, server, project_name, branch, log_path):
        start = time.monotonic()

        secret_key = current_app.config.get("SECRET_KEY") or ""
        try:
            pem = ssh_service.decrypt_private_key(secret_key, bytes(server.ssh_private_key_enc))
        except Exception as exc:  # noqa: BLE001
            self._emit(deployment_id, f"[cannot decrypt server key: {exc}]", stream="stderr")
            self._finalize(deployment_id, status="failed", commit_sha=None)
            return

        self._emit(
            deployment_id,
            f"$ connect {server.ssh_user}@{server.hostname}:{server.ssh_port}",
            stream="stdout",
        )

        try:
            client = ssh_service.open_client(
                pem=pem,
                hostname=server.hostname,
                ssh_port=server.ssh_port,
                ssh_user=server.ssh_user,
                expected_fingerprint=server.host_fingerprint,
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit(deployment_id, f"[SSH connect failed: {exc}]", stream="stderr")
            self._finalize(deployment_id, status="failed", commit_sha=None)
            return

        deploy_path = os.path.join(server.deploy_base_path, project_name)
        # Safe: branch was validated by regex; deploy_path is server-controlled, project_name is a slug.
        script = (
            "set -e\n"
            f"cd {_shell_quote(deploy_path)}\n"
            "git fetch --prune origin\n"
            f"git reset --hard origin/{_shell_quote(branch)}\n"
            "git rev-parse HEAD\n"
        )
        self._emit(deployment_id, f"$ cd {deploy_path}", stream="stdout")
        self._emit(deployment_id, f"$ git fetch --prune origin", stream="stdout")
        self._emit(deployment_id, f"$ git reset --hard origin/{branch}", stream="stdout")

        commit_sha: Optional[str] = None
        status = "failed"
        try:
            stdin, stdout, stderr = client.exec_command(script, timeout=_DEPLOY_TIMEOUT_SECONDS, get_pty=False)
            channel = stdout.channel
            stdin.close()

            captured_stdout_lines: List[str] = []

            def on_line(line: str, stream: str):
                captured_stdout_lines.append(line) if stream == "stdout" else None
                self._emit(deployment_id, line, stream=stream)

            self._stream_channel(channel, on_line, start, deployment_id)

            exit_code = channel.recv_exit_status()
            if exit_code == 0:
                status = "success"
                # `git rev-parse HEAD` was the last command; the last non-empty
                # stdout line is the commit sha.
                for line in reversed(captured_stdout_lines):
                    candidate = line.strip()
                    if re.fullmatch(r"[0-9a-f]{40}", candidate):
                        commit_sha = candidate
                        break
            else:
                self._emit(deployment_id, f"[remote exited with code {exit_code}]", stream="stderr")
                status = "failed"
        except (TimeoutError, socket_timeout_exc()):
            self._emit(deployment_id, "[deployment timed out]", stream="stderr")
            status = "timeout"
        except Exception as exc:  # noqa: BLE001
            self._emit(deployment_id, f"[exec error: {exc}]", stream="stderr")
            status = "failed"
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

        self._finalize(deployment_id, status=status, commit_sha=commit_sha)

    def _stream_channel(self, channel, on_line: Callable[[str, str], None], start_time: float, deployment_id: int):
        """Stream stdout/stderr lines until the channel closes or we hit the global timeout."""
        channel.settimeout(1.0)
        stdout_buf = ""
        stderr_buf = ""
        while True:
            if time.monotonic() - start_time > _DEPLOY_TIMEOUT_SECONDS:
                try:
                    channel.close()
                except Exception:  # noqa: BLE001
                    pass
                raise TimeoutError("Deployment exceeded the global time budget.")

            did_read = False

            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                if chunk:
                    stdout_buf += chunk
                    stdout_buf, emitted = _drain_lines(stdout_buf)
                    for line in emitted:
                        on_line(line, "stdout")
                    did_read = True

            if channel.recv_stderr_ready():
                chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                if chunk:
                    stderr_buf += chunk
                    stderr_buf, emitted = _drain_lines(stderr_buf)
                    for line in emitted:
                        on_line(line, "stderr")
                    did_read = True

            if channel.exit_status_ready() and not did_read and not channel.recv_ready() and not channel.recv_stderr_ready():
                break

            if not did_read:
                time.sleep(0.05)

        # Flush trailing lines without newline
        if stdout_buf.strip():
            on_line(stdout_buf.strip(), "stdout")
        if stderr_buf.strip():
            on_line(stderr_buf.strip(), "stderr")

    def _emit(self, deployment_id: int, line: str, *, stream: str) -> None:
        safe = ssh_service.redact_private_keys(line)
        # Append to log file
        try:
            dep = self.get_deployment(deployment_id)
            path = dep.get("log_file") if dep else None
            if path:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(f"[{stream}] {safe}\n")
        except OSError:
            pass

        # Emit to Socket.IO room
        if self.socketio is not None:
            try:
                self.socketio.emit(
                    "deployment_log",
                    {"id": deployment_id, "line": safe, "stream": stream},
                    room=f"deploy_{deployment_id}",
                )
            except Exception:  # noqa: BLE001
                pass

    def _finalize(self, deployment_id: int, *, status: str, commit_sha: Optional[str]) -> None:
        finished = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE deployments SET status = ?, finished_at = ?, commit_sha = ? WHERE id = ?",
                (status, finished, commit_sha, deployment_id),
            )
            conn.commit()
        if self.socketio is not None:
            try:
                self.socketio.emit(
                    "deployment_complete",
                    {"id": deployment_id, "status": status, "commit_sha": commit_sha, "finished_at": finished},
                    room=f"deploy_{deployment_id}",
                )
            except Exception:  # noqa: BLE001
                pass


# ─── module helpers ──────────────────────────────────────────────────


def _drain_lines(buffer: str) -> Tuple[str, List[str]]:
    """Split a buffer into complete lines plus a remainder."""
    if "\n" not in buffer:
        return buffer, []
    parts = buffer.split("\n")
    remainder = parts.pop()
    return remainder, [p for p in parts if p is not None]


def _shell_quote(value: str) -> str:
    """Single-quote a string for safe shell interpolation."""
    return "'" + value.replace("'", "'\\''") + "'"


def socket_timeout_exc():
    """Lazy import of socket.timeout for the except clause."""
    import socket
    return socket.timeout
