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
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import paramiko
from flask import Flask, current_app

from app.services import deployments_schema, ssh_service

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/deployments.db"
_LOG_DIR = "logs/deployments"
_DEPLOY_TIMEOUT_SECONDS = 600  # 10 minutes
# Branch names: git refs minus the dangerous bits. `..` is explicitly
# banned even though the regex wouldn't match a pure `..` alone, since
# we interpolate `origin/<branch>` into a shell pipeline.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
# Keep at most this many log files on disk. Older ones are pruned on
# each _finalize call so an unattended worker can't fill the volume.
_MAX_LOG_FILES = 500


class DeploymentService:
    """Runs and tracks git-based deployments over SSH."""

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        log_dir: str = _LOG_DIR,
        server_service=None,
        socketio=None,
    ):
        self.db_path = os.path.abspath(db_path)
        self.log_dir = os.path.abspath(log_dir)
        self.server_service = server_service
        self.socketio = socketio
        os.makedirs(self.log_dir, exist_ok=True)
        deployments_schema.init(self.db_path)
        self._reap_stale_running_rows()

    # ─── helpers ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        return deployments_schema.connect(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _reap_stale_running_rows(self) -> None:
        """Fail any row that was left `running` by a previous process
        crash. Without this, UI spinners would hang forever after an
        SIGKILL/OOM because the worker thread can't update the DB
        during an abrupt interpreter shutdown."""
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE deployments "
                    "SET status = 'failed', finished_at = ? "
                    "WHERE status = 'running'",
                    (now,),
                )
                conn.commit()
        except sqlite3.Error as exc:
            log.warning("Could not reap stale deployments: %s", exc)

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

    # ─── per-(project, server) deploy path overrides ────────────────

    def get_deploy_path(self, project_name: str, server_id: int) -> Optional[str]:
        """Return the user-defined deploy path for (project, server), or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT deploy_path FROM project_server_deploy_paths "
                "WHERE project_name = ? AND server_id = ?",
                (project_name, int(server_id)),
            ).fetchone()
        return row["deploy_path"] if row else None

    def set_deploy_path(
        self, project_name: str, server_id: int, deploy_path: Optional[str]
    ) -> Optional[str]:
        """Upsert a custom deploy path. Passing None/'' clears the override."""
        with self._connect() as conn:
            if not deploy_path:
                conn.execute(
                    "DELETE FROM project_server_deploy_paths "
                    "WHERE project_name = ? AND server_id = ?",
                    (project_name, int(server_id)),
                )
                conn.commit()
                return None
            conn.execute(
                """
                INSERT INTO project_server_deploy_paths
                    (project_name, server_id, deploy_path, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name, server_id) DO UPDATE SET
                    deploy_path = excluded.deploy_path,
                    updated_at  = excluded.updated_at
                """,
                (project_name, int(server_id), deploy_path, self._now()),
            )
            conn.commit()
        return deploy_path

    def list_deploy_paths_for_project(self, project_name: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT server_id, deploy_path, updated_at "
                "FROM project_server_deploy_paths WHERE project_name = ?",
                (project_name,),
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_deploy_path(self, project_name: str, server) -> str:
        """Effective deploy path for this (project, server) couple.
        Custom override wins; otherwise falls back to
        ``<server.deploy_base_path>/<project_name>``.
        """
        custom = self.get_deploy_path(project_name, server.id)
        if custom:
            return custom
        return os.path.join(server.deploy_base_path, project_name)

    # ─── permissions ─────────────────────────────────────────────────

    def can_user_deploy(self, user, project_name: str) -> bool:
        """Admin can deploy anything; developers can deploy only projects
        where they own an active dev-instance.

        The dev-instance service is expected to expose
        ``list_instances_by_user(username) -> Iterable`` (or dicts with
        ``parent_project``/``owner_username`` keys). We fail loud if the
        method is missing rather than silently locking every developer
        out — which was the pre-refactor behaviour and masked a broken
        DI wiring in staging.
        """
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

        lister = getattr(svc, "list_instances_by_user", None)
        if not callable(lister):
            # Legacy shapes kept for backwards compat, explicitly named.
            lister = getattr(svc, "list_for_user", None)
        if not callable(lister):
            log.warning(
                "dev_instance_service has neither list_instances_by_user "
                "nor list_for_user — denying deploy by default."
            )
            return False

        try:
            instances = lister(user.username) or []
        except Exception:  # noqa: BLE001
            log.exception("list_instances_by_user crashed for user %s", user.username)
            return False

        username = user.username
        for inst in instances:
            parent = getattr(inst, "parent_project", None) or (
                inst.get("parent_project") if isinstance(inst, dict) else None
            )
            owner = getattr(inst, "owner_username", None) or (
                inst.get("owner_username") if isinstance(inst, dict) else None
            )
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
        limit = max(1, min(int(limit), 500))
        q = (
            "SELECT d.*, s.label AS server_label, s.env AS server_env "
            "FROM deployments d LEFT JOIN servers s ON s.id = d.server_id "
        )
        args: Tuple = ()
        if project_name:
            q += "WHERE d.project_name = ? "
            args = (project_name,)
        q += "ORDER BY d.started_at DESC LIMIT ?"
        args = args + (limit,)

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
        self._validate_branch(branch)

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

        # Single transaction: insert row, capture the rowid, and patch
        # the log_file path using the known id — without ever leaving
        # the row in the `log_file=''` state visible to readers.
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
                (project_name, int(server_id), branch, triggered_by, now, ""),
            )
            deployment_id = cur.lastrowid
            log_path = os.path.join(self.log_dir, f"{deployment_id}.log")
            cur.execute(
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

    @staticmethod
    def _validate_branch(branch: str) -> None:
        """Reject obviously-dangerous branch names before shell interpolation.

        The regex already whitelists the charset, but we additionally
        forbid `..` path segments and leading `-` to avoid anyone
        sneaking a path-traversal component or an ``--upload-pack=…``
        style option into ``git reset --hard origin/<branch>``.
        """
        if not branch or not _BRANCH_RE.match(branch):
            raise ValueError("Invalid branch name.")
        if ".." in branch.split("/") or ".." in branch:
            raise ValueError("Invalid branch name (path traversal).")
        if branch.startswith("-"):
            raise ValueError("Invalid branch name (leading dash).")

    # ─── internals ───────────────────────────────────────────────────

    def _execute_wrapped(self, app, deployment_id, server, project_name, branch, log_path):
        """Thread target: establishes app context then delegates."""
        with app.app_context():
            try:
                self._execute(deployment_id, server, project_name, branch, log_path)
            except Exception as exc:  # noqa: BLE001
                log.exception("Deployment %s crashed", deployment_id)
                self._emit(deployment_id, log_path, f"[deployment crashed: {exc}]", stream="stderr")
                self._finalize(deployment_id, status="failed", commit_sha=None)

    def _execute(self, deployment_id, server, project_name, branch, log_path):
        start = time.monotonic()

        secret_key = current_app.config.get("SECRET_KEY") or ""
        try:
            pem = ssh_service.decrypt_private_key(secret_key, bytes(server.ssh_private_key_enc))
        except Exception as exc:  # noqa: BLE001
            self._emit(deployment_id, log_path, f"[cannot decrypt server key: {exc}]", stream="stderr")
            self._finalize(deployment_id, status="failed", commit_sha=None)
            return

        self._emit(
            deployment_id,
            log_path,
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
            self._emit(deployment_id, log_path, f"[SSH connect failed: {exc}]", stream="stderr")
            self._finalize(deployment_id, status="failed", commit_sha=None)
            return

        # Custom (project, server) path wins over <base_path>/<project_name>.
        deploy_path = self.resolve_deploy_path(project_name, server)
        # Safe: branch was validated by regex above; deploy_path is
        # server-controlled (admin-supplied); project_name is a slug.
        script = (
            "set -e\n"
            f"cd {_shell_quote(deploy_path)}\n"
            "git fetch --prune origin\n"
            f"git reset --hard origin/{_shell_quote(branch)}\n"
            "git rev-parse HEAD\n"
        )
        self._emit(deployment_id, log_path, f"$ cd {deploy_path}", stream="stdout")
        self._emit(deployment_id, log_path, "$ git fetch --prune origin", stream="stdout")
        self._emit(deployment_id, log_path, f"$ git reset --hard origin/{branch}", stream="stdout")

        commit_sha: Optional[str] = None
        status = "failed"
        try:
            # paramiko's `timeout=` is a per-recv inactivity timeout;
            # the real wall-clock guard lives in _stream_channel.
            stdin, stdout, stderr = client.exec_command(script, get_pty=False)
            channel = stdout.channel
            stdin.close()

            # Keep a ring buffer of stdout lines so we can recover the
            # commit sha from `git rev-parse HEAD` without holding the
            # full log in memory for noisy deploys.
            tail_stdout: List[str] = []
            tail_max = 50

            def on_line(line: str, stream: str):
                if stream == "stdout":
                    tail_stdout.append(line)
                    if len(tail_stdout) > tail_max:
                        del tail_stdout[0]
                self._emit(deployment_id, log_path, line, stream=stream)

            self._stream_channel(channel, on_line, start, deployment_id)

            exit_code = channel.recv_exit_status()
            if exit_code == 0:
                status = "success"
                # `git rev-parse HEAD` was the last command; the last
                # non-empty stdout line is the commit sha.
                for line in reversed(tail_stdout):
                    candidate = line.strip()
                    if re.fullmatch(r"[0-9a-f]{40}", candidate):
                        commit_sha = candidate
                        break
            else:
                self._emit(
                    deployment_id,
                    log_path,
                    f"[remote exited with code {exit_code}]",
                    stream="stderr",
                )
                status = "failed"
        except TimeoutError:
            self._emit(deployment_id, log_path, "[deployment timed out]", stream="stderr")
            status = "timeout"
        except socket.timeout:
            self._emit(deployment_id, log_path, "[deployment timed out]", stream="stderr")
            status = "timeout"
        except paramiko.SSHException as exc:
            # Paramiko surfaces channel-level timeouts as SSHException
            # with "Timeout" in the message — treat them as timeouts so
            # the UI shows the correct pill.
            if "timeout" in str(exc).lower():
                self._emit(deployment_id, log_path, "[deployment timed out]", stream="stderr")
                status = "timeout"
            else:
                self._emit(deployment_id, log_path, f"[SSH error: {exc}]", stream="stderr")
                status = "failed"
        except Exception as exc:  # noqa: BLE001
            self._emit(deployment_id, log_path, f"[exec error: {exc}]", stream="stderr")
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

    def _emit(self, deployment_id: int, log_path: Optional[str], line: str, *, stream: str) -> None:
        """Append a redacted line to the deployment's log file and broadcast it.

        ``log_path`` is passed in from the caller so we avoid a DB
        round-trip per log line — a noisy deploy could otherwise open
        hundreds of SQLite connections per second and starve other
        writers.
        """
        safe = ssh_service.redact_private_keys(line)
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"[{stream}] {safe}\n")
            except OSError:
                pass

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
        self._prune_old_logs()
        if self.socketio is not None:
            try:
                self.socketio.emit(
                    "deployment_complete",
                    {"id": deployment_id, "status": status, "commit_sha": commit_sha, "finished_at": finished},
                    room=f"deploy_{deployment_id}",
                )
            except Exception:  # noqa: BLE001
                pass

    def _prune_old_logs(self) -> None:
        """Cap the number of on-disk log files at _MAX_LOG_FILES."""
        try:
            entries = [
                (os.path.getmtime(os.path.join(self.log_dir, f)), f)
                for f in os.listdir(self.log_dir)
                if f.endswith(".log")
            ]
        except OSError:
            return
        if len(entries) <= _MAX_LOG_FILES:
            return
        entries.sort()  # oldest first
        excess = len(entries) - _MAX_LOG_FILES
        for _, name in entries[:excess]:
            try:
                os.remove(os.path.join(self.log_dir, name))
            except OSError:
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
