"""
DB push — ship the local dev WordPress database to a remote server.

The pipeline, in order:

  1. read the dev site URL + table prefix from the project's WordPress
     container (wp-cli);
  2. inspect the remote host over the already-open SSH channel: locate
     ``wp-config.php`` by walking *up* from the deploy path, parse its
     DB credentials with PHP (sed fallback), write them into a 0600
     MySQL defaults-file **on the remote** and read back the remote
     siteurl / home / table prefix. Credentials never travel back to
     the launcher and never appear in a process argv;
  3. export the dev database through ``wp search-replace --export`` so
     the dev URL is rewritten to the remote URL *in the dump* — the dev
     database itself is never modified and PHP-serialized payloads
     (Elementor, widgets, options) keep valid string lengths;
  4. upload the gzipped dump over SFTP;
  5. remotely: back up the target database, drop the prefixed tables,
     import the dump;
  6. best-effort second pass with the remote wp-cli (if present) for
     leftover scheme-less occurrences of the dev host, then a cache
     flush.

Everything user-visible is streamed to the caller's ``emit`` callback so
the existing deployment log modal renders it live.
"""
from __future__ import annotations

import gzip
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

log = logging.getLogger(__name__)

# Wall-clock budgets, per phase (seconds).
INSPECT_TIMEOUT = 180
EXPORT_TIMEOUT = 3600
UPLOAD_TIMEOUT = 3600
IMPORT_TIMEOUT = 3600
POST_TIMEOUT = 900

from app.services.push_common import (  # noqa: F401  (re-exported)
    PushError,
    SCRIPT_CLEANUP as _SCRIPT_CLEANUP,
    container_name as _container,
    container_running as _container_running,
    human_size as _human_size,
    parse_kv as _parse_kv,
    remote_capture as _remote_capture,
    run_local as _run_local,
)

_PREFIX_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_$-]{1,64}$")
_CHARSET_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{0,255}$")


class DbPushError(PushError):
    """Any recoverable failure of the DB push pipeline."""


def _wp(project_name: str, wp_args, timeout: int = 120) -> Tuple[int, str, str]:
    """Run wp-cli inside the project's WordPress container."""
    return _run_local(
        ["docker", "exec", _container(project_name, "wordpress"), "wp"]
        + list(wp_args)
        + ["--allow-root", "--skip-plugins", "--skip-themes", "--skip-packages"],
        timeout=timeout,
    )


def _normalize_url(url: str) -> str:
    """Drop the trailing slash a site URL sometimes carries.

    A remote ``siteurl`` stored as ``https://site.tld/`` would otherwise
    be substituted for a slash-less dev URL and turn every asset path
    into ``https://site.tld//wp-content/…``.
    """
    return (url or "").strip().rstrip("/")


def _host_of(url: str) -> str:
    """``https://example.com/sub`` → ``example.com/sub`` (scheme stripped)."""
    return re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", (url or "").strip()).rstrip("/")


# ─── remote scripts ──────────────────────────────────────────────────

# Reads wp-config.php and writes a 0600 MySQL defaults-file next to it in
# /tmp. Emits KEY=value lines on stdout — never the password.
_PHP_PARSER = r"""<?php
$cfg = $argv[1];
$cnf = $argv[2];
$src = @file_get_contents($cfg);
if ($src === false) { fwrite(STDERR, "cannot read wp-config.php\n"); exit(5); }
// Drop the bootstrap require so including the config doesn't boot WordPress.
$src = preg_replace('/^[^\S\n]*(require|include)(_once)?[^;]*wp-settings\.php[^;]*;/mi', '', $src);
ob_start();
eval('?>' . $src);
ob_end_clean();
if (!defined('DB_NAME') || !defined('DB_USER')) {
    fwrite(STDERR, "DB constants not found in wp-config.php\n");
    exit(5);
}
$host = defined('DB_HOST') ? DB_HOST : 'localhost';
$port = '';
$socket = '';
if (strpos($host, ':') !== false) {
    list($host, $tail) = explode(':', $host, 2);
    if (ctype_digit($tail)) { $port = $tail; } else { $socket = $tail; }
}
$q = function ($v) { return '"' . addcslashes((string) $v, "\"\\") . '"'; };
$out = "[client]\n";
$out .= 'user=' . $q(DB_USER) . "\n";
$out .= 'password=' . $q(DB_PASSWORD) . "\n";
if ($host !== '') { $out .= 'host=' . $q($host) . "\n"; }
if ($port !== '') { $out .= 'port=' . $port . "\n"; }
if ($socket !== '') { $out .= 'socket=' . $q($socket) . "\n"; }
$old = umask(0077);
$ok = @file_put_contents($cnf, $out);
umask($old);
if ($ok === false) { fwrite(STDERR, "cannot write the mysql defaults-file\n"); exit(5); }
@chmod($cnf, 0600);
$prefix = isset($table_prefix) && $table_prefix !== '' ? $table_prefix : 'wp_';
echo 'DB_NAME=' . DB_NAME . "\n";
echo 'DB_HOST=' . DB_HOST . "\n";
echo 'PREFIX=' . $prefix . "\n";
"""

