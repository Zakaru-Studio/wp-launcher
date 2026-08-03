"""Tests for the security-hardening layer.

These cover pure functions with no Docker or network dependency:
brute-force throttling, SECRET_KEY validation, per-project credential
resolution and WordPress salt generation.
"""
import os
import re

import pytest

from app.utils import login_throttle, security_config
from app.utils.project_credentials import _compose_env, get_mysql_credentials


# ─── login throttle ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_throttle():
    login_throttle.reset()
    yield
    login_throttle.reset()


def test_throttle_allows_attempts_below_threshold():
    for _ in range(login_throttle.MAX_ATTEMPTS - 1):
        login_throttle.record_failure('10.0.0.1', 'alice')
    assert login_throttle.check('10.0.0.1', 'alice') == 0


def test_throttle_locks_after_threshold():
    for _ in range(login_throttle.MAX_ATTEMPTS):
        login_throttle.record_failure('10.0.0.1', 'alice')
    assert login_throttle.check('10.0.0.1', 'alice') > 0


def test_throttle_lockout_is_scoped_to_the_ip_username_pair():
    """A locked-out attacker must not lock the real user out from elsewhere."""
    for _ in range(login_throttle.MAX_ATTEMPTS + 1):
        login_throttle.record_failure('10.0.0.1', 'alice')
    assert login_throttle.check('10.0.0.2', 'alice') == 0


def test_throttle_backoff_grows_with_repeated_failures():
    penalties = [
        login_throttle.record_failure('10.0.0.3', 'bob')
        for _ in range(login_throttle.MAX_ATTEMPTS + 3)
    ]
    applied = [p for p in penalties if p]
    assert applied == sorted(applied)
    assert applied[-1] > applied[0]


def test_throttle_blocks_password_spraying_across_usernames():
    """One IP trying a few passwords against many accounts still trips."""
    for i in range(login_throttle.MAX_ATTEMPTS_PER_IP + 1):
        login_throttle.record_failure('10.0.0.4', f'user{i}')
    assert login_throttle.check('10.0.0.4', 'never-seen-before') > 0


def test_throttle_truncates_attacker_supplied_username():
    login_throttle.record_failure('10.0.0.5', 'x' * 5000)
    keys = [k for k in login_throttle._attempts if k[0] == '10.0.0.5' and k[1]]
    assert len(keys[0][1]) == login_throttle.MAX_USERNAME_KEY_LEN


def test_throttle_flood_cannot_evict_an_active_lockout():
    """Junk usernames must not push an attacker's own lockout out of the table."""
    for _ in range(login_throttle.MAX_ATTEMPTS + 1):
        login_throttle.record_failure('10.0.0.6', 'victim')
    assert login_throttle.check('10.0.0.6', 'victim') > 0

    for i in range(login_throttle._MAX_TRACKED_KEYS + 100):
        login_throttle.record_failure('10.0.0.7', f'junk{i}')

    assert login_throttle.check('10.0.0.6', 'victim') > 0


def test_throttle_success_clears_counters():
    for _ in range(login_throttle.MAX_ATTEMPTS - 1):
        login_throttle.record_failure('10.0.0.8', 'carol')
    login_throttle.record_success('10.0.0.8', 'carol')
    for _ in range(login_throttle.MAX_ATTEMPTS - 1):
        login_throttle.record_failure('10.0.0.8', 'carol')
    assert login_throttle.check('10.0.0.8', 'carol') == 0


# ─── SECRET_KEY validation ──────────────────────────────────────────────

@pytest.mark.parametrize('value', ['', '   '])
def test_require_secret_key_rejects_missing(monkeypatch, value):
    monkeypatch.setenv('SECRET_KEY', value)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        security_config.require_secret_key()


