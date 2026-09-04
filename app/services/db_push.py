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
  4. upload the gzipped dump over SFTP — when the two sites use
     different table prefixes, the dump is rewritten on the fly so it
     lands under the *remote* prefix (the remote ``wp-config.php`` is
     never touched);
  5. remotely: back up the target database, drop the prefixed tables,
     import the dump, then rename the prefix-dependent option/usermeta
     keys (``<prefix>user_roles``, ``<prefix>capabilities``…);
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

# The largest statement this server will accept. A dump built without
# looking at it can carry a single multi-megabyte INSERT that the server
# refuses by closing the connection — reported as the famously unhelpful
# "MySQL server has gone away".
MAXPACKET=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
  "SELECT @@max_allowed_packet" "$DB_NAME" < /dev/null) || MAXPACKET=""

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
printf 'MAXPACKET=%s\n' "$MAXPACKET"
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
# Set only when the dump was rewritten from the dev prefix to the remote
# one: the tables already carry NEW_PREFIX, but the prefix-dependent
# rows inside them still carry OLD_PREFIX and must follow.
OLD_PREFIX="${10:-}"
NEW_PREFIX="${11:-}"
# The mysql client caps outgoing statements at its own max_allowed_packet
# (16M by default), regardless of what the server allows. Raise it to the
# server's value so only the server's limit ever applies. Empty when the
# server did not report one: the client then keeps its own default.
PKT="${12:-}"
PKT_OPT=""
[ -n "$PKT" ] && PKT_OPT="--max-allowed-packet=$PKT"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

# Used by every failure that happens once the target tables are gone.
rollback_now() {
  printf -- '-- rolling back to the pre-import backup\n'
  if gunzip -c "$BAK" | "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT $PKT_OPT "$DB"; then
    printf -- '-- rollback done: the remote database is back to its previous state\n'
  else
    printf -- '-- ROLLBACK FAILED — restore manually with:\n'
    printf -- '--   gunzip -c %s | mysql %s\n' "$BAK" "$DB"
  fi
}

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
} | "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT $PKT_OPT --default-character-set="$CHARSET" "$DB"; then
  # The tables were already dropped, so a half-finished import leaves the
  # site down. Roll straight back to the snapshot taken minutes ago
  # rather than leaving someone to do it by hand under pressure.
  printf -- '-- IMPORT FAILED\n'
  rollback_now
  fail "import failed" 13
fi
printf -- '-- import finished\n'