_SCRIPT_INSPECT = r"""
set -u
DEPLOY_PATH="$1"
TOKEN="$2"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

# Returns the RESOLVED path, not the candidate name: a bare `wp` works
# when executed directly but not when handed to a PHP interpreter,
# which does no PATH lookup ("Could not open input file: wp").
find_bin() {
  for c in "$@"; do
    p=$(command -v "$c" 2>/dev/null) && [ -n "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

# 1) locate wp-config.php by walking up from the deploy path
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
[ -n "$CFG" ] || fail "wp-config.php not found walking up from $DEPLOY_PATH" 3
WPROOT=$(dirname "$CFG")

MYSQL=$(find_bin mariadb mysql) || fail "no mysql client found on the remote host" 4
MYSQLDUMP=$(find_bin mariadb-dump mysqldump) || fail "no mysqldump found on the remote host" 4
PHPBIN=$(find_bin php php8.4 php8.3 php8.2 php8.1 php8.0 php7.4 /usr/local/bin/php) || PHPBIN=""
if [ -z "$PHPBIN" ]; then
  # Managed hosts keep PHP out of the deploy user's PATH: Plesk and
  # cPanel both install it under a versioned prefix instead.
  for c in /opt/plesk/php/*/bin/php /usr/local/php*/bin/php \
           /opt/cpanel/ea-php*/root/usr/bin/php; do
    if [ -x "$c" ]; then PHPBIN="$c"; break; fi
  done
fi
WPCLI=$(find_bin wp wp-cli /usr/local/bin/wp) || WPCLI=""

# A `wp` on PATH is not proof of a usable wp-cli: it is normally a phar
# with a `#!/usr/bin/env php` shebang, which dies when PHP is not on the
# PATH — exactly the Plesk layout above. Probe it, and fall back to
# invoking the phar through the interpreter we just located.
WPCLI_VIA_PHP=0
if [ -n "$WPCLI" ]; then
  if "$WPCLI" --version > /dev/null 2>&1 < /dev/null; then
    :
  elif [ -n "$PHPBIN" ] && "$PHPBIN" "$WPCLI" --version > /dev/null 2>&1 < /dev/null; then
    WPCLI_VIA_PHP=1
  else
    WPCLI=""
  fi
fi

CNF="/tmp/.wplp-${TOKEN}.cnf"
PHPSCRIPT="/tmp/.wplp-${TOKEN}.php"
umask 077

DB_NAME=""
DB_HOST=""
PREFIX=""

if [ -n "$PHPBIN" ]; then
  cat > "$PHPSCRIPT" <<'WPLP_PHP_EOF'
__PHP_PARSER__
WPLP_PHP_EOF
  OUT=$("$PHPBIN" "$PHPSCRIPT" "$CFG" "$CNF" < /dev/null) || OUT=""
  rm -f "$PHPSCRIPT"
  if [ -n "$OUT" ]; then
    DB_NAME=$(printf '%s\n' "$OUT" | sed -n 's/^DB_NAME=//p' | head -n1)
    DB_HOST=$(printf '%s\n' "$OUT" | sed -n 's/^DB_HOST=//p' | head -n1)
    PREFIX=$(printf '%s\n' "$OUT" | sed -n 's/^PREFIX=//p' | head -n1)
  fi
fi

if [ -z "$DB_NAME" ]; then
  # Fallback: plain text extraction (no PHP available, or eval refused).
  grab() {
    sed -n "s/^[[:space:]]*define([[:space:]]*['\"]$1['\"][[:space:]]*,[[:space:]]*['\"]\(.*\)['\"][[:space:]]*)[[:space:]]*;.*/\1/p" "$CFG" | head -n1
  }
  DB_NAME=$(grab DB_NAME)
  DB_USER=$(grab DB_USER)
  DB_PASSWORD=$(grab DB_PASSWORD)
  DB_HOST=$(grab DB_HOST)
  PREFIX=$(sed -n "s/^[[:space:]]*\$table_prefix[[:space:]]*=[[:space:]]*['\"]\(.*\)['\"][[:space:]]*;.*/\1/p" "$CFG" | head -n1)
  [ -n "$DB_NAME" ] || fail "could not read the database credentials from $CFG" 5
  HOST_ONLY="$DB_HOST"
  PORT_ONLY=""
  SOCKET_ONLY=""
  case "$DB_HOST" in
    *:*)
      HOST_ONLY=${DB_HOST%%:*}
      TAIL=${DB_HOST#*:}
      case "$TAIL" in
        ''|*[!0-9]*) SOCKET_ONLY="$TAIL" ;;
        *) PORT_ONLY="$TAIL" ;;
      esac
      ;;
  esac
  {
    printf '[client]\n'
    printf 'user="%s"\n' "$DB_USER"
    printf 'password="%s"\n' "$DB_PASSWORD"
    [ -n "$HOST_ONLY" ] && printf 'host="%s"\n' "$HOST_ONLY"
    [ -n "$PORT_ONLY" ] && printf 'port=%s\n' "$PORT_ONLY"
    [ -n "$SOCKET_ONLY" ] && printf 'socket="%s"\n' "$SOCKET_ONLY"
  } > "$CNF"
  chmod 600 "$CNF"
fi

[ -n "$PREFIX" ] || PREFIX="wp_"

# Recent MariaDB clients (11.4+) verify the server certificate by
# default, which fails against the self-signed cert most managed hosts
# ship — even though WordPress itself connects happily. Probe for the
# lightest option that gets us through, and hand it to the import phase.
try_query() {
  "$MYSQL" --defaults-file="$CNF" $1 -N -B -e "SELECT 1" "$DB_NAME" < /dev/null > /dev/null 2>&1
}
MYSQL_OPT=""
if ! try_query ""; then
  for opt in "--ssl-verify-server-cert=0" "--ssl-mode=PREFERRED" "--skip-ssl"; do
    if try_query "$opt"; then MYSQL_OPT="$opt"; break; fi
  done
  [ -n "$MYSQL_OPT" ] || fail "cannot connect to the remote database — check the wp-config credentials" 6
fi
# mysqldump must accept the same option, or the pre-import backup would
# fail after we have already started.
if [ -n "$MYSQL_OPT" ]; then
  "$MYSQLDUMP" --defaults-file="$CNF" $MYSQL_OPT --no-data --no-create-info \
    --skip-triggers "$DB_NAME" < /dev/null > /dev/null 2>&1 \
    || fail "the remote mysqldump rejects the required TLS option ($MYSQL_OPT)" 7
fi

SITEURL=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
  "SELECT option_value FROM \`${PREFIX}options\` WHERE option_name='siteurl' LIMIT 1" \
  "$DB_NAME" < /dev/null) || fail "cannot read siteurl — is ${PREFIX}options the right table?" 6
HOMEURL=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
  "SELECT option_value FROM \`${PREFIX}options\` WHERE option_name='home' LIMIT 1" \
  "$DB_NAME" < /dev/null) || HOMEURL=""

printf 'WPROOT=%s\n' "$WPROOT"
printf 'CFG=%s\n' "$CFG"
printf 'CNF=%s\n' "$CNF"
printf 'DB_NAME=%s\n' "$DB_NAME"
printf 'DB_HOST=%s\n' "$DB_HOST"
printf 'PREFIX=%s\n' "$PREFIX"
printf 'SITEURL=%s\n' "$SITEURL"
printf 'HOMEURL=%s\n' "$HOMEURL"
printf 'MYSQL=%s\n' "$MYSQL"
printf 'MYSQLDUMP=%s\n' "$MYSQLDUMP"
printf 'WPCLI=%s\n' "$WPCLI"
printf 'WPCLI_VIA_PHP=%s\n' "$WPCLI_VIA_PHP"
printf 'PHPBIN=%s\n' "$PHPBIN"
printf 'MYSQL_OPT=%s\n' "$MYSQL_OPT"
printf 'HOME=%s\n' "${HOME:-}"
""".replace(
    "__PHP_PARSER__", _PHP_PARSER.rstrip("\n")
)

