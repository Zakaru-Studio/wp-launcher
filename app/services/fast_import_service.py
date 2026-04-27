#!/usr/bin/env python3
"""
Fast SQL import into a project's MySQL container.

The previous implementation was broken in a few hard-to-notice ways:

  1. It ran ``mysql -e 'SOURCE /tmp/import.sql'``. ``SOURCE`` is a
     *client metacommand*, not a SQL statement — passed via ``-e`` it
     silently no-ops or only runs the first line.
  2. It issued ``SET SESSION foreign_key_checks=0`` in a separate mysql
     invocation. That session died before the import session opened.
  3. It read the whole dump into RAM for analysis and prefix rewriting.
     OOM on multi-GB files.
  4. ``-prootpassword`` was hard-coded, breaking any project where a
     custom MySQL root password was set.
  5. It dropped the DB before import with no backup; a failed import
     left the project with no way back.

This rewrite:
  - Pipes the dump straight into ``docker exec -i mysql ...`` via stdin
    (no ``docker cp``, no ``/tmp`` round-trip, no ``SOURCE``).
  - Injects the session pragmas as the first bytes of that same stream
    so they apply to the import session.
  - Reads the file once, in chunks, emitting byte-based progress.
  - Auto-detects the MySQL root password from ``docker inspect`` env
    and falls back to ``rootpassword`` only if the env is unreadable.
  - Dumps the current DB to ``logs/db-backups/<project>/<ts>.sql.gz``
    before the drop so a failed import is recoverable.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config.app_config import PROJECTS_FOLDER
from app.utils.logger import wp_logger

log = logging.getLogger(__name__)


# How many MB to keep backed up per project before rotating oldest out.
_BACKUP_KEEP = 5
# Chunk size when piping the dump into mysql. 1 MiB is a good balance
# between syscall overhead and memory footprint.
_PIPE_CHUNK = 1024 * 1024
# Bytes of the dump we scan for metadata (create tables / prefix / WP
# keywords). We don't need the whole file for those signals.
_ANALYZE_MAX_BYTES = 32 * 1024 * 1024  # 32 MB
# Wall-clock import limit. Tuned for very large dumps on slow disks.
_IMPORT_TIMEOUT_SECONDS = 3600  # 1 hour

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z0-9_]+)`?",
    re.IGNORECASE,
)


# ────────────────────────────────────────────────────────────────────────
# Container-info helpers
# ────────────────────────────────────────────────────────────────────────


@dataclass
class ContainerInfo:
    container: str
    database: str
    user: str
    password: str
    root_password: str
    project_type: str  # 'wordpress' or 'nextjs'


@dataclass
class _MemoryState:
    """Snapshot of a container's memory limits so we can restore them
    after a temporary bump. Stores the raw bytes Docker reports."""
    memory: int
    memory_swap: int


# Mysql needs roughly 4-5× the single largest INSERT in RAM to parse,
# index and commit it. For a 284 MB dump with Elementor blobs, that
# can easily be 1-2 GB of working set. We bump to this floor for the
# duration of the import.
_IMPORT_MEMORY_BYTES = 2 * 1024 * 1024 * 1024           # 2 GiB
_IMPORT_MEMORY_SWAP_BYTES = 3 * 1024 * 1024 * 1024      # 3 GiB


def _docker_inspect_env(container: str) -> Dict[str, str]:
    """Return the container's Config.Env as a dict.

    Raises nothing — an unreachable container yields an empty dict so
    callers fall back to defaults.
    """
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    if result.returncode != 0:
        return {}
    env: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            env[k.strip()] = v
    return env


def _docker_inspect_memory(container: str) -> Optional[_MemoryState]:
    """Read the container's current memory + swap limits in bytes.

    Returns None if docker is unavailable or the inspect fails. A limit
    of ``0`` means "no limit", which is what Docker reports for
    unconstrained containers.
    """
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format',
             '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}', container],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    try:
        return _MemoryState(memory=int(parts[0]), memory_swap=int(parts[1]))
    except (IndexError, ValueError):
        return None


def _docker_update_memory(container: str, memory: int, swap: int) -> bool:
    """Apply new memory + memory_swap limits via ``docker update``.

    Returns True on success. Docker supports live memory updates on
    cgroups v1 and v2; the only common failure mode is insufficient
    host memory (which the caller logs and proceeds without a bump).
    """
    try:
        result = subprocess.run(
            ['docker', 'update',
             f'--memory={memory}',
             f'--memory-swap={swap}',
             container],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if result.returncode != 0:
        log.warning("docker update memory failed for %s: %s",
                    container, result.stderr.strip())
        return False
    return True


def _docker_container_started_at(container: str) -> Optional[str]:
    """Return ``.State.StartedAt`` of the container.

    Used as a restart canary during long-running imports: if the
    timestamp changes mid-import, mysql was killed (OOM) and our
    ``docker exec`` wrapper is now zombied.
    """
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.StartedAt}}', container],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _mysql_user_has_active_connection(
    container: str, root_password: str, user: str,
) -> Optional[bool]:
    """Return True if ``user`` has any active connection in mysql, False
    if confirmed absent, None if the probe itself failed.

    Used as a "mysql is idle" signal: after ``stdin.close()``, the
    import connection closes when mysql finishes the last statement.
    ``docker exec -i`` on some kernels + docker versions fails to
    detect stdin EOF in time and hangs in a futex wait for the daemon
    — we break that deadlock by killing it ourselves once the server-
    side work is clearly done.
    """
    try:
        result = subprocess.run(
            ['docker', 'exec', container,
             'mysql', '-h', 'localhost', '-u', 'root', f'-p{root_password}',
             '-N', '-B', '-e',
             f"SELECT COUNT(*) FROM information_schema.processlist "
             f"WHERE user = '{user}'"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip()) > 0
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────────────────
# Service
# ────────────────────────────────────────────────────────────────────────


class FastImportService:
    """Runs a SQL import against a project's MySQL container."""

    def __init__(self, socketio=None, projects_folder: Optional[str] = None):
        self.socketio = socketio
        self.projects_folder = projects_folder or PROJECTS_FOLDER
        self.mysql_container_prefix = "mysql"
        self.db_name = "wordpress"
        self.db_user = "wordpress"
        self.db_password = "wordpress"

    # ─── SocketIO progress ────────────────────────────────────────────

    def _emit_progress(
        self,
        project_name: str,
        progress: int,
        message: str,
        status: str = 'importing',
        table_name: Optional[str] = None,
    ) -> None:
        """Emit a ``database_import`` event the frontend modal listens on."""
        if self.socketio is None:
            log.debug("[%s] %d%% %s", project_name, progress, message)
            return
        data: Dict[str, Any] = {
            'type': 'database_import',
            'project': project_name,
            'progress': progress,
            'message': message,
            'status': status,
        }
        if table_name:
            data['table'] = table_name
        try:
            self.socketio.emit('import_progress', data)
        except Exception:  # noqa: BLE001
            log.exception("socketio.emit failed for project=%s", project_name)

    # ─── container / credentials detection ───────────────────────────

    def get_container_mysql_info(self, project_name: str) -> ContainerInfo:
        """Auto-detect container name, DB credentials and root password.

        Reads ``docker inspect`` env so a user who edited docker-compose
        won't silently fall off the happy path. Defaults mirror the
        shipped templates (``wordpress``/``wordpress``/``rootpassword``
        for WP, ``<project>``/``projectpassword``/``rootpassword`` for
        the Next.js+MySQL stack).
        """
        container = f"{project_name}_{self.mysql_container_prefix}_1"
        env = _docker_inspect_env(container)
        project_type = self._detect_project_type(project_name)

        if project_type == 'nextjs':
            default_user = project_name
            default_db = project_name
            default_pw = 'projectpassword'
        else:
            default_user = self.db_user
            default_db = self.db_name
            default_pw = self.db_password

        return ContainerInfo(
            container=container,
            database=env.get('MYSQL_DATABASE') or default_db,
            user=env.get('MYSQL_USER') or default_user,
            password=env.get('MYSQL_PASSWORD') or default_pw,
            root_password=env.get('MYSQL_ROOT_PASSWORD') or 'rootpassword',
            project_type=project_type,
        )

    def _detect_project_type(self, project_name: str) -> str:
        """Inspect running containers to decide WP vs Next.js+MySQL."""
        for suffix, kind in (('client_1', 'nextjs'), ('wordpress_1', 'wordpress')):
            try:
                result = subprocess.run(
                    ['docker', 'ps', '--filter', f'name={project_name}_{suffix}',
                     '--format', '{{.Names}}'],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
            if result.returncode == 0 and f'{project_name}_{suffix}' in result.stdout:
                return kind
        return 'wordpress'

    # ─── maintenance-mode toggle ─────────────────────────────────────

    def enable_maintenance_mode(self, project_name: str) -> Optional[str]:
        """Create the WP ``.maintenance`` guard file. Returns its path."""
        try:
            maintenance_file = os.path.join(self.projects_folder, project_name, '.maintenance')
            content = f"<?php $upgrading = {int(time.time())}; ?>"
            with open(maintenance_file, 'w', encoding='utf-8') as f:
                f.write(content)
            return maintenance_file
        except Exception:  # noqa: BLE001
            log.exception("enable_maintenance_mode failed for %s", project_name)
            return None

    def disable_maintenance_mode(self, project_name_or_file) -> None:
        """Accepts either a project name (preferred) or the raw file path."""
        path: Optional[str]
        if project_name_or_file and os.path.isabs(str(project_name_or_file)):
            path = str(project_name_or_file)
        elif project_name_or_file:
            path = os.path.join(self.projects_folder, str(project_name_or_file), '.maintenance')
        else:
            return
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                log.warning("Could not remove maintenance file %s", path)

    # Legacy names — kept for backwards-compat with call sites that
    # used the underscored form. Prefer the public names above.
    _enable_maintenance_mode = enable_maintenance_mode
    _disable_maintenance_mode = disable_maintenance_mode

    # ─── file prep (unzip / ungzip) ──────────────────────────────────

    def _prepare_sql_file(self, file_path: str) -> Optional[str]:
        """Decompress a ``.gz`` or ``.zip`` if needed; return the .sql path.

        The caller is responsible for deleting the returned path if it
        differs from ``file_path`` (it's under tempdir).
        """
        ext = os.path.splitext(file_path)[1].lower()
        # Support .sql.gz by treating double-extension correctly.
        if file_path.lower().endswith('.sql.gz'):
            ext = '.gz'

        if ext == '.sql':
            return file_path

        if ext == '.gz':
            fd, temp_sql = tempfile.mkstemp(suffix='.sql')
            os.close(fd)
            try:
                with gzip.open(file_path, 'rb') as src, open(temp_sql, 'wb') as dst:
                    shutil.copyfileobj(src, dst, length=_PIPE_CHUNK)
                return temp_sql
            except Exception:  # noqa: BLE001
                log.exception("gzip decompression failed for %s", file_path)
                if os.path.exists(temp_sql):
                    os.remove(temp_sql)
                return None

        if ext == '.zip':
            temp_dir = tempfile.mkdtemp()
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    zf.extractall(temp_dir)
                for root, _, files in os.walk(temp_dir):
                    for fn in files:
                        if fn.lower().endswith('.sql'):
                            return os.path.join(root, fn)
            except Exception:  # noqa: BLE001
                log.exception("zip extraction failed for %s", file_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        log.warning("Unsupported extension: %s", ext)
        return None

    # ─── streaming analysis ──────────────────────────────────────────

    def _stream_analyze_sql(self, sql_file: str) -> Dict[str, Any]:
        """Scan up to _ANALYZE_MAX_BYTES of the dump to collect stats.

        Reads line-by-line so memory stays bounded even for multi-GB
        files. The CREATE TABLE list it returns is authoritative for
        the first N MBs — further tables are still imported (the full
        file is streamed into mysql) but not counted in progress.
        """
        tables: List[str] = []
        is_mariadb = False
        is_wordpress = False
        wp_keywords = {'wp_options', 'wp_posts', 'wp_users', 'wp_comments'}
        wp_hits: List[str] = []
        bytes_read = 0

        try:
            with open(sql_file, 'rb') as f:
                header = f.read(2048)
                if b'MariaDB dump' in header or b'MariaDB' in header:
                    is_mariadb = True
                f.seek(0)
                for raw in f:
                    bytes_read += len(raw)
                    if bytes_read > _ANALYZE_MAX_BYTES:
                        break
                    try:
                        line = raw.decode('utf-8', errors='replace')
                    except Exception:  # noqa: BLE001
                        continue
                    match = _CREATE_TABLE_RE.search(line)
                    if match:
                        name = match.group(1)
                        if name and not name.startswith('`'):
                            tables.append(name)
                    low = line.lower()
                    for kw in wp_keywords:
                        if kw in low and kw not in wp_hits:
                            wp_hits.append(kw)
                            if len(wp_hits) >= 2:
                                is_wordpress = True
        except OSError:
            log.exception("analyze: could not read %s", sql_file)

        tables = sorted(set(tables))
        file_size = os.path.getsize(sql_file) if os.path.exists(sql_file) else 0
        return {
            'table_count': len(tables),
            'create_tables': tables,
            'file_size': file_size,
            'file_size_mb': file_size / (1024 * 1024),
            'encoding': 'utf-8',
            'is_mariadb': is_mariadb,
            'is_wordpress': is_wordpress,
            'wp_tables': wp_hits,
        }

    # ─── streaming prefix adaptation ─────────────────────────────────

    def _detect_source_prefix(self, sql_file: str) -> Optional[str]:
        """Scan the first ~10 MB for common WP tables to guess the prefix."""
        known = ['options', 'posts', 'users', 'comments', 'postmeta', 'usermeta',
                 'terms', 'term_relationships', 'term_taxonomy', 'termmeta',
                 'commentmeta', 'links']
        counter: Counter = Counter()
        bytes_read = 0
        try:
            with open(sql_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    bytes_read += len(line)
                    if bytes_read > 10 * 1024 * 1024:
                        break
                    for table in known:
                        for match in re.finditer(
                            rf'`([A-Za-z0-9_]+)_{table}`',
                            line,
                        ):
                            counter[match.group(1)] += 1
        except OSError:
            return None
        if not counter:
            return None
        return counter.most_common(1)[0][0] + '_'

    def _read_target_prefix(self, project_name: str) -> str:
        """Read ``$table_prefix`` from wp-config.php, fallback to ``wp_``."""
        wp_config = os.path.join(self.projects_folder, project_name, 'wp-config.php')
        if not os.path.exists(wp_config):
            return 'wp_'
        try:
            with open(wp_config, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            m = re.search(r"\$table_prefix\s*=\s*['\"]([^'\"]+)['\"]", content)
            if m:
                return m.group(1)
        except OSError:
            pass
        return 'wp_'

    def _stream_adapt_prefix(
        self,
        sql_file: str,
        project_name: str,
    ) -> str:
        """Rewrite the dump's table prefix to match wp-config if needed.

        Returns the path to the SQL file we should actually import.
        Always streams line-by-line; never buffers the full file.
        """
        target = self._read_target_prefix(project_name)
        source = self._detect_source_prefix(sql_file)

        if not source or source == target:
            log.info("prefix: no rewrite needed (source=%s target=%s)", source, target)
            return sql_file

        log.info("prefix: rewriting %s -> %s", source, target)
        src_esc = re.escape(source)

        # Table references (backticked and bare) + meta_key values.
        pat_bt = re.compile(rf'`{src_esc}([A-Za-z0-9_]+)`')
        pat_bare = re.compile(rf'(\b){src_esc}([A-Za-z0-9_]+)\b')
        meta_keys = {'capabilities', 'user_level', 'user-settings', 'user-settings-time',
                     'dashboard_quick_press_last_post_id', 'user-avatar', 'metaboxhidden',
                     'closedpostboxes', 'primary_blog', 'source_domain', 'user_roles'}

        def rewrite_line(line: str) -> str:
            line = pat_bt.sub(lambda m: f'`{target}{m.group(1)}`', line)
            line = pat_bare.sub(lambda m: f'{m.group(1)}{target}{m.group(2)}', line)
            # PHP-serialized s:N:"prefix_something" — recompute length.
            def _s_fix(m: re.Match) -> str:
                inner = m.group(2).replace(source, target, 1)
                return f's:{len(inner)}:"{inner}"'
            line = re.sub(rf's:\d+:"({src_esc}[A-Za-z0-9_]+)"',
                          _s_fix, line)
            for mk in meta_keys:
                line = line.replace(f"'{source}{mk}'", f"'{target}{mk}'")
                line = line.replace(f'"{source}{mk}"', f'"{target}{mk}"')
            return line

        fd, out_path = tempfile.mkstemp(suffix='_adapted.sql')
        os.close(fd)
        try:
            with open(sql_file, 'r', encoding='utf-8', errors='replace') as src_f, \
                 open(out_path, 'w', encoding='utf-8') as out_f:
                for line in src_f:
                    out_f.write(rewrite_line(line))
        except OSError:
            log.exception("prefix rewrite failed, keeping original")
            if os.path.exists(out_path):
                os.remove(out_path)
            return sql_file

        # Clean up the previous temp if it was one
        if sql_file.startswith(tempfile.gettempdir()) and sql_file != out_path:
            try:
                os.remove(sql_file)
            except OSError:
                pass
        return out_path

    # ─── pre-import backup ───────────────────────────────────────────

    def _backup_current_db(self, project_name: str, info: ContainerInfo) -> Optional[str]:
        """Dump the current DB to ``logs/db-backups/<project>/<ts>.sql.gz``.

        Returns the backup path so a failed import can point the user
        at it. Non-fatal: if the dump fails we log and proceed (the
        user chose to replace the DB anyway).
        """
        backup_root = os.path.join('logs', 'db-backups', project_name)
        os.makedirs(backup_root, exist_ok=True)
        ts = time.strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_root, f'pre-import_{ts}.sql.gz')

        # Write a per-container .mysqldump.cnf with the credentials so
        # the password never appears on the command line.
        cnf_content = (
            f"[mysqldump]\nuser={info.user}\npassword={info.password}\n"
        ).encode('utf-8')
        write_cnf = subprocess.Popen(
            ['docker', 'exec', '-i', info.container, 'sh', '-c',
             'cat > /tmp/.mysqldump.cnf && chmod 600 /tmp/.mysqldump.cnf'],
            stdin=subprocess.PIPE,
        )
        write_cnf.communicate(cnf_content, timeout=15)
        if write_cnf.returncode != 0:
            log.warning("backup: could not write mysqldump cnf")
            return None

        dump_cmd = [
            'docker', 'exec', info.container,
            'mysqldump',
            '--defaults-file=/tmp/.mysqldump.cnf',
            '--quick', '--single-transaction', '--lock-tables=false',
            '--routines', '--triggers', '--hex-blob',
            '--no-tablespaces', '--default-character-set=utf8mb4',
            info.database,
        ]
        try:
            with gzip.open(backup_path, 'wb') as gz:
                proc = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                assert proc.stdout is not None
                shutil.copyfileobj(proc.stdout, gz, length=_PIPE_CHUNK)
                _, stderr = proc.communicate(timeout=_IMPORT_TIMEOUT_SECONDS)
                if proc.returncode != 0:
                    log.warning("backup: mysqldump exit=%d err=%s",
                                proc.returncode, stderr.decode('utf-8', errors='replace')[:500])
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    return None
        except Exception:  # noqa: BLE001
            log.exception("backup: dump crashed")
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return None
        finally:
            try:
                subprocess.run(
                    ['docker', 'exec', info.container, 'rm', '-f', '/tmp/.mysqldump.cnf'],
                    capture_output=True, timeout=10,
                )
            except Exception:  # noqa: BLE001
                pass

        self._rotate_backups(backup_root)
        log.info("backup: wrote %s (%s bytes)",
                 backup_path, os.path.getsize(backup_path) if os.path.exists(backup_path) else 0)
        return backup_path

    @staticmethod
    def _rotate_backups(backup_root: str) -> None:
        try:
            files = sorted(
                (os.path.join(backup_root, f) for f in os.listdir(backup_root)
                 if f.endswith('.sql.gz')),
                key=os.path.getmtime,
            )
        except OSError:
            return
        while len(files) > _BACKUP_KEEP:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except OSError:
                log.warning("backup rotation: failed to remove %s", oldest)

    # ─── drop + recreate ─────────────────────────────────────────────

    def _recreate_database(self, info: ContainerInfo) -> bool:
        """DROP + CREATE + (re)create user + GRANT using the detected
        root password.

        MySQL 8 no longer auto-creates users on GRANT, so we issue a
        ``CREATE USER IF NOT EXISTS`` + ``ALTER USER`` pair before the
        GRANT. That ensures the import account exists and has the
        expected password, even if the container was rebuilt or the
        user was dropped manually.

        We also bump ``max_allowed_packet`` server-side — wp-migrate
        dumps routinely ship single INSERTs > 64 MB (Elementor-laden
        ``wp_postmeta``), and the default kills the connection at
        byte 67108864 with the not-very-helpful behaviour of just
        closing the socket.
        """
        esc_pwd = info.password.replace("'", "''")
        sql = (
            # Server-side tuning for the import session's lifetime —
            # SET GLOBAL requires SUPER which root has. 1 GiB is
            # overkill for typical WP dumps but cheap at rest.
            "SET GLOBAL max_allowed_packet = 1073741824;"
            "SET GLOBAL net_read_timeout = 3600;"
            "SET GLOBAL net_write_timeout = 3600;"
            "SET GLOBAL wait_timeout = 7200;"
            f"DROP DATABASE IF EXISTS `{info.database}`;"
            f"CREATE DATABASE `{info.database}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            f"CREATE USER IF NOT EXISTS '{info.user}'@'%' "
            f"IDENTIFIED BY '{esc_pwd}';"
            f"ALTER USER '{info.user}'@'%' IDENTIFIED BY '{esc_pwd}';"
            f"GRANT ALL PRIVILEGES ON `{info.database}`.* TO '{info.user}'@'%';"
            f"FLUSH PRIVILEGES;"
        )
        cmd = [
            'docker', 'exec', info.container,
            'mysql', '-h', 'localhost', '-u', 'root',
            f'-p{info.root_password}',
            '-e', sql,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            log.error("recreate: timeout")
            return False
        if result.returncode != 0:
            log.error("recreate: exit=%d err=%s", result.returncode, result.stderr)
            return False
        return True

    # ─── stream import ───────────────────────────────────────────────

    # Exceptions that can come out of writing to a dying Popen pipe —
    # BrokenPipe on Linux, ValueError from "flush/write on closed file"
    # if the buffer got closed before we got there, OSError catches
    # rarer cases (EPIPE, EBADF).
    _PIPE_EXCS = (BrokenPipeError, ValueError, OSError)

    def _verify_mysql_auth(self, info: ContainerInfo) -> Optional[str]:
        """Quick ``SELECT 1`` as the import user — returns an error
        string if auth fails, None on success.

        Catches the #1 "mysql dies instantly → pipe breaks" case and
        turns it into a real, readable message before we bother
        spinning up a streaming import.
        """
        try:
            result = subprocess.run(
                ['docker', 'exec', info.container,
                 'mysql', '-h', 'localhost',
                 '-u', info.user, f'-p{info.password}',
                 info.database, '-e', 'SELECT 1'],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            return "mysql auth check timed out"
        except FileNotFoundError:
            return "docker binary not found"
        if result.returncode == 0:
            return None
        # Filter the insecure-password warning noise.
        stderr = "\n".join(
            l for l in (result.stderr or "").splitlines()
            if 'password on the command line' not in l.lower()
        ).strip()
        return stderr or f"mysql auth check failed (exit {result.returncode})"

    def _bump_memory_for_import(
        self,
        info: ContainerInfo,
        project_name: str,
    ) -> Optional[_MemoryState]:
        """Temporarily raise the container's memory limit to ~2 GiB
        so a large import doesn't get OOM-killed.

        Returns the ORIGINAL limits so the caller can restore them
        after the import. Returns None if the bump failed or wasn't
        needed (e.g. already >= the threshold).
        """
        current = _docker_inspect_memory(info.container)
        if current is None:
            return None
        # 0 == unlimited. Anything already above our floor, leave alone.
        already_generous = (
            current.memory == 0 or current.memory >= _IMPORT_MEMORY_BYTES
        )
        if already_generous:
            return None
        ok = _docker_update_memory(
            info.container,
            _IMPORT_MEMORY_BYTES,
            _IMPORT_MEMORY_SWAP_BYTES,
        )
        if not ok:
            self._emit_progress(
                project_name, 0,
                f"Impossible de bumper la RAM du container {info.container}. "
                f"L'import peut être OOM-killé.",
                'importing',
            )
            return None
        mb = _IMPORT_MEMORY_BYTES // (1024 * 1024)
        log.info("bumped %s memory from %d -> %d MB",
                 info.container, current.memory // (1024 * 1024), mb)
        self._emit_progress(
            project_name, 33,
            f"RAM du container augmentée temporairement à {mb} MB "
            f"pour l'import (était {current.memory // (1024 * 1024)} MB).",
            'importing',
        )
        return current

    def _restore_memory(self, info: ContainerInfo, original: Optional[_MemoryState]) -> None:
        """Reset the container to its pre-bump memory limits.

        Non-fatal: if the restore fails (container was recreated mid-
        import, etc.), we log and proceed — the limits will be
        whatever the next compose-up sets.
        """
        if original is None:
            return
        ok = _docker_update_memory(info.container, original.memory, original.memory_swap)
        if ok:
            log.info("restored %s memory to %d bytes",
                     info.container, original.memory)
        else:
            log.warning("could not restore memory on %s", info.container)

    def _import_sql_stream(
        self,
        project_name: str,
        sql_file: str,
        info: ContainerInfo,
        file_size: int,
    ) -> Dict[str, Any]:
        """Pipe the SQL file into ``docker exec -i mysql …`` via stdin.

        The session pragmas are written as the first bytes of the same
        stream so they take effect on the import session. Progress is
        emitted every ~2 % by tracking bytes sent.

        If mysql dies mid-stream we ALWAYS drain its stderr before
        returning, so the user sees the actual SQL/auth error rather
        than ``[Errno 32] Broken pipe`` or ``flush of closed file``.

        A restart canary (``.State.StartedAt``) runs during the
        post-stream wait so an OOM-restart of the mysql container
        can't leave us staring at a zombie ``docker exec``.
        """
        # Pre-flight: a dead-on-arrival mysql (wrong password, missing
        # db, grant loss) breaks the pipe before our first write and
        # blows up as a cryptic ValueError. Catch it here with a
        # readable message.
        auth_err = self._verify_mysql_auth(info)
        if auth_err:
            self._emit_progress(project_name, 0, f"MySQL auth: {auth_err[:300]}", 'error')
            return {'success': False, 'error': f"MySQL auth: {auth_err}", 'bytes_sent': 0}

        # Snapshot the container's StartedAt so we can detect a restart
        # (OOM, docker-compose restart) that would zombie our exec.
        started_at_before = _docker_container_started_at(info.container)

        # Why these flags:
        #   --max_allowed_packet=1G: giant INSERTs (Elementor blobs in
        #     wp_postmeta/wp_options) blow past the 64 MB default.
        #   --force: keep going after single-row errors. Real WP dumps
        #     routinely carry garbage in cache tables (Wordfence IP
        #     logs, session caches) — duplicate-key there should not
        #     abort the whole import. We surface the count of errors
        #     as a post-import warning, not a hard failure.
        #   --show-warnings: echo warnings (including forced-past
        #     errors) with line numbers so the UI can display them.
        cmd = [
            'docker', 'exec', '-i', info.container,
            'mysql', '-h', 'localhost',
            '-u', info.user, f'-p{info.password}',
            '--default-character-set=utf8mb4',
            '--max_allowed_packet=1G',
            '--force',
            '--show-warnings',
            info.database,
        ]

        prelude = (
            b"/*!40101 SET NAMES utf8mb4 */;\n"
            b"SET SESSION foreign_key_checks=0;\n"
            b"SET SESSION unique_checks=0;\n"
            b"SET SESSION sql_notes=0;\n"
            b"SET SESSION autocommit=1;\n"
            # NOTE: ``max_allowed_packet`` is read-only at the session
            # scope on MySQL 8 (ERROR 1621). We raise it GLOBAL in
            # ``_recreate_database`` via root BEFORE opening this
            # session — the new connection picks up the new global.
            # The timeouts below are session-writable and matter for
            # slow imports (default ``net_write_timeout`` is 60s).
            b"SET SESSION net_read_timeout=3600;\n"
            b"SET SESSION net_write_timeout=3600;\n"
            b"SET SESSION wait_timeout=7200;\n"
        )
        epilogue = (
            b"\nSET SESSION foreign_key_checks=1;\n"
            b"SET SESSION unique_checks=1;\n"
        )

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # unbuffered stdin so a dying mysql surfaces quickly
            )
        except FileNotFoundError:
            return {'success': False, 'error': 'docker binary not found'}

        assert proc.stdin is not None
        sent = 0
        last_pct = 0
        size_mb = max(file_size, 1) / (1024 * 1024)
        pipe_broken = False

        def _safe_write(buf: bytes) -> bool:
            nonlocal pipe_broken
            if pipe_broken:
                return False
            try:
                proc.stdin.write(buf)
                return True
            except self._PIPE_EXCS:
                pipe_broken = True
                return False

        # Blanket try/finally so any exception (pipe, local read, etc.)
        # leaves the subprocess in a known state and we always reach
        # the stderr-drain + wait below.
        try:
            _safe_write(prelude)
            try:
                with open(sql_file, 'rb') as src:
                    while not pipe_broken:
                        chunk = src.read(_PIPE_CHUNK)
                        if not chunk:
                            break
                        if not _safe_write(chunk):
                            break
                        sent += len(chunk)
                        pct = 40 + int((sent / max(file_size, 1)) * 50)
                        if pct - last_pct >= 2:
                            sent_mb = sent / (1024 * 1024)
                            self._emit_progress(
                                project_name,
                                min(90, pct),
                                f"Import en cours… {sent_mb:.0f}/{size_mb:.0f} MB",
                                'importing',
                            )
                            last_pct = pct
            except OSError as exc:
                log.warning("import: local read failed: %s", exc)
            _safe_write(epilogue)
        finally:
            # Always detach + close stdin ourselves; we deliberately
            # avoid proc.communicate() below because it tries to flush
            # stdin a second time and raises "I/O operation on closed
            # file" when the BufferedWriter is already half-torn-down
            # by a pipe break.
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

        # Post-stream: mysql can spend *minutes* rebuilding indexes and
        # committing InnoDB state after seeing stdin EOF. We drain
        # stderr in a background thread (so mysql never blocks on a
        # full stderr pipe) and emit heartbeats so the UI doesn't look
        # frozen.
        stderr_chunks: List[bytes] = []

        def _drain_stderr() -> None:
            try:
                if proc.stderr is None:
                    return
                while True:
                    chunk = proc.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            except Exception:  # noqa: BLE001
                pass

        reader = threading.Thread(target=_drain_stderr, daemon=True)
        reader.start()

        wait_start = time.monotonic()
        last_heartbeat = wait_start
        last_restart_check = wait_start
        last_idle_check = wait_start
        # When the import user has had zero active connections for this
        # many consecutive probes, we conclude mysql is done and the
        # docker exec is the one stalling.
        idle_since: Optional[float] = None
        IDLE_THRESHOLD_SECONDS = 15
        docker_exec_bypassed = False
        while proc.poll() is None:
            now = time.monotonic()
            elapsed_total = now - wait_start
            if elapsed_total > _IMPORT_TIMEOUT_SECONDS:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                reader.join(timeout=5)
                return {
                    'success': False,
                    'error': "Timeout (> 1h) pendant la finalisation MySQL",
                    'bytes_sent': sent,
                }
            # Container-restart canary (polled every 10s). If the
            # ``docker exec`` is stuck talking to a dead mysql, we
            # kill it ourselves rather than wait for the outer timeout.
            if now - last_restart_check >= 10:
                current_started = _docker_container_started_at(info.container)
                if (started_at_before
                        and current_started
                        and current_started != started_at_before):
                    log.error(
                        "container %s restarted mid-import "
                        "(was %s, now %s) — killing zombie exec",
                        info.container, started_at_before, current_started,
                    )
                    proc.kill()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    reader.join(timeout=5)
                    return {
                        'success': False,
                        'error': (
                            f"Le container {info.container} a été redémarré "
                            "pendant l'import (très probablement OOM-kill). "
                            "Augmente sa mem_limit dans docker-compose ou "
                            "libère de la RAM sur l'hôte."
                        ),
                        'bytes_sent': sent,
                    }
                last_restart_check = now
            # Idle detection (polled every 5s). docker exec -i on some
            # docker daemon versions misses stdin EOF and hangs in a
            # futex wait for the daemon. If mysql has zero active
            # connections for our import user for IDLE_THRESHOLD
            # seconds, the server-side work is done: bypass the stall
            # by killing the hung exec ourselves.
            if now - last_idle_check >= 5:
                has_conn = _mysql_user_has_active_connection(
                    info.container, info.root_password, info.user,
                )
                if has_conn is False:
                    if idle_since is None:
                        idle_since = now
                    elif now - idle_since >= IDLE_THRESHOLD_SECONDS:
                        log.warning(
                            "mysql has been idle for %.0fs after stdin EOF — "
                            "killing hung docker-exec (Docker %s pipe quirk)",
                            now - idle_since, info.container,
                        )
                        proc.kill()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            pass
                        docker_exec_bypassed = True
                        break
                elif has_conn is True:
                    idle_since = None  # still working
                last_idle_check = now
            if now - last_heartbeat >= 5:
                self._emit_progress(
                    project_name, 92,
                    f"Finalisation MySQL (indexes, commit InnoDB)… "
                    f"{int(elapsed_total)}s",
                    'importing',
                )
                last_heartbeat = now
            time.sleep(0.5)

        reader.join(timeout=5)
        stderr_bytes = b"".join(stderr_chunks)

        # Drain any stdout still pending.
        try:
            if proc.stdout is not None:
                proc.stdout.read()
        except Exception:  # noqa: BLE001
            pass

        stderr = stderr_bytes.decode('utf-8', errors='replace').strip()
        # mysql 8 prints "[Warning] Using a password on the command
        # line interface can be insecure." — filter it out so it never
        # shows up as the headline error.
        stderr_lines = [
            l for l in stderr.splitlines()
            if 'password on the command line' not in l.lower()
        ]
        stderr_clean = "\n".join(stderr_lines).strip()

        # With --force, mysql keeps going past per-row errors; we
        # classify the outcome as:
        #   - hard fail: pipe broke early, or no bytes consumed, or a
        #     connection-level error (Can't connect / Access denied)
        #   - soft success: the full stream was fed AND the errors are
        #     only per-statement issues (duplicate key, FK violation,
        #     truncated value). These are common in real-world dumps
        #     and should not block the import.
        error_lines = [l for l in stderr_lines if l.startswith('ERROR ')]
        hard_fail_markers = ("Access denied", "Can't connect", "Unknown database")
        hit_hard_error = any(m in stderr_clean for m in hard_fail_markers)
        consumed_everything = (not pipe_broken) and sent >= max(file_size, 1) * 0.99

        # If we killed a hung docker-exec ourselves (the stdin-EOF
        # detection quirk), the non-zero return code is ours, not
        # mysql's. mysql is confirmed idle, so the import succeeded
        # up to whatever errors --force tolerated.
        if docker_exec_bypassed:
            return {
                'success': True,
                'bytes_sent': sent,
                'tolerated_errors': len(stderr_lines),
                'docker_exec_bypassed': True,
            }

        if hit_hard_error or (not consumed_everything and proc.returncode != 0):
            # Always include the exit code + bytes consumed so a silent
            # mysql death still carries some signal, even if stderr
            # was empty (SIGKILL, container OOM, docker crash).
            if stderr_clean:
                msg = stderr_clean
            else:
                sent_mb = sent / (1024 * 1024)
                msg = (
                    f"mysql exit={proc.returncode}, "
                    f"{sent_mb:.1f}/{file_size / (1024*1024):.1f} MB envoyés, "
                    f"stderr vide. Le client mysql a probablement été tué "
                    f"par le kernel (OOM) ou la session docker a été reset. "
                    f"Vérifie `docker logs {info.container}`."
                )
            truncated = msg[:800]
            if len(msg) > 800:
                truncated += "\n…(truncated)"
            first_line = truncated.splitlines()[0] if truncated else msg
            self._emit_progress(
                project_name, 0,
                f"MySQL a rejeté l'import : {first_line}",
                'error',
            )
            return {
                'success': False,
                'error': truncated,
                'bytes_sent': sent,
            }

        # Soft success: emit a summary of tolerated errors so the user
        # knows something was skipped. Log the full stderr server-side
        # for forensics.
        if error_lines:
            log.warning(
                "import soft-success with %d tolerated errors for %s:\n%s",
                len(error_lines), project_name, stderr_clean,
            )
            sample = error_lines[0][:250]
            self._emit_progress(
                project_name, 92,
                f"Import terminé avec {len(error_lines)} erreur(s) tolérée(s). "
                f"Ex: {sample}",
                'importing',
            )
        elif stderr_clean:
            self._emit_progress(
                project_name, 92,
                f"MySQL warnings: {stderr_clean[:300]}",
                'importing',
            )
        return {
            'success': True,
            'bytes_sent': sent,
            'tolerated_errors': len(error_lines),
        }

    # ─── URL replace (unchanged wp-cli flow) ────────────────────────

    def _perform_url_replacement(self, project_name: str) -> None:
        """Rewrite siteurl/home to the local port using wp-cli.

        Tries hard to leave no https:// pointer behind so the local
        container doesn't redirect to a URL its proxy cannot serve:
          1. search-replace old→new URL across the DB
          2. search-replace ``https://<host>[:port]`` → ``http://…``
             variants in case the dump had mixed protocols
          3. force ``home`` and ``siteurl`` options to the http URL
          4. deactivate known SSL-forcing plugins (Really Simple SSL)
             which re-hydrate force_ssl_admin on every request
          5. Elementor-specific URL pass if Elementor is installed
        """
        try:
            from app.config.docker_config import DockerConfig
            container_path = os.path.join(DockerConfig.CONTAINERS_FOLDER, project_name)
            port_file = os.path.join(container_path, '.port')
            if not os.path.exists(port_file):
                log.info("url_replace: no .port file for %s", project_name)
                return
            with open(port_file, 'r') as f:
                port = f.read().strip()
            if not port:
                return

            local_url = f"http://{DockerConfig.LOCAL_IP}:{port}"
            wp_container = f"{project_name}_wordpress_1"

            result = subprocess.run(
                ['docker', 'exec', wp_container, 'wp', 'option', 'get', 'siteurl', '--allow-root'],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log.warning("url_replace: wp option get failed: %s", result.stderr)
                return

            old_url = (result.stdout or "").strip()
            if not old_url:
                return

            # 1. Canonical old -> new replace (incl. trailing /).
            if old_url != local_url:
                log.info("url_replace: %s -> %s", old_url, local_url)
                self._run_search_replace(wp_container, old_url, local_url)

            # 2. Handle the protocol-flip case: if the source dump was
            # on https but search-replace was done above on the HTTP
            # host, any remaining https://<host> references (e.g.
            # embedded in serialized data / widget configs that used
            # a different capitalization or trailing slash) need a
            # second pass. We derive both variants from old_url and
            # rewrite them to the local http URL.
            host_from_old = old_url.split("://", 1)[-1].rstrip('/')
            for scheme in ('https', 'http'):
                candidate = f"{scheme}://{host_from_old}"
                if candidate != local_url:
                    self._run_search_replace(wp_container, candidate, local_url)

            # 3. Force-write home/siteurl so a misfired search-replace
            # on a serialized blob can't leave the canonical options
            # on the old domain.
            for opt in ('home', 'siteurl'):
                subprocess.run(
                    ['docker', 'exec', wp_container,
                     'wp', 'option', 'update', opt, local_url,
                     '--allow-root'],
                    capture_output=True, timeout=30,
                )

            # 4. Deactivate SSL-forcing plugins. These plugins rewrite
            # every request to https on load OR set HSTS, which
            # contaminates the browser's hostname-level cache and
            # makes every site on the same IP unreachable in http.
            ssl_forcing_plugins = (
                'really-simple-ssl',
                'really-simple-ssl-pro',
                'ssl-insecure-content-fixer',
                'wp-force-ssl',
                'ssl-zen',
                'wp-https',
                'cloudflare-flexible-ssl',
                'easy-https-redirection',
            )
            for plugin in ssl_forcing_plugins:
                check = subprocess.run(
                    ['docker', 'exec', wp_container,
                     'wp', 'plugin', 'is-active', plugin, '--allow-root'],
                    capture_output=True, timeout=15,
                )
                if check.returncode == 0:
                    subprocess.run(
                        ['docker', 'exec', wp_container,
                         'wp', 'plugin', 'deactivate', plugin, '--allow-root'],
                        capture_output=True, timeout=30,
                    )
                    log.info("url_replace: deactivated plugin %s", plugin)

            # 5. Force-disable WP-side https flags that survive a plugin
            # deactivation (constants stored in the DB / wp_options).
            for opt in ('force_ssl_admin', 'force_ssl_login'):
                subprocess.run(
                    ['docker', 'exec', wp_container,
                     'wp', 'option', 'update', opt, '0', '--allow-root'],
                    capture_output=True, timeout=15,
                )

            # 6. Elementor URL pass (serializes its own data structures
            # so wp search-replace doesn't always reach everything).
            plugin_check = subprocess.run(
                ['docker', 'exec', wp_container,
                 'wp', 'plugin', 'is-installed', 'elementor', '--allow-root'],
                capture_output=True, timeout=15,
            )
            if plugin_check.returncode == 0 and old_url != local_url:
                subprocess.run(
                    ['docker', 'exec', wp_container,
                     'wp', 'elementor', 'replace-urls', old_url, local_url,
                     '--force', '--allow-root'],
                    capture_output=True, timeout=300,
                )
        except Exception:  # noqa: BLE001
            log.exception("url_replace crashed for %s", project_name)

    @staticmethod
    def _run_search_replace(container: str, old: str, new: str) -> None:
        result = subprocess.run(
            ['docker', 'exec', container,
             'wp', 'search-replace', old, new,
             '--skip-columns=guid', '--allow-root'],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            log.warning("search-replace %s -> %s failed: %s",
                        old, new, result.stderr.strip()[:300])

    # ─── orchestrator ────────────────────────────────────────────────

    def import_database(self, project_name: str, file_path: str) -> Dict[str, Any]:
        """Run the full import pipeline. Returns a result dict.

        Steps (emitted as Socket.IO ``import_progress`` events):
            0-5   init / decompress
            5-10  analyze
            10-15 prefix adapt
            15-30 backup current DB
            30-35 drop + recreate
            35-90 stream into mysql
            90-95 wp-cli search-replace
            95-100 cleanup
        """
        start = time.time()
        maintenance_file = self.enable_maintenance_mode(project_name)
        prepared_sql: Optional[str] = None
        adapted_sql: Optional[str] = None
        backup_path: Optional[str] = None
        original_memory: Optional[_MemoryState] = None
        info_for_finally: Optional[ContainerInfo] = None

        try:
            wp_logger.log_database_operation(
                'fast_import', project_name, True,
                f"Début fast import: {file_path}", file_path=file_path,
            )
            self._emit_progress(project_name, 0, "Initialisation de l'import…", 'starting')

            # 1. Decompress if needed.
            prepared_sql = self._prepare_sql_file(file_path)
            if not prepared_sql:
                self._emit_progress(project_name, 0, "Fichier SQL introuvable / non supporté", 'error')
                return {'success': False, 'error': 'Impossible de préparer le fichier SQL'}

            # 2. Analyze (bounded).
            self._emit_progress(project_name, 5, "Analyse du fichier SQL…", 'analyzing')
            analysis = self._stream_analyze_sql(prepared_sql)
            size_mb = analysis['file_size_mb']
            file_size = analysis['file_size']
            self._emit_progress(
                project_name, 10,
                f"Fichier analysé: {size_mb:.1f} MB, {analysis['table_count']} tables détectées",
                'analyzed',
            )

            # 3. Prefix adapt (streamed).
            self._emit_progress(project_name, 12, "Adaptation du préfixe de table…", 'processing')
            adapted_sql = self._stream_adapt_prefix(prepared_sql, project_name)

            # 4. Container info + connectivity.
            info = self.get_container_mysql_info(project_name)
            info_for_finally = info
            ping = subprocess.run(
                ['docker', 'exec', info.container, 'mysqladmin',
                 '-h', 'localhost', '-u', info.user, f'-p{info.password}', 'ping'],
                capture_output=True, text=True, timeout=15,
            )
            if ping.returncode != 0:
                self._emit_progress(project_name, 0,
                                    f"MySQL inaccessible: {ping.stderr.strip()}",
                                    'error')
                return {'success': False, 'error': f'MySQL inaccessible: {ping.stderr.strip()}'}

            # 4b. Bump the container's memory limit for the duration of
            # the import. A 512 MB-limited mysql container routinely
            # gets OOM-killed mid-import on WP dumps > 100 MB (Elementor
            # blobs alone can push the buffer pool past the cap). We
            # temporarily raise to 2 GiB and restore in the finally
            # block.
            original_memory = self._bump_memory_for_import(info, project_name)

            # 5. Backup the current DB before we drop it.
            self._emit_progress(project_name, 18, "Sauvegarde de la base actuelle…", 'processing')
            backup_path = self._backup_current_db(project_name, info)
            if backup_path:
                self._emit_progress(
                    project_name, 28,
                    f"Backup: {os.path.basename(backup_path)}",
                    'processing',
                )

            # 6. Drop + recreate.
            self._emit_progress(project_name, 30, "Suppression / recréation de la base…", 'dropping')
            if not self._recreate_database(info):
                msg = "Impossible de recréer la base. Vérifie le mot de passe root MySQL."
                if backup_path:
                    msg += f" Backup préservé: {backup_path}"
                self._emit_progress(project_name, 0, msg, 'error')
                return {'success': False, 'error': msg}

            # 7. Stream the import.
            self._emit_progress(project_name, 35, "Démarrage de l'import…", 'importing')
            result = self._import_sql_stream(project_name, adapted_sql, info, file_size)

            if not result['success']:
                err = result.get('error', 'Import mysql échoué')
                # Keep the raw mysql stderr in the server log; only
                # send the first line to the UI so the toast stays
                # readable.
                log.error("import mysql error for %s:\n%s", project_name, err)
                bytes_sent = result.get('bytes_sent', 0) or 0
                head = err.splitlines()[0] if err else 'unknown'
                summary = (
                    f"MySQL a rejeté l'import ({head[:200]}). "
                    f"{bytes_sent // (1024*1024)} MB envoyés."
                )
                if backup_path:
                    summary += f" Backup conservé: {backup_path}"
                self._emit_progress(project_name, 0, summary, 'error')
                wp_logger.log_database_operation(
                    'fast_import', project_name, False,
                    f"Fast import échoué: {err}",
                    file_path=file_path,
                )
                return {'success': False, 'error': summary, 'mysql_stderr': err}

            # 8. wp-cli URL rewrite.
            self._emit_progress(project_name, 93, "Remplacement des URLs (wp-cli)…", 'replacing_urls')
            self._perform_url_replacement(project_name)

            duration = time.time() - start
            speed = size_mb / duration if duration > 0 else 0
            wp_logger.log_database_operation(
                'fast_import', project_name, True,
                f"Fast import terminé ({speed:.2f} MB/s)",
                file_path=file_path,
                duration=f"{duration:.2f}s",
                file_size=f"{size_mb:.2f} MB",
                tables_count=analysis['table_count'],
            )
            self._emit_progress(project_name, 100, "Import terminé avec succès !", 'completed')
            return {
                'success': True,
                'method': 'MySQL stdin pipe',
                'speed': f"{speed:.2f} MB/s",
                'duration': f"{duration:.2f}s",
                'file_size': f"{size_mb:.2f} MB",
                'tables_imported': analysis['table_count'],
                'backup_path': backup_path,
            }

        except Exception as exc:  # noqa: BLE001
            log.exception("import_database crashed for %s", project_name)
            msg = f"Erreur critique: {exc}"
            if backup_path:
                msg += f" — backup: {backup_path}"
            self._emit_progress(project_name, 0, msg, 'error')
            wp_logger.log_database_operation(
                'fast_import', project_name, False,
                f"Exception: {exc}",
                file_path=file_path,
            )
            return {'success': False, 'error': msg}
        finally:
            # Remove the adapted tmp (if different from prepared) and the
            # prepared tmp (if different from the original).
            for cleanup in (adapted_sql, prepared_sql):
                if (cleanup and cleanup != file_path
                        and cleanup.startswith(tempfile.gettempdir())
                        and os.path.exists(cleanup)):
                    try:
                        os.remove(cleanup)
                    except OSError:
                        log.warning("cleanup: failed to remove %s", cleanup)
            # Restore the container's original memory limits regardless
            # of how we got here.
            if info_for_finally is not None and original_memory is not None:
                self._restore_memory(info_for_finally, original_memory)
            self.disable_maintenance_mode(maintenance_file or project_name)

    # ─── misc helpers kept for back-compat ───────────────────────────

    def estimate_import_time(self, file_size_mb: float) -> str:
        """Rough ETA based on observed ~75 MB/s on SSD-backed setups."""
        seconds = file_size_mb / 75
        if seconds < 60:
            return f"~{int(seconds)}s"
        if seconds < 3600:
            return f"~{int(seconds / 60)}min"
        return f"~{int(seconds / 3600)}h"