if [ -n "$OLD_PREFIX" ] && [ -n "$NEW_PREFIX" ] && [ "$OLD_PREFIX" != "$NEW_PREFIX" ]; then
  # WordPress keys a handful of rows by table prefix: the roles
  # definition in options, and the capabilities / user level / screen
  # settings in usermeta. Left under the dev prefix they would be
  # invisible to the remote site — every user would lose their role.
  #
  # Both lists are EXPLICIT rather than a `LIKE '<prefix>%'` sweep. With a
  # dev prefix of `wp_` that sweep also caught rows that merely start with
  # those letters — core's own `wp_page_for_privacy_policy` option, or a
  # plugin's `wp_rocket_*` usermeta — and renaming those corrupts them.
  printf -- '-- renaming the prefixed keys (%s -> %s)\n' "$OLD_PREFIX" "$NEW_PREFIX"
  START=$(( ${#OLD_PREFIX} + 1 ))
  "$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -e \
    "UPDATE \`${NEW_PREFIX}options\` \
       SET option_name = CONCAT('${NEW_PREFIX}', SUBSTRING(option_name, ${START})) \
       WHERE option_name = '${OLD_PREFIX}user_roles'; \
     UPDATE \`${NEW_PREFIX}usermeta\` \
       SET meta_key = CONCAT('${NEW_PREFIX}', SUBSTRING(meta_key, ${START})) \
       WHERE meta_key IN ('${OLD_PREFIX}capabilities', \
                          '${OLD_PREFIX}user_level', \
                          '${OLD_PREFIX}user-settings', \
                          '${OLD_PREFIX}user-settings-time', \
                          '${OLD_PREFIX}dashboard_quick_press_last_post_id', \
                          '${OLD_PREFIX}media_library_mode', \
                          '${OLD_PREFIX}persisted_preferences');" \
    "$DB" < /dev/null || {
      # Every user would be locked out of a site that otherwise looks
      # imported. Put the previous database back rather than leave that.
      printf -- '-- KEY RENAME FAILED\n'
      rollback_now
      fail "could not rename the prefixed option/usermeta keys" 14
    }
  ROLES=$("$MYSQL" --defaults-file="$CNF" $MYSQL_OPT -N -B -e \
    "SELECT COUNT(*) FROM \`${NEW_PREFIX}usermeta\` WHERE meta_key = '${NEW_PREFIX}capabilities'" \
    "$DB" < /dev/null) || ROLES="?"
  printf -- '-- %s user(s) now carry %scapabilities\n' "$ROLES" "$NEW_PREFIX"
fi

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
        max_packet = _max_packet(info.get("MAXPACKET", ""))
        # Two different numbers: what we batch to, and what the server
        # actually refuses. Conflating them aborted pushes that would have
        # gone through — a 20 MB row is fine against a 64 MB server even
        # though we never build a statement that large.
        stmt_budget = min(max_packet or _DEFAULT_PACKET, _MAX_STATEMENT) - _PACKET_MARGIN
        hard_limit = max_packet - _PACKET_MARGIN if max_packet else 0

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
        if max_packet:
            emit(
                f"   max_allowed_packet: {_human_size(max_packet)}"
                f" (statements capped at {_human_size(stmt_budget)})"
            )
        else:
            emit(
                "   max_allowed_packet: not reported by the server — statements "
                f"capped at {_human_size(stmt_budget)}"
            )

        prefix_rewrite = remote_prefix != dev_prefix
        if prefix_rewrite:
            # Plesk's WP Toolkit (among others) installs with a random
            # prefix. Rather than asking the user to align the two
            # sites by hand, the dump is rewritten to the remote prefix
            # so the imported tables match the remote wp-config.php.
            emit(
                f"   prefix rewrite: dev tables '{dev_prefix}' will be imported as "
                f"'{remote_prefix}' (the remote wp-config.php is kept as is)"
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
        if code == _EXIT_KILLED:
            # The cgroup OOM killer, not wp-cli: `wp search-replace
            # --export` unserializes every row in PHP and easily needs
            # 200 MB, while the container's mem_limit (256m by default)
            # is largely taken by Apache already. Raise the cap once and
            # retry — the limit is the launcher's own choice, so this is
            # ours to fix rather than the user's.
            current = _container_memory(wp_container)
            if not current:
                # docker reports 0 for a container with no cap of its own,
                # so there is nothing of ours to raise: the kill came from
                # the host running out of memory, or from outside.
                raise DbPushError(
                    "wp-cli export was killed (exit 137) but the WordPress container "
                    "has no memory limit of its own — the host ran out of memory, or "
                    "the process was killed from outside. Re-run the push once the "
                    "machine is free."
                )
            if current >= _parse_size(EXPORT_MEMORY):
                raise DbPushError(
                    f"wp-cli export killed (out of memory) although the container already "
                    f"has {_human_size(current)} — raise mem_limit in the project's docker-compose.yml"
                )
            emit(
                f"   the export was killed by the container memory limit "
                f"({_human_size(current)}) — raising it to {EXPORT_MEMORY} and retrying",
                "stderr",
            )
            if not _raise_container_memory(wp_container, EXPORT_MEMORY):
                raise DbPushError(
                    f"wp-cli export killed by the container memory limit and `docker update` "
                    f"failed — set wordpress mem_limit to {EXPORT_MEMORY} in the project's "
                    f"docker-compose.yml and recreate the container"
                )
            emit(
                f"   note: `docker update` does not touch docker-compose.yml — set "
                f"mem_limit to {EXPORT_MEMORY} there too, or the cap returns on recreate"
            )
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
        shown, skipped = _filter_export_output(out)
        for line in shown[-15:]:
            emit("   " + line)
        if skipped:
            # Serialized objects of classes not loaded under --skip-plugins
            # (Freemius `FS_Plugin`, Elementor's log items): wp-cli leaves
            # them as is. They are plugin bookkeeping, never site content,
            # so one summary line beats a thousand identical warnings.
            emit(f"   {skipped} serialized plugin object(s) left untouched (uninitialized classes)")
        if code != 0:
            raise DbPushError("wp-cli export failed: " + _export_failure_detail(code, out, err))

        emit("   compressing the dump")
        raw_bytes, gz_bytes, oversized = _copy_and_gzip(
            wp_container, container_sql, local_gz, dev_prefix, remote_prefix,
            stmt_budget, hard_limit,
        )
        if raw_bytes == 0:
            raise DbPushError("The exported dump is empty — aborting before touching the remote site.")
        emit(f"   dump: {_human_size(raw_bytes)} -> {_human_size(gz_bytes)} gzipped")
        if prefix_rewrite:
            emit(f"   table prefix rewritten in the dump: {dev_prefix} -> {remote_prefix}")
        if oversized:
            # Nothing remote has been touched yet: fail here rather than
            # after dropping the target's tables, which would only get
            # rolled back a few minutes later.
            biggest = max(oversized, key=lambda o: o[1])
            raise DbPushError(
                f"{len(oversized)} row(s) are individually larger than the remote "
                f"max_allowed_packet ({_human_size(max_packet)}) — the biggest is "
                f"{_human_size(biggest[1])} in {biggest[0]}. The import would be cut off "
                f"mid-way ('MySQL server has gone away'). Raise max_allowed_packet on the "
                f"remote MySQL server (Plesk: Databases > server settings), then push again."
            )

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
        prefix_like = _like_escape(remote_prefix)
        code = run_streaming(
            _SCRIPT_IMPORT,
            [remote_cnf, db_name, prefix_like, remote_gz, backup_path,
             mysql_bin, mysqldump_bin, dev_charset, mysql_opt,
             # Empty when the prefixes match: the script then skips the
             # key renaming entirely.
             dev_prefix if prefix_rewrite else "",
             remote_prefix if prefix_rewrite else "",
             # Empty when unknown: the client then keeps its own default
             # rather than being talked DOWN to our guess, which would
             # also cap the rollback replaying the server's own dump.
             str(max_packet) if max_packet else ""],
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


# Exit status of a process killed by SIGKILL — for `docker exec`, that is
# the cgroup OOM killer in practice.
_EXIT_KILLED = 137
# What the WordPress container is raised to when the export gets killed.
EXPORT_MEMORY = "1g"
_UNINIT_WARNING = "Skipping an uninitialized class"


def _filter_export_output(out: str) -> Tuple[list, int]:
    """Drop wp-cli's per-object "uninitialized class" warnings, count them."""
    shown = []
    skipped = 0
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        if _UNINIT_WARNING in line:
            skipped += 1
            continue
        shown.append(line.rstrip())
    return shown, skipped


def _export_failure_detail(code: int, out: str, err: str) -> str:
    """The line worth showing for a failed export — never a noise warning."""
    if code == _EXIT_KILLED:
        return (
            "the process was killed (exit 137) — out of memory in the WordPress "
            "container; raise its mem_limit"
        )
    for text in (err, out):
        lines = [l.strip() for l in (text or "").splitlines()
                 if l.strip() and _UNINIT_WARNING not in l]
        if lines:
            return lines[-1]
    return f"exit code {code}"


_SIZE_UNITS = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _parse_size(value: str) -> int:
    """``1g`` / ``512m`` / ``268435456`` → bytes (docker's own notation)."""
    v = value.strip().lower()
    if v and v[-1] in _SIZE_UNITS:
        return int(float(v[:-1]) * _SIZE_UNITS[v[-1]])
    return int(v)


def _container_memory(container: str) -> int:
    """Current memory cap of a container in bytes (0 = unlimited/unknown)."""
    code, out, _ = _run_local(
        ["docker", "inspect", "--format", "{{.HostConfig.Memory}}", container], timeout=30
    )
    try:
        return int(out.strip()) if code == 0 else 0
    except ValueError:
        return 0


def _raise_container_memory(container: str, size: str) -> bool:
    """``docker update`` the cap live — no restart, takes effect at once.

    Swap is set to twice the cap, mirroring what compose derives from a
    bare ``mem_limit``; docker refuses a memory raise that would leave
    swap below memory otherwise.
    """
    swap = str(_parse_size(size) * 2)
    code, _, _ = _run_local(
        ["docker", "update", "--memory", size, "--memory-swap", swap, container], timeout=60
    )
    return code == 0


def _like_escape(value: str) -> str:
    """Escape ``_`` and ``\\`` so a prefix is matched literally by LIKE."""
    return value.replace("\\", "\\\\").replace("_", r"\_")


# Statements whose head names a table. The prefix is rewritten there
# only — never in the data, where a post quoting `wp_posts` in a code
# block would otherwise be corrupted.
_TABLE_STMT_RE = re.compile(
    rb"^(INSERT INTO|REPLACE INTO|CREATE TABLE IF NOT EXISTS|CREATE TABLE|"
    rb"DROP TABLE IF EXISTS|DROP TABLE|LOCK TABLES|ALTER TABLE|TRUNCATE TABLE|"
    rb"/\*!40000 ALTER TABLE) `"
)


def _rewrite_prefix_line(
    line: bytes, old: bytes, new: bytes, in_create: bool
) -> Tuple[bytes, bool]:
    """Rewrite one dump line; ``in_create`` tracks a multi-line CREATE TABLE."""
    m = _TABLE_STMT_RE.match(line)
    if m:
        head = m.end()
        if line.startswith(old, head):
            line = line[:head] + new + line[head + len(old):]
        # A CREATE TABLE spans several lines (one per column); a foreign
        # key inside it names another prefixed table.
        in_create = m.group(1).startswith(b"CREATE TABLE") and not line.rstrip().endswith(b";")
        return line, in_create
    if in_create:
        if line.startswith(b")"):
            in_create = False  # `) ENGINE=InnoDB …;`
        else:
            line = line.replace(b"REFERENCES `" + old, b"REFERENCES `" + new)
        return line, in_create
    if line.startswith(b"-- ") and b"table `" + old in line:
        # mysqldump's "Table structure for table `x`" banners: cosmetic,
        # but a log reader grepping the dump expects the real names.
        line = line.replace(b"table `" + old, b"table `" + new, 1)
    return line, in_create


def _rewrite_prefix_stream(chunks, old_prefix: str, new_prefix: str):
    """Yield ``chunks`` with every table name moved from one prefix to the other.

    Line-based: an INSERT split across two chunks is reassembled before
    being looked at. A no-op when the prefixes match.

    The partial line is appended to, never rebuilt: `wp db export` (used
    when both sides share a URL) is plain mysqldump, whose extended
    inserts put a whole table on ONE line — concatenating `pending +
    chunk` per 256 KB read made that quadratic (a 250 MB line measured
    ~100 s of pure copying). Past _LINE_CAP the head has long been seen,
    so the tail is streamed out raw: it is row data, never a table name.
    """
    if old_prefix == new_prefix:
        yield from chunks
        return
    old = old_prefix.encode("utf-8")
    new = new_prefix.encode("utf-8")
    pending = bytearray()
    in_create = False
    overflow = False        # this line is past the cap: pass it through
    for chunk in chunks:
        start = 0
        while True:
            nl = chunk.find(b"\n", start)
            if nl == -1:
                if overflow:
                    yield chunk[start:]
                else:
                    pending += chunk[start:]
                    if len(pending) >= _LINE_CAP:
                        line, in_create = _rewrite_prefix_line(
                            bytes(pending), old, new, in_create
                        )
                        yield line
                        pending = bytearray()
                        overflow = True
                break
            if overflow:
                yield chunk[start:nl + 1]
                overflow = False
            else:
                pending += chunk[start:nl + 1]
                line, in_create = _rewrite_prefix_line(
                    bytes(pending), old, new, in_create
                )
                pending = bytearray()
                yield line
            start = nl + 1
    if pending:
        line, _ = _rewrite_prefix_line(bytes(pending), old, new, in_create)
        yield line


# Ceiling on a generated statement, whatever the server allows: a value
# every MySQL/MariaDB build accepts, and small enough that one statement
# never dominates the import's memory. Margin covers the per-statement
# protocol overhead.
_MAX_STATEMENT = 16 * 1024 ** 2
_PACKET_MARGIN = 64 * 1024
# How small a statement we batch to when the server will not say what it
# accepts — MySQL's own historical default, safe everywhere. Used ONLY as
# a batching target: with no known limit we must not declare a row
# unsendable, nor tell the client to cap itself.
_DEFAULT_PACKET = 4 * 1024 ** 2
# Beyond this, a single line is streamed out instead of being buffered.
_LINE_CAP = 8 * 1024 ** 2


def _max_packet(value: str) -> Optional[int]:
    """The remote's ``max_allowed_packet``, or None when it did not say."""
    try:
        parsed = int((value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


_INSERT_MARK = b"INSERT INTO "
_VALUES_MARK = b" VALUES "
# A statement head longer than this is not a head at all.
_HEAD_SCAN = 8192


def _split_large_inserts(chunks, max_bytes: int, hard_limit: int = 0):
    """Re-emit INSERT statements that exceed ``max_bytes`` as several.

    ``wp search-replace --export`` batches 50 rows per INSERT, so a table
    holding a few multi-megabyte rows (Elementor's inlined SVGs, base64
    images) produces statements far past any ``max_allowed_packet``. The
    server answers by closing the connection — ``ERROR 2006 … server has
    gone away`` — halfway through the import.

    Splitting happens at row boundaries, tracked with a real scanner
    (string literals, backslash escapes, nesting) rather than a regex, so
    a comma inside post content is never mistaken for a row separator.
    ``max_bytes`` is the batching target; ``hard_limit`` (0 = unknown) is
    what the server will actually refuse. A row over the target is simply
    given a statement of its own — only one over the *hard limit* is
    unsendable, and those are reported so the caller can abort before
    touching the remote.

    Yields byte chunks, and finally a list of ``(table, size)`` for the
    rows that could not be made to fit.
    """
    oversized = []
    if not max_bytes or max_bytes <= 0:
        yield from chunks
        return oversized

    line = bytearray()      # COPY mode: current line, until we can classify it
    passthrough = False     # this line is not a statement head: stream it out
    header = None           # set while inside an INSERT's row list
    table = b""
    row = bytearray()
    depth = 0
    in_string = False
    escaped = False
    has_row = False
    stmt_len = 0
    eat_newline = False     # the source newline that followed a ';'

    for chunk in chunks:
        data = chunk
        pos = 0
        end = len(data)
        while pos < end:
            if header is None:
                # ── outside an INSERT: copy through, watching for a head
                nl = data.find(b"\n", pos)
                stop = end if nl == -1 else nl + 1
                if passthrough:
                    yield data[pos:stop]
                    if nl != -1:
                        passthrough = False
                    pos = stop
                    continue
                line += data[pos:stop]
                pos = stop
                if line.startswith(_INSERT_MARK):
                    at = line[:_HEAD_SCAN].find(_VALUES_MARK)
                    if at != -1:
                        cut = at + len(_VALUES_MARK)
                        header = bytes(line[:cut])
                        table = header[len(_INSERT_MARK):].split(b" ", 1)[0]
                        rest = bytes(line[cut:])
                        line = bytearray()
                        yield header
                        stmt_len = len(header)
                        has_row = False
                        # The rest of the head's line is already row data.
                        data = rest + data[pos:]
                        pos, end = 0, len(data)
                        continue
                    if len(line) < _HEAD_SCAN and nl == -1:
                        continue  # need more bytes to decide
                    # Starts like an INSERT but has no VALUES in its first
                    # 8 KB (INSERT ... SELECT, say). Nothing to split, and
                    # nothing to gain from buffering it whole.
                    yield bytes(line)
                    passthrough = nl == -1
                    line = bytearray()
                    continue
                elif len(line) >= len(_INSERT_MARK) and not _INSERT_MARK.startswith(bytes(line)):
                    # Definitely not a head — stop buffering this line.
                    yield bytes(line)
                    passthrough = nl == -1
                    line = bytearray()
                    continue
                if nl != -1:
                    if not (eat_newline and bytes(line) in (b"\n", b"\r\n")):
                        yield bytes(line)
                    eat_newline = False
                    line = bytearray()
                continue

            # ── inside an INSERT's row list ─────────────────────────
            c = data[pos]
            pos += 1
            if in_string:
                row.append(c)
                if escaped:
                    escaped = False
                elif c == 0x5C:      # backslash
                    escaped = True
                elif c == 0x27:      # closing quote ('' is handled by re-opening)
                    in_string = False
                continue
            if c == 0x27:
                in_string = True
                row.append(c)
                continue
            if c == 0x28:            # (
                depth += 1
                row.append(c)
                continue
            if c == 0x29:            # )
                depth -= 1
                row.append(c)
                continue
            if depth == 0 and c in (0x2C, 0x3B):   # , or ; between rows
                piece = bytes(row).strip()
                row = bytearray()
                if piece:
                    needed = len(header) + len(piece) + 2
                    # Too big to share a statement — give it its own,
                    # rather than let it drag 49 neighbours over with it.
                    alone = needed > max_bytes
                    if hard_limit and needed > hard_limit:
                        # Genuinely unsendable: no split can help.
                        oversized.append(
                            (table.decode("utf-8", "replace").strip("`"), len(piece))
                        )
                    if has_row and (alone or stmt_len + 2 + len(piece) + 2 > max_bytes):
                        yield b";\n"
                        yield header
                        stmt_len = len(header)
                        has_row = False
                    if has_row:
                        yield b",\n"
                        stmt_len += 2
                    yield piece
                    stmt_len += len(piece)
                    has_row = True
                if c == 0x3B:        # end of statement
                    yield b";\n"
                    header = None
                    has_row = False
                    eat_newline = True
                continue
            row.append(c)            # whitespace / newlines between rows

    # A dump that stops inside a statement is truncated — `docker exec
    # cat` was killed, the disk filled up. Terminating it here would ship
    # syntactically valid but WRONG SQL, and the remote tables are dropped
    # before the import runs. Fail while nothing has been touched.
    if header is not None:
        raise DbPushError(
            "The exported dump is truncated (it ends in the middle of an "
            f"INSERT into {table.decode('utf-8', 'replace').strip('`') or '?'}) "
            "— aborting before touching the remote site."
        )
    if line:
        yield bytes(line)
    return oversized


def _drain(gen, sink) -> list:
    """Write a generator's chunks to ``sink``, returning its final value."""
    while True:
        try:
            sink(next(gen))
        except StopIteration as stop:
            return stop.value or []


def _copy_and_gzip(
    container: str,
    container_path: str,
    local_gz: str,
    old_prefix: str = "",
    new_prefix: str = "",
    max_statement: int = 0,
    hard_limit: int = 0,
) -> Tuple[int, int, list]:
    """Stream ``docker exec cat`` into a local gzip file.

    Streaming (rather than ``docker cp`` + compress) keeps a multi-GB
    dump off the launcher's disk in uncompressed form. When
    ``old_prefix`` and ``new_prefix`` differ the table prefix is
    rewritten on the way through (see :func:`_rewrite_prefix_stream`),
    and ``max_statement`` caps the size of a single INSERT (see
    :func:`_split_large_inserts`).

    Returns ``(raw_bytes, gzipped_bytes, oversized_rows)``.
    """
    raw = 0
    oversized: list = []
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
            assert proc.stdout is not None

            def _chunks():
                nonlocal raw
                while True:
                    chunk = proc.stdout.read(1024 * 256)
                    if not chunk:
                        break
                    raw += len(chunk)
                    yield chunk

            with gzip.open(local_gz, "wb", compresslevel=6) as out:
                stream = _rewrite_prefix_stream(_chunks(), old_prefix, new_prefix)
                if max_statement > 0:
                    oversized = _drain(
                        _split_large_inserts(stream, max_statement, hard_limit), out.write
                    )
                else:
                    for piece in stream:
                        out.write(piece)
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

    return raw, os.path.getsize(local_gz), oversized


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