_SCRIPT_IMPORT = r"""
set -u
set -o pipefail
CNF="$1"
DB="$2"
PREFIX_LIKE="$3"
GZ="$4"
BAK="$5"
MYSQL="$6"
MYSQLDUMP="$7"
CHARSET="$8"
# May be empty; deliberately left unquoted at the call sites so an empty
# value expands to no argument at all.
MYSQL_OPT="${9:-}"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

umask 077
BAKDIR=$(dirname "$BAK")
mkdir -p "$BAKDIR" 2>/dev/null || { BAKDIR="/tmp"; BAK="/tmp/$(basename "$BAK")"; }
[ -w "$BAKDIR" ] || { BAKDIR="/tmp"; BAK="/tmp/$(basename "$BAK")"; }
printf -- '-- backing up the remote database to %s\n' "$BAK"
"$MYSQLDUMP" --defaults-file="$CNF" $MYSQL_OPT --single-transaction --quick --no-tablespaces \
  --routines --triggers "$DB" < /dev/null | gzip -c > "$BAK" || fail "remote backup failed" 10
printf -- '-- backup written (%s)\n' "$(ls -lh "$BAK" | awk '{print $5}')"

# Keep the 5 most recent backups of THIS database, drop the rest.
if [ "$BAKDIR" != "/tmp" ]; then
  ls -1t "$BAKDIR/$DB"-*.sql.gz 2>/dev/null | tail -n +6 | while IFS= read -r old; do
    rm -f "$old" && printf -- '-- pruned old backup %s\n' "$(basename "$old")"
  done
fi

printf -- '-- listing the tables to replace (prefix %s)\n' "$PREFIX_LIKE"
DROPS=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
  "SELECT CONCAT('DROP TABLE IF EXISTS \`', TABLE_NAME, '\`;') FROM information_schema.TABLES \
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME LIKE '${PREFIX_LIKE}%'" \
  "$DB" < /dev/null) || fail "could not list the remote tables" 11

if [ -n "$DROPS" ]; then
  printf -- '-- dropping %s table(s)\n' "$(printf '%s\n' "$DROPS" | wc -l | tr -d ' ')"
  printf 'SET FOREIGN_KEY_CHECKS=0;\n%s\nSET FOREIGN_KEY_CHECKS=1;\n' "$DROPS" \
    | "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT "$DB" || fail "could not drop the remote tables" 12
else
  printf -- '-- no existing table with this prefix\n'
fi

# wp-cli's --export writes a bare dump: no charset line and no SQL-mode
# preamble, unlike mysqldump. Both have to be supplied here or the
# import breaks on a stricter remote server — a client defaulting to
# latin1 mojibakes accents, and NO_ZERO_DATE rejects WordPress's
# `DEFAULT '0000-00-00 00:00:00'` columns outright.
printf -- '-- importing the dump (charset %s)\n' "$CHARSET"
if ! {
  printf 'SET SQL_MODE="NO_AUTO_VALUE_ON_ZERO";\n'
  printf 'SET FOREIGN_KEY_CHECKS=0;\n'
  printf 'SET UNIQUE_CHECKS=0;\n'
  printf 'SET NAMES %s;\n' "$CHARSET"
  gunzip -c "$GZ"
} | "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT --default-character-set="$CHARSET" "$DB"; then
  # The tables were already dropped, so a half-finished import leaves the
  # site down. Roll straight back to the snapshot taken minutes ago
  # rather than leaving someone to do it by hand under pressure.
  printf -- '-- IMPORT FAILED — rolling back to the pre-import backup\n'
  if gunzip -c "$BAK" | "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT "$DB"; then
    printf -- '-- rollback done: the remote database is back to its previous state\n'
  else
    printf -- '-- ROLLBACK FAILED — restore manually with:\n'
    printf -- '--   gunzip -c %s | mysql %s\n' "$BAK" "$DB"
  fi
  fail "import failed" 13
fi
printf -- '-- import finished\n'

COUNT=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
  "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() \
   AND TABLE_NAME LIKE '${PREFIX_LIKE}%'" "$DB" < /dev/null) || COUNT="?"
printf -- '-- %s table(s) present after the import\n' "$COUNT"
"""

