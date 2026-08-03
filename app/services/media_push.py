"""
Media push — sync the dev ``wp-content/uploads`` tree to a remote site.

Deliberately **additive**: files are created and updated, never deleted
remotely. Media uploaded straight onto staging (or produced there by a
plugin) therefore survive a push — which is what the project's own
``.gitignore`` asks for when it excludes ``/uploads/`` as "synchronisés
séparément, jamais écrasés sur le staging".

The transfer runs over the same fingerprint-pinned paramiko connection
as the rest of the deploy stack rather than shelling out to rsync: that
keeps the host-key pinning intact and avoids writing the server's
private key to disk just to hand it to ``ssh -i``. Only the differing
files cross the wire — both sides are listed first and compared on
(size, mtime), which is the same heuristic rsync uses by default.
"""
from __future__ import annotations

import logging
import os
import stat
from typing import Callable, Dict, List, Tuple

from app.services.push_common import (
    PushError,
    container_name,
    human_size,
    parse_kv,
    remote_capture,
)

log = logging.getLogger(__name__)

LIST_TIMEOUT = 600
UPLOAD_TIMEOUT = 7200

# Generated artefacts that must NOT travel: they embed absolute URLs of
# the environment that produced them, and every one of them is rebuilt
# on demand by the plugin that owns it. Copying Elementor's CSS cache in
# particular would inject dev URLs straight back into staging's assets —
# undoing the URL rewriting the database push just did.
_EXCLUDED_PREFIXES = (
    "elementor/css/",
    "cache/",
    "wp-rocket-config/",
    "et-cache/",
)
_EXCLUDED_NAMES = (".DS_Store", "Thumbs.db")

# mtime comparison tolerance. FAT/SMB-backed volumes and some SFTP
# servers round timestamps to the nearest second (or two).
_MTIME_SLACK = 2.0


class MediaPushError(PushError):
    """Any recoverable failure of the media push pipeline."""


# Locates the remote uploads directory from the configured deploy path.
# The deploy path is often wp-content itself (that is how the launcher's
# git deployments are set up), otherwise we walk up to wp-config.php.
_SCRIPT_RESOLVE_UPLOADS = r"""
set -u
DEPLOY_PATH="$1"

if [ "$(basename "$DEPLOY_PATH")" = "wp-content" ]; then
  printf 'UPLOADS=%s\n' "$DEPLOY_PATH/uploads"
  exit 0
fi

d="$DEPLOY_PATH"
CFG=""
i=0
while [ "$i" -lt 6 ]; do
  if [ -f "$d/wp-config.php" ]; then CFG="$d/wp-config.php"; break; fi
  p=$(dirname "$d")
  if [ "$p" = "$d" ]; then break; fi
  d="$p"
  i=$((i + 1))
done
if [ -z "$CFG" ]; then
  printf 'ERROR: wp-config.php not found walking up from %s\n' "$DEPLOY_PATH" >&2
  exit 3
fi
printf 'UPLOADS=%s/wp-content/uploads\n' "$(dirname "$CFG")"
exit 0
"""

_SCRIPT_LIST_REMOTE = r"""
set -u
UPLOADS="$1"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

if [ ! -d "$UPLOADS" ]; then
  # First push to a fresh site: nothing to compare against.
  printf 'MISSING=1\n'
  printf '__FILES__\n'
  exit 0
fi
[ -w "$UPLOADS" ] || fail "the uploads directory is not writable by this SSH user: $UPLOADS" 4
printf 'MISSING=0\n'
printf '__FILES__\n'
cd "$UPLOADS" || fail "cannot enter $UPLOADS" 4
# GNU find prints size/mtime/path in one pass; fall back to stat(1) for
# the rare host without -printf.
if find . -maxdepth 0 -printf '' > /dev/null 2>&1; then
  find . -type f -printf '%s\t%T@\t%P\n'
else
  find . -type f -exec stat -c '%s	%Y	%n' {} + | sed 's|\t\./|\t|'
fi
exit 0
"""


