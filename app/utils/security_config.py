"""Centralised security configuration for self-hosted deployments.

WP Launcher drives Docker and ``sudo`` on its host, so an authenticated
session is effectively root. When the app is reachable from the internet the
defaults below are what stand between a stranger and the host: services bind
to loopback unless explicitly opened, per-project database passwords are
random, and a missing ``SECRET_KEY`` aborts startup instead of silently
falling back to a shared constant.

Every knob is an environment variable so a local development box can opt back
into the permissive behaviour without patching code.
"""
import os
import secrets
import string

# Values that used to be hard-coded as the Flask secret. Refused at startup:
# they are public, so a session cookie signed with one is forgeable, and
# forging a session means root on the host.
_LEGACY_SECRETS = frozenset({
    'dev-secret-key-change-me',
    'change-me-in-production',
})

# Credentials the shipped templates used for every project. Kept here so
# existing containers created before randomisation keep working.
LEGACY_MYSQL_ROOT_PASSWORD = 'rootpassword'
LEGACY_MYSQL_PASSWORD = 'wordpress'
LEGACY_MYSQL_USER = 'wordpress'
LEGACY_MYSQL_DATABASE = 'wordpress'


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def is_local_mode() -> bool:
    """True when the operator explicitly asked for local-development defaults.

    Set ``WPL_LOCAL_MODE=true`` on a laptop or LAN box to restore the previous
    permissive behaviour (services on ``0.0.0.0``, plaintext cookies).
    """
    return _env_flag('WPL_LOCAL_MODE', False)


# ─── network binding ────────────────────────────────────────────────────

def site_bind_address() -> str:
    """Interface the project sites (WordPress, Next.js) listen on.

    Defaults to loopback: on a VPS the sites belong behind a reverse proxy
    that terminates TLS. Set ``WPL_SITE_BIND=0.0.0.0`` to publish directly.
    """
    default = '0.0.0.0' if is_local_mode() else '127.0.0.1'
    return os.environ.get('WPL_SITE_BIND', default).strip() or default


# Préfixe d'adresse dans un mapping de port compose ("127.0.0.1:8080:80").
# Optionnel : les projets créés avant le durcissement portent 0.0.0.0, ceux
# d'après 127.0.0.1, et un compose édité à la main peut n'avoir aucun préfixe.
# Toute réécriture de port doit accepter les trois formes, sinon elle ne
# matche plus rien et échoue en silence.
BIND_PREFIX = r'(?:\d{1,3}(?:\.\d{1,3}){3}:)?'


def admin_bind_address() -> str:
    """Interface the admin side-cars (phpMyAdmin, Mailpit, SMTP) listen on.

    These ship with static credentials and no TLS, so on an exposed host they
    must never leave loopback — reach them through an SSH tunnel instead:
    ``ssh -L 8081:127.0.0.1:8081 user@vps``.

    In local mode they follow the historical behaviour and bind everywhere,
    so the UI's ``http://<lan-ip>:8081`` links keep working from other
    machines on the network.
    """
    default = '0.0.0.0' if is_local_mode() else '127.0.0.1'
    return os.environ.get('WPL_ADMIN_BIND', default).strip() or default


# ─── Flask secret ───────────────────────────────────────────────────────

def require_secret_key() -> str:
    """Return the Flask ``SECRET_KEY``, refusing to start without a real one.

    The key does double duty: it signs session cookies *and* derives the
    Fernet key that encrypts stored SSH private keys
    (:mod:`app.services.ssh_service`). A predictable value means stored
    deployment keys are decryptable by anyone holding the source, so a
    missing key is a hard failure rather than a warning.
    """
    key = (os.environ.get('SECRET_KEY') or '').strip()

    if not key:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with:\n"
            "  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "and add it to your .env. It signs session cookies and encrypts "
            "stored SSH private keys — rotating it logs everyone out and "
            "invalidates saved deployment keys."
        )

    if key in _LEGACY_SECRETS:
        raise RuntimeError(
            f"SECRET_KEY is still a shipped placeholder ({key!r}). "
            "Replace it with a random value before starting."
        )

    if len(key) < 32:
        raise RuntimeError(
            f"SECRET_KEY is too short ({len(key)} chars, 32 minimum). "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

    return key


# ─── session cookies ────────────────────────────────────────────────────

def session_cookie_secure() -> bool:
    """Whether to mark the session cookie ``Secure`` (HTTPS-only).

    On by default — a self-hosted instance belongs behind TLS. Local HTTP
    setups opt out with ``WPL_LOCAL_MODE=true`` or ``SESSION_COOKIE_SECURE=false``.
    """
    return _env_flag('SESSION_COOKIE_SECURE', not is_local_mode())


def session_lifetime_seconds() -> int:
    """Session lifetime. Shorter than the previous 30 days for exposed hosts."""
    default = 2592000 if is_local_mode() else 43200  # 30 days vs 12 hours
    try:
        return int(os.environ.get('WPL_SESSION_LIFETIME', default))
    except ValueError:
        return default


# ─── generated credentials ──────────────────────────────────────────────

# Ambiguous glyphs removed: these end up copy-pasted out of the UI by hand.
_PASSWORD_ALPHABET = (
    string.ascii_lowercase.replace('l', '').replace('o', '')
    + string.ascii_uppercase.replace('I', '').replace('O', '')
    + string.digits.replace('0', '').replace('1', '')
)


def generate_password(length: int = 24) -> str:
    """Random password safe to drop into docker-compose and MySQL alike.

    Alphanumeric on purpose: these values are interpolated into YAML, shell
    commands (``mysql -p<password>``) and PHP string literals, where quoting
    bugs are far likelier than a brute-force against 24 random chars.
    """
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def apply_project_credentials(content: str, overrides: dict | None = None) -> str:
    """Substitute the credential placeholders in a rendered compose file.

    Idempotent by construction: an already-rendered compose has no
    placeholders left, so calling this again on an existing project is a
    no-op rather than a password rotation that would lock the stack out of
    its own database.

    ``overrides`` maps a placeholder to the value it must take — pass the
    credentials already recorded in the project's ``.db.json`` when
    *re-rendering* a compose for an existing project. Without it, a
    re-render mints fresh random passwords, and the site is locked out of a
    database whose password nobody changed.
    """
    placeholders = ('{mysql_root_password}', '{mysql_password}', '{mongo_password}')

    legacy = {
        '{mysql_root_password}': LEGACY_MYSQL_ROOT_PASSWORD,
        '{mysql_password}': LEGACY_MYSQL_PASSWORD,
        '{mongo_password}': 'adminpassword',
    }

    overrides = overrides or {}
    randomise = should_randomise_project_credentials()

    for token in placeholders:
        if token not in content:
            continue
        if token in overrides:
            value = overrides[token]
        else:
            value = generate_password() if randomise else legacy[token]
        content = content.replace(token, value)

    return content


def should_randomise_project_credentials() -> bool:
    """Whether new projects get unique database passwords.

    Set ``WPL_LEGACY_PROJECT_CREDENTIALS=true`` to keep the old shared
    ``wordpress``/``rootpassword`` values — only useful for tooling that
    hard-codes them. Existing projects are unaffected either way: their
    passwords are read back from the running container.
    """
    return not _env_flag('WPL_LEGACY_PROJECT_CREDENTIALS', False)