# Extra serialization-safe replacement passes, run through the remote's
# own wp-cli — or through the phar we uploaded when the host has none.
# `wp search-replace` takes a single pair per call, and a plain text
# substitution can't be used instead: these URLs live inside
# PHP-serialized payloads whose `s:<len>:` headers must be recomputed.
# Remaining args are consumed as OLD NEW pairs.
_SCRIPT_POST = r"""
set -u
WPCLI="$1"
PHPBIN="$2"
PHAR="$3"
WPROOT="$4"
VIA_PHP="$5"
shift 5

run_wp() {
  if [ -n "$WPCLI" ] && [ "$VIA_PHP" = "1" ]; then
    "$PHPBIN" "$WPCLI" "$@"
  elif [ -n "$WPCLI" ]; then
    "$WPCLI" "$@"
  else
    "$PHPBIN" "$PHAR" "$@"
  fi
}

if [ -z "$WPCLI" ] && { [ -z "$PHPBIN" ] || [ -z "$PHAR" ] || [ ! -f "$PHAR" ]; }; then
  printf -- '-- no usable wp-cli on the remote host: skipping the cleanup passes\n'
  printf -- '-- (the main URL was already rewritten inside the dump)\n'
  exit 0
fi
if [ -z "$WPCLI" ]; then
  printf -- '-- using the wp-cli copied from the dev container\n'
elif [ "$VIA_PHP" = "1" ]; then
  printf -- '-- running wp-cli through %s (php is not on the PATH)\n' "$PHPBIN"
fi

while [ "$#" -ge 2 ]; do
  OLD="$1"
  NEW="$2"
  shift 2
  if [ "$OLD" = "$NEW" ] || [ -z "$OLD" ]; then
    continue
  fi
  printf -- '-- pass: %s -> %s\n' "$OLD" "$NEW"
  run_wp --path="$WPROOT" search-replace "$OLD" "$NEW" \
    --all-tables-with-prefix --skip-columns=guid --precise --report-changed-only \
    --allow-root --skip-plugins --skip-themes --skip-packages 2>&1 \
    || printf -- '-- this pass failed (non blocking)\n'
done

if run_wp --path="$WPROOT" cache flush --allow-root --skip-plugins --skip-themes \
     --skip-packages > /dev/null 2>&1; then
  printf -- '-- object cache flushed\n'
else
  printf -- '-- cache flush skipped\n'
fi

# Elementor caches rendered markup, so a page keeps serving the URLs it
# was built with even after the database is corrected — images point at
# the dev host until this cache is dropped. The `elementor` command only
# exists when the plugin is loaded, so this call must NOT skip plugins.
if run_wp --path="$WPROOT" plugin is-active elementor --allow-root \
     --skip-plugins --skip-themes --skip-packages > /dev/null 2>&1; then
  if run_wp --path="$WPROOT" elementor flush-css --allow-root > /dev/null 2>&1; then
    printf -- '-- Elementor cache flushed\n'
  else
    printf -- '-- Elementor cache flush FAILED — clear it from the WP admin\n'
  fi
fi
exit 0
"""