def test_require_secret_key_rejects_unset(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    with pytest.raises(RuntimeError):
        security_config.require_secret_key()


@pytest.mark.parametrize('placeholder', sorted(security_config._LEGACY_SECRETS))
def test_require_secret_key_rejects_shipped_placeholders(monkeypatch, placeholder):
    """Both historical hard-coded values must be refused: they are public,
    so a session cookie signed with one is forgeable."""
    monkeypatch.setenv('SECRET_KEY', placeholder)
    with pytest.raises(RuntimeError, match='placeholder'):
        security_config.require_secret_key()


def test_require_secret_key_rejects_short_keys(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'a' * 31)
    with pytest.raises(RuntimeError, match='too short'):
        security_config.require_secret_key()


def test_require_secret_key_accepts_a_real_key(monkeypatch):
    key = 'b' * 64
    monkeypatch.setenv('SECRET_KEY', key)
    assert security_config.require_secret_key() == key


# ─── generated credentials ──────────────────────────────────────────────

def test_generated_passwords_are_unique_and_shell_safe():
    passwords = {security_config.generate_password() for _ in range(50)}
    assert len(passwords) == 50
    for pw in passwords:
        assert len(pw) == 24
        # Interpolated into YAML, `mysql -p<pw>` and PHP single-quoted
        # strings — anything outside [A-Za-z0-9] risks breaking one of them.
        assert re.fullmatch(r'[A-Za-z0-9]+', pw)


def test_apply_project_credentials_is_idempotent():
    """Re-rendering an existing compose must not rotate its password, or the
    stack loses access to its own database."""
    template = 'MYSQL_ROOT_PASSWORD: "{mysql_root_password}"\n'
    rendered = security_config.apply_project_credentials(template)
    assert '{mysql_root_password}' not in rendered
    assert security_config.apply_project_credentials(rendered) == rendered


def test_apply_project_credentials_reuses_one_value_per_token():
    template = (
        'MYSQL_ROOT_PASSWORD: "{mysql_root_password}"\n'
        'test: ["-p{mysql_root_password}"]\n'
    )
    rendered = security_config.apply_project_credentials(template)
    found = re.findall(r'MYSQL_ROOT_PASSWORD: "([^"]+)"', rendered)
    assert f'-p{found[0]}' in rendered


# ─── compose credential scraping ────────────────────────────────────────

def test_compose_env_reads_quoted_and_bare_values(tmp_path):
    compose = tmp_path / 'docker-compose.yml'
    compose.write_text(
        'services:\n'
        '  mysql:\n'
        '    environment:\n'
        '      MYSQL_ROOT_PASSWORD: "R00tPass"\n'
        '      MYSQL_USER: wordpress\n'
        "      MYSQL_PASSWORD: 'UserPass'\n"
        '      MYSQL_DATABASE: wordpress\n'
    )
    env = _compose_env(str(compose))
    assert env['MYSQL_ROOT_PASSWORD'] == 'R00tPass'
    assert env['MYSQL_PASSWORD'] == 'UserPass'
    assert env['MYSQL_USER'] == 'wordpress'


def test_compose_env_strips_trailing_comment_but_keeps_hash_in_value(tmp_path):
    compose = tmp_path / 'docker-compose.yml'
    compose.write_text(
        '      MYSQL_PASSWORD: secret   # rotated 2026-01-01\n'
        '      MYSQL_ROOT_PASSWORD: has#hash\n'
    )
    env = _compose_env(str(compose))
    assert env['MYSQL_PASSWORD'] == 'secret'
    assert env['MYSQL_ROOT_PASSWORD'] == 'has#hash'


def test_compose_env_ignores_unsubstituted_placeholders(tmp_path):
    """An unrendered template must not be mistaken for a real credential."""
    compose = tmp_path / 'docker-compose.yml'
    compose.write_text('      MYSQL_PASSWORD: "{mysql_password}"\n')
    assert _compose_env(str(compose)) == {}


def test_compose_env_handles_env_list_form(tmp_path):
    compose = tmp_path / 'docker-compose.yml'
    compose.write_text('    environment:\n      - MYSQL_PASSWORD=ListForm\n')
    assert _compose_env(str(compose))['MYSQL_PASSWORD'] == 'ListForm'


def test_get_mysql_credentials_falls_back_to_legacy_for_unknown_project(tmp_path):
    creds = get_mysql_credentials('does-not-exist', containers_folder=str(tmp_path))
    assert creds['root_password'] == security_config.LEGACY_MYSQL_ROOT_PASSWORD
    assert creds['user'] == security_config.LEGACY_MYSQL_USER


def test_get_mysql_credentials_prefers_compose_over_legacy(tmp_path):
    project = tmp_path / 'demo'
    project.mkdir()
    (project / 'docker-compose.yml').write_text(
        '      MYSQL_ROOT_PASSWORD: "FromCompose"\n'
        '      MYSQL_PASSWORD: "UserFromCompose"\n'
    )
    creds = get_mysql_credentials('demo', containers_folder=str(tmp_path))
    assert creds['root_password'] == 'FromCompose'
    assert creds['password'] == 'UserFromCompose'


# ─── WordPress salts ────────────────────────────────────────────────────

_SALT_KEYS = (
    'AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY',
    'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT',
)


def _wp_config_for(tmp_path, name):
    from app.utils.project_utils import create_wordpress_base_files
    project = os.path.join(str(tmp_path), name)
    assert create_wordpress_base_files(project)
    with open(os.path.join(project, 'wp-config.php')) as handle:
        return handle.read()


def test_wp_config_has_no_placeholder_salts(tmp_path):
    """The placeholder salts are public; shipping them makes WordPress auth
    cookies forgeable on every site created through this path."""
    content = _wp_config_for(tmp_path, 'salted')
    assert 'put your unique phrase here' not in content
    assert '__WPL_' not in content, 'a substitution token was left unrendered'


def test_wp_config_salts_are_random_and_distinct(tmp_path):
    first = _wp_config_for(tmp_path, 'one')
    second = _wp_config_for(tmp_path, 'two')

    def salts(content):
        return {
            key: re.search(rf"define\('{key}',\s*'(.*)'\);", content).group(1)
            for key in _SALT_KEYS
        }

    a, b = salts(first), salts(second)
    assert len(set(a.values())) == len(_SALT_KEYS), 'salts repeat within one file'
    for key in _SALT_KEYS:
        assert len(a[key]) == 64
        assert a[key] != b[key], f'{key} identical across two projects'