def _iter_local_files(root: str):
    """Yield ``(relpath, size, mtime)`` for every syncable file."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        # Prune excluded subtrees so we don't even walk them.
        if rel_dir and _is_excluded(rel_dir + "/"):
            dirnames[:] = []
            continue
        for name in filenames:
            if name in _EXCLUDED_NAMES:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if _is_excluded(rel):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue  # skip symlinks and specials
            yield rel, st.st_size, st.st_mtime


def _is_excluded(rel: str) -> bool:
    return any(rel.startswith(p) for p in _EXCLUDED_PREFIXES)


def _parse_remote_listing(text: str) -> Tuple[bool, Dict[str, Tuple[int, float]]]:
    """Split the remote script output into its header and file list."""
    head, _, body = text.partition("__FILES__\n")
    missing = parse_kv(head).get("MISSING") == "1"
    files: Dict[str, Tuple[int, float]] = {}
    for line in body.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        size_s, mtime_s, rel = parts
        try:
            files[rel] = (int(size_s), float(mtime_s))
        except ValueError:
            continue
    return missing, files


def diff_trees(
    local_files: List[Tuple[str, int, float]],
    remote_files: Dict[str, Tuple[int, float]],
) -> Tuple[List[Tuple[str, int]], int]:
    """Which local files need sending, and how many are brand new.

    Same heuristic as rsync's default: a file is stale when its size
    differs or the local copy is newer. Never reports remote-only files
    — this sync only ever adds.
    """
    todo: List[Tuple[str, int]] = []
    new_count = 0
    for rel, size, mtime in local_files:
        remote = remote_files.get(rel)
        if remote is None:
            todo.append((rel, size))
            new_count += 1
        elif remote[0] != size or mtime > remote[1] + _MTIME_SLACK:
            todo.append((rel, size))
    return todo, new_count


def resolve_remote_uploads(client, deploy_path: str) -> str:
    """Ask the remote where its uploads directory lives."""
    code, out, err = remote_capture(
        client, _SCRIPT_RESOLVE_UPLOADS, [deploy_path], 60
    )
    if code != 0:
        detail = (err or out).strip().splitlines()
        raise MediaPushError(
            "Could not locate the remote uploads directory: "
            + (detail[-1] if detail else f"exit {code}")
        )
    uploads = parse_kv(out).get("UPLOADS", "")
    if not uploads.startswith("/"):
        raise MediaPushError(f"Unusable remote uploads path: {uploads!r}")
    return uploads


def push(
    *,
    emit: Callable[..., None],
    cancel_check: Callable[[], None],
    client,
    project_name: str,
    projects_folder: str,
    remote_uploads: str,
) -> Dict[str, str]:
    """Sync dev uploads → ``remote_uploads``. Never deletes remotely."""
    local_root = os.path.join(projects_folder, project_name, "wp-content", "uploads")
    container_name(project_name, "wordpress")  # validates the project slug

    if not os.path.isdir(local_root):
        raise MediaPushError(f"No local uploads directory: {local_root}")

    # ── 1. inventory both sides ──────────────────────────────────────
    cancel_check()
    emit("== 1/3 Listing both media libraries")
    local_files = list(_iter_local_files(local_root))
    local_bytes = sum(f[1] for f in local_files)
    emit(f"   dev   : {len(local_files)} files ({human_size(local_bytes)})")

    code, out, err = remote_capture(
        client, _SCRIPT_LIST_REMOTE, [remote_uploads], LIST_TIMEOUT
    )
    if code != 0:
        detail = (err or out).strip().splitlines()
        raise MediaPushError(
            "Could not list the remote media: " + (detail[-1] if detail else f"exit {code}")
        )
    remote_missing, remote_files = _parse_remote_listing(out)
    if remote_missing:
        emit(f"   remote: {remote_uploads} does not exist yet — it will be created")
    else:
        remote_bytes = sum(v[0] for v in remote_files.values())
        emit(f"   remote: {len(remote_files)} files ({human_size(remote_bytes)})")

    # ── 2. diff ──────────────────────────────────────────────────────
    cancel_check()
    todo, new_count = diff_trees(local_files, remote_files)
    updated = len(todo) - new_count
    only_remote = len(remote_files) - (len(local_files) - new_count)
    emit(
        f"== 2/3 {len(todo)} file(s) to send — {new_count} new, {updated} updated"
    )
    if only_remote > 0:
        emit(f"   {only_remote} file(s) exist only on the remote — kept (additive sync)")
    if not todo:
        emit("== 3/3 Nothing to transfer, the remote media is already up to date")
        return {"sent": "0", "bytes": "0", "kept_remote": str(max(only_remote, 0))}

    # ── 3. transfer ──────────────────────────────────────────────────
    total = sum(size for _, size in todo)
    emit(f"== 3/3 Uploading {human_size(total)}")
    sent_bytes = 0
    sent_files = 0
    failures: List[str] = []
    made_dirs = {""}
    next_report = 0

    sftp = None
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(UPLOAD_TIMEOUT)
        _ensure_remote_dir(sftp, remote_uploads, made_dirs)

        for rel, size in todo:
            cancel_check()
            rel_dir = os.path.dirname(rel)
            if rel_dir and rel_dir not in made_dirs:
                _ensure_remote_dir(sftp, f"{remote_uploads}/{rel_dir}", made_dirs)
            local_path = os.path.join(local_root, rel.replace("/", os.sep))
            remote_path = f"{remote_uploads}/{rel}"
            try:
                sftp.put(local_path, remote_path, confirm=True)
                # Carry the mtime across so the next run's diff skips it.
                st = os.stat(local_path)
                sftp.utime(remote_path, (st.st_atime, st.st_mtime))
                sent_files += 1
                sent_bytes += size
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{rel}: {exc}")
                # Retirer le fichier partiel : le diff du prochain run compare
                # taille et mtime, un tronqué pourrait passer pour synchronisé.
                try:
                    sftp.remove(remote_path)
                except Exception:  # noqa: BLE001
                    pass
                if len(failures) > 25:
                    raise MediaPushError(
                        "Too many upload failures — aborting. Last error: " + failures[-1]
                    ) from exc
                continue

            if total and sent_bytes >= next_report:
                pct = int(sent_bytes * 100 / total)
                emit(f"   {pct}% — {sent_files}/{len(todo)} files ({human_size(sent_bytes)})")
                next_report = sent_bytes + max(total // 5, 1)
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:  # noqa: BLE001
                pass

    for line in failures:
        emit(f"   [skipped] {line}", "stderr")

    if failures:
        # Un fichier non transféré laisse la médiathèque distante incomplète.
        # Remonter l'échec plutôt que de conclure en « success » : sinon un
        # run à moitié synchronisé s'affiche en vert et personne ne rejoue.
        emit(f"== Done with {len(failures)} skipped file(s)", "stderr")
        raise MediaPushError(
            f"{len(failures)} file(s) could not be uploaded "
            f"({sent_files} sent). First error: {failures[0]}"
        )

    emit(f"== Done — {sent_files} file(s) sent ({human_size(sent_bytes)})")
    emit("== No remote file was deleted (additive sync)")

    return {
        "sent": str(sent_files),
        "bytes": str(sent_bytes),
        "skipped": str(len(failures)),
        "kept_remote": str(max(only_remote, 0)),
    }


def _ensure_remote_dir(sftp, path: str, made: set) -> None:
    """mkdir -p over SFTP, remembering what already exists."""
    if path in made:
        return
    try:
        sftp.stat(path)
        made.add(path)
        return
    except IOError:
        pass
    parent = os.path.dirname(path.rstrip("/"))
    if parent and parent not in made and parent != "/":
        _ensure_remote_dir(sftp, parent, made)
    try:
        sftp.mkdir(path)
    except IOError as exc:
        # A concurrent push (or a race with the web server) may have
        # created it between our stat and mkdir.
        try:
            sftp.stat(path)
        except IOError:
            raise MediaPushError(f"Cannot create the remote directory {path}: {exc}") from exc
    made.add(path)