# ─── pipeline ────────────────────────────────────────────────────────


def push(
    *,
    emit: Callable[..., None],
    run_streaming: Callable[..., int],
    cancel_check: Callable[[], None],
    client,
    project_name: str,
    deploy_path: str,
    token: str,
    work_dir: str,
) -> Dict[str, str]:
    """Run the whole dev → remote database push.

    ``run_streaming(script, args, timeout=…) -> exit_code`` is injected
    by the caller so remote output lands in the deployment log (and
    honours cancellation / the global time budget). ``cancel_check``
    raises the caller's cancellation exception when the user asked to
    stop — it is polled at every phase boundary, since the local export
    and the upload run outside the streaming loop that would otherwise
    notice.

    Returns a small summary dict. Raises :class:`DbPushError` on any
    failure the user can act on.
    """
    remote_cnf: Optional[str] = None
    remote_gz: Optional[str] = None
    remote_temp: list = []
    local_gz = os.path.join(work_dir, f"wplp-{token}.sql.gz")
    container_sql = f"/tmp/wplp-{token}.sql"
    wp_container = _container(project_name, "wordpress")

    try:
        # ── 1. dev side ──────────────────────────────────────────────
        cancel_check()
        emit("== 1/6 Reading the dev site")
        if not _container_running(wp_container):
            raise DbPushError(
                f"The WordPress container {wp_container} is not running — start the project first."
            )
        if not _container_running(_container(project_name, "mysql")):
            raise DbPushError(
                f"The MySQL container {_container(project_name, 'mysql')} is not running — start the project first."
            )

        code, out, err = _wp(project_name, ["option", "get", "siteurl"], timeout=90)
        dev_url = _normalize_url(out)
        if code != 0 or not dev_url:
            raise DbPushError(f"Could not read the dev siteurl: {err.strip() or out.strip()}")
        code, out, _ = _wp(project_name, ["config", "get", "table_prefix"], timeout=60)
        dev_prefix = out.strip() if code == 0 else ""
        if not _PREFIX_RE.match(dev_prefix or ""):
            dev_prefix = "wp_"
        code, out, _ = _wp(project_name, ["config", "get", "DB_CHARSET"], timeout=60)
        dev_charset = out.strip() if code == 0 else ""
        if not _CHARSET_RE.match(dev_charset or ""):
            dev_charset = "utf8mb4"
        emit(f"   dev siteurl   : {dev_url}")
        emit(f"   dev prefix    : {dev_prefix}")
        emit(f"   dev charset   : {dev_charset}")

        # ── 2. remote inspection ─────────────────────────────────────
        cancel_check()
        emit("== 2/6 Inspecting the remote host (wp-config.php)")
        code, out, err = _remote_capture(
            client, _SCRIPT_INSPECT, [deploy_path, token], INSPECT_TIMEOUT
        )
        if code != 0:
            detail = (err or out).strip().splitlines()
            raise DbPushError(
                "Remote inspection failed: " + (detail[-1] if detail else f"exit code {code}")
            )
        info = _parse_kv(out)
        remote_cnf = info.get("CNF") or None
        wp_root = info.get("WPROOT", "")
        db_name = info.get("DB_NAME", "")
        remote_prefix = info.get("PREFIX", "")
        remote_url = _normalize_url(info.get("SITEURL"))
        remote_home_url = _normalize_url(info.get("HOMEURL"))
        mysql_bin = info.get("MYSQL", "mysql")
        mysqldump_bin = info.get("MYSQLDUMP", "mysqldump")
        wpcli_bin = info.get("WPCLI", "")
        wpcli_via_php = info.get("WPCLI_VIA_PHP", "0")
        php_bin = info.get("PHPBIN", "")
        mysql_opt = info.get("MYSQL_OPT", "")
        remote_home = info.get("HOME", "")

        if not (remote_cnf and _PATH_RE.match(remote_cnf)):
            raise DbPushError("The remote host did not return a usable credentials file path.")
        if not _DB_NAME_RE.match(db_name or ""):
            raise DbPushError(f"Unusable remote database name: {db_name!r}")
        if not _PREFIX_RE.match(remote_prefix or ""):
            raise DbPushError(f"Unusable remote table prefix: {remote_prefix!r}")
        if not remote_url:
            raise DbPushError(
                "The remote database has no 'siteurl' option — is it really a WordPress database?"
            )

        emit(f"   wp-config     : {info.get('CFG', '?')}")
        emit(f"   remote root   : {wp_root}")
        emit(f"   remote DB     : {db_name} @ {info.get('DB_HOST', '?')}")
        emit(f"   remote prefix : {remote_prefix}")
        emit(f"   remote siteurl: {remote_url}")
        if remote_home_url and remote_home_url != remote_url:
            emit(f"   remote home   : {remote_home_url}")

        if remote_prefix != dev_prefix:
            raise DbPushError(
                f"Table prefix mismatch: dev uses '{dev_prefix}', the remote site uses "
                f"'{remote_prefix}'. Align them before pushing the database."
            )

        # ── 3. export with URL rewriting ─────────────────────────────
        cancel_check()
        emit("== 3/6 Exporting the dev database (URLs rewritten in the dump)")
        if dev_url != remote_url:
            emit(f"   search-replace: {dev_url} -> {remote_url}")
            export_cmd = [
                "docker", "exec", wp_container, "wp", "search-replace",
                dev_url, remote_url,
                "--all-tables-with-prefix",
                "--skip-columns=guid",
                "--precise",
                "--report-changed-only",
                f"--export={container_sql}",
                "--allow-root", "--skip-plugins", "--skip-themes", "--skip-packages",
            ]
        else:
            emit("   dev and remote URLs are identical: plain export")
            export_cmd = [
                "docker", "exec", wp_container, "wp", "db", "export", container_sql,
                "--no-tablespaces", "--single-transaction",
                "--allow-root", "--skip-plugins", "--skip-themes", "--skip-packages",
            ]

        code, out, err = _run_local(export_cmd, timeout=EXPORT_TIMEOUT)
        if code != 0 and "tablespaces" in (err + out).lower():
            # `--no-tablespaces` is a MySQL 8 option that MariaDB's
            # mysqldump rejects outright; on MySQL 8 it is what lets a
            # non-root user dump without the PROCESS privilege. Neither
            # flag suits both engines, so try one and fall back.
            emit("   retrying the export without --no-tablespaces (MariaDB)")
            export_cmd = [a for a in export_cmd
                          if a not in ("--no-tablespaces", "--single-transaction")]
            code, out, err = _run_local(export_cmd, timeout=EXPORT_TIMEOUT)
        for line in (out or "").splitlines()[-15:]:
            if line.strip():
                emit("   " + line.rstrip())
        if code != 0:
            detail = (err or out).strip().splitlines()
            raise DbPushError(
                "wp-cli export failed: " + (detail[-1] if detail else f"exit code {code}")
            )

        emit("   compressing the dump")
        raw_bytes, gz_bytes = _copy_and_gzip(wp_container, container_sql, local_gz)
        if raw_bytes == 0:
            raise DbPushError("The exported dump is empty — aborting before touching the remote site.")
        emit(f"   dump: {_human_size(raw_bytes)} -> {_human_size(gz_bytes)} gzipped")

        # ── 4. upload ────────────────────────────────────────────────
        cancel_check()
        emit("== 4/6 Uploading the dump")
        remote_gz = f"/tmp/wplp-{token}.sql.gz"
        _sftp_upload(client, local_gz, remote_gz, gz_bytes, emit)
        emit(f"   uploaded to {remote_gz}")

        # ── 5. remote backup + import ────────────────────────────────
        # Last chance to bail: past this point the remote database is
        # already being rewritten, so cancelling is no longer safe.
        cancel_check()
        emit("== 5/6 Backing up and importing on the remote host")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # Never inside the docroot — a .sql.gz under httpdocs would be
        # publicly downloadable. The SSH user's home also has far more
        # room than /tmp on most managed hosts.
        backup_dir = (
            f"{remote_home.rstrip('/')}/wp-launcher-backups"
            if remote_home and _PATH_RE.match(remote_home)
            else "/tmp"
        )
        backup_path = f"{backup_dir}/{db_name}-{stamp}.sql.gz"
        prefix_like = remote_prefix.replace("\\", "\\\\").replace("_", r"\_")
        code = run_streaming(
            _SCRIPT_IMPORT,
            [remote_cnf, db_name, prefix_like, remote_gz, backup_path,
             mysql_bin, mysqldump_bin, dev_charset, mysql_opt],
            timeout=IMPORT_TIMEOUT,
        )
        if code != 0:
            raise DbPushError(
                f"The remote import failed (exit code {code}). The remote database was rolled "
                f"back to the pre-import backup — check the rollback line above to confirm."
            )

        # ── 6. best-effort cleanup passes ────────────────────────────
        # The dump-level rewrite only caught `http://<devhost>`. What is
        # left are the same URLs in other shapes — JSON-escaped
        # (`http:\/\/host`, very common with Elementor / block editor /
        # WP Rocket payloads), protocol-relative, or scheme-less.
        emit("== 6/6 Cleaning up the remaining URL forms")
        if not wpcli_bin and php_bin:
            remote_phar = _upload_wp_cli(client, wp_container, token, work_dir, emit)
        else:
            remote_phar = ""
        if remote_phar:
            remote_temp.append(remote_phar)

        code = run_streaming(
            _SCRIPT_POST,
            [wpcli_bin, php_bin, remote_phar, wp_root, wpcli_via_php]
            + _cleanup_pairs(dev_url, remote_url),
            timeout=POST_TIMEOUT,
        )
        if code != 0:
            emit("   [cleanup passes reported an error — the import itself succeeded]", "stderr")

        emit(f"== Done — {db_name} now mirrors the dev database of {project_name}")
        emit("== The pre-import backup logged above is kept on the server")
        return {
            "dev_url": dev_url,
            "remote_url": remote_url,
            "db_name": db_name,
            "backup_path": backup_path,
            "dump_size": str(raw_bytes),
        }

    finally:
        # Local + remote temp files. Never removes the remote backup.
        try:
            if os.path.exists(local_gz):
                os.remove(local_gz)
        except OSError:
            pass
        _run_local(["docker", "exec", wp_container, "rm", "-f", container_sql], timeout=30)
        # Chemins déterministes à partir du token : le script d'inspection
        # écrit le .cnf (identifiants MySQL en clair) et le .php AVANT de
        # pouvoir échouer, auquel cas `remote_cnf` reste None côté Python et
        # le mot de passe resterait indéfiniment sur le serveur distant.
        deterministic = [f"/tmp/.wplp-{token}.cnf", f"/tmp/.wplp-{token}.php"]
        leftovers = [p for p in ([remote_cnf, remote_gz] + remote_temp + deterministic) if p]
        leftovers = list(dict.fromkeys(leftovers))
        if leftovers:
            try:
                _remote_capture(client, _SCRIPT_CLEANUP, leftovers, 60)
            except Exception:  # noqa: BLE001
                log.warning("Could not clean up remote temp files: %s", leftovers)


