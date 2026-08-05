"""
Shared plumbing for the dev → remote push pipelines (database, media).

Both pushes talk to the same two worlds: local Docker containers on the
launcher side, and an already-authenticated paramiko client on the
remote side. The helpers below are the parts neither pipeline should
reimplement — notably ``remote_capture``, which feeds a bash script over
stdin so credentials never land in a remote process argv.
"""
from __future__ import annotations

import logging
import re
import shlex
import subprocess
from typing import Dict, Tuple

log = logging.getLogger(__name__)

# Le premier caractère est alphanumérique : sans ça, "." et ".." passent, et
# le nom est joint à des chemins (projects_folder/<name>/wp-content/uploads)
# autant qu'interpolé dans des noms de conteneurs.
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{0,255}$")


class PushError(RuntimeError):
    """A recoverable failure surfaced verbatim to the user."""


def container_name(project_name: str, service: str) -> str:
    if not PROJECT_RE.match(project_name or ""):
        raise PushError(f"Invalid project name: {project_name!r}")
    # La base fait exception : un projet migré sur le serveur MySQL partagé
    # n'a plus de conteneur mysql à lui, et `db_target` sait lequel porte
    # réellement son schéma.
    if service == "mysql":
        from app.utils.db_target import db_target
        return db_target(project_name).container
    return f"{project_name}_{service}_1"


def run_local(args, timeout: int) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"Local command timed out after {timeout}s: {args[0]}"
    except OSError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def container_running(name: str) -> bool:
    code, out, _ = run_local(
        ["docker", "inspect", "-f", "{{.State.Running}}", name], timeout=20
    )
    return code == 0 and out.strip() == "true"


def human_size(num: int) -> str:
    step = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if step < 1024 or unit == "GB":
            return f"{step:.1f} {unit}" if unit != "B" else f"{int(step)} B"
        step /= 1024
    return f"{num} B"


def remote_capture(client, script: str, args, timeout: int) -> Tuple[int, str, str]:
    """Run a bash script (fed on stdin, so nothing lands in argv) and
    capture its output."""
    cmd = "bash -s -- " + " ".join(shlex.quote(str(a)) for a in args)
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
    channel = stdout.channel
    channel.settimeout(timeout)
    try:
        stdin.write(script)
        stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = channel.recv_exit_status()
    finally:
        try:
            channel.close()
        except Exception:  # noqa: BLE001
            pass
    return code, out, err


def parse_kv(text: str) -> Dict[str, str]:
    """Collect ``KEY=value`` lines (upper-case keys only) from output."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if key.isupper():
                out[key] = value.strip()
    return out


# Removes the temp files a pipeline left on the remote host. Never
# touches a backup.
SCRIPT_CLEANUP = r"""
set -u
for f in "$@"; do
  [ -n "$f" ] && rm -f "$f"
done
exit 0
"""