def _cleanup_pairs(dev_url: str, remote_url: str) -> list:
    """Flat [old, new, old, new, …] list for the post-import passes.

    The dump-level rewrite handled ``http://<devhost>`` verbatim. These
    passes mop up the other shapes the same URL takes in a WordPress
    database — each one still going through wp-cli so serialized
    payloads stay valid.
    """
    dev_host = _host_of(dev_url)
    remote_host = _host_of(remote_url)
    pairs = [
        # Any leftover form of the dev host: JSON-escaped, protocol
        # relative, or bare. Leaves the scheme untouched.
        dev_host, remote_host,
    ]
    if "/" in dev_host:
        # A dev URL carrying a path only matches JSON payloads once its
        # slashes are escaped the way json_encode writes them.
        pairs += [
            dev_host.replace("/", "\\/"), remote_host.replace("/", "\\/"),
        ]
    if remote_url.startswith("https://"):
        # …then upgrade the scheme wherever the host is now correct but
        # the URL still says http (both plain and JSON-escaped).
        json_host = remote_host.replace("/", "\\/")
        pairs += [
            f"http://{remote_host}", f"https://{remote_host}",
            f"http:\\/\\/{json_host}", f"https:\\/\\/{json_host}",
        ]
    return pairs


def _upload_wp_cli(client, wp_container: str, token: str, work_dir: str, emit) -> str:
    """Copy the dev container's wp-cli phar to the remote /tmp.

    Plesk-style hosts often have PHP but no ``wp`` in the deploy user's
    PATH; shipping the phar we already have locally keeps the cleanup
    passes available there. Best-effort: returns '' on any failure.
    """
    local_phar = os.path.join(work_dir, f"wplp-{token}-wp.phar")
    remote_phar = f"/tmp/wplp-{token}-wp.phar"
    try:
        code, _, err = _run_local(
            ["docker", "cp", f"{wp_container}:/usr/local/bin/wp", local_phar], timeout=120
        )
        if code != 0 or not os.path.isfile(local_phar):
            emit(f"   [could not read the local wp-cli phar: {err.strip()}]", "stderr")
            return ""
        size = os.path.getsize(local_phar)
        emit(f"   uploading wp-cli ({_human_size(size)}) — the remote host has none")
        _sftp_upload(client, local_phar, remote_phar, size, emit)
        return remote_phar
    except Exception as exc:  # noqa: BLE001
        emit(f"   [could not upload wp-cli: {exc}]", "stderr")
        return ""
    finally:
        try:
            if os.path.exists(local_phar):
                os.remove(local_phar)
        except OSError:
            pass


def _copy_and_gzip(container: str, container_path: str, local_gz: str) -> Tuple[int, int]:
    """Stream ``docker exec cat`` into a local gzip file.

    Streaming (rather than ``docker cp`` + compress) keeps a multi-GB
    dump off the launcher's disk in uncompressed form.
    """
    raw = 0
    # stderr dans un fichier plutôt qu'un tube : on ne lit que stdout dans la
    # boucle, et un tube stderr saturé (>64 Ko) bloquerait `docker exec`
    # indéfiniment. Le fichier se lit après coup, sans risque d'interblocage.
    with tempfile.TemporaryFile() as err_file:
        proc = subprocess.Popen(
            ["docker", "exec", container, "cat", container_path],
            stdout=subprocess.PIPE,
            stderr=err_file,
        )
        try:
            with gzip.open(local_gz, "wb", compresslevel=6) as out:
                assert proc.stdout is not None
                while True:
                    chunk = proc.stdout.read(1024 * 256)
                    if not chunk:
                        break
                    raw += len(chunk)
                    out.write(chunk)
            code = proc.wait(timeout=EXPORT_TIMEOUT)
        finally:
            if proc.poll() is None:
                proc.kill()
                # wait() après kill : sans ça le processus reste en zombie.
                proc.wait(timeout=10)
            if proc.stdout is not None:
                proc.stdout.close()

        if code != 0:
            err_file.seek(0)
            err = err_file.read().decode("utf-8", "replace").strip()
            raise DbPushError(
                f"Could not read the dump out of the container: {err or code}"
            )

    return raw, os.path.getsize(local_gz)


def _sftp_upload(client, local_path: str, remote_path: str, total: int, emit) -> None:
    last = {"pct": -10}

    def progress(sent: int, _total: int):
        if total <= 0:
            return
        pct = int(sent * 100 / total)
        if pct >= last["pct"] + 20:
            last["pct"] = pct - (pct % 20)
            emit(f"   {pct}% ({_human_size(sent)} / {_human_size(total)})")

    sftp = None
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(UPLOAD_TIMEOUT)
        sftp.put(local_path, remote_path, callback=progress, confirm=True)
        sftp.chmod(remote_path, 0o600)
    except Exception as exc:  # noqa: BLE001
        raise DbPushError(f"Upload failed: {exc}") from exc
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:  # noqa: BLE001
                pass
