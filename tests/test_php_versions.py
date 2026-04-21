"""
Tests for the PHP versions source-of-truth module and the config
service/route integration with it.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import php_versions as pv


# ─── SUPPORTED list invariants ──────────────────────────────────────


def test_supported_list_is_non_empty_and_ordered():
    assert len(pv.SUPPORTED_PHP_VERSIONS) > 0
    # Every entry must be a plausible X.Y string (rejects typos).
    for v in pv.SUPPORTED_PHP_VERSIONS:
        parts = v.split('.')
        assert len(parts) == 2
        assert all(p.isdigit() for p in parts)


def test_default_is_in_supported():
    """Changing DEFAULT_PHP_VERSION to an unsupported string would
    break every new project — guard with a test."""
    assert pv.DEFAULT_PHP_VERSION in pv.SUPPORTED_PHP_VERSIONS


def test_retired_versions_are_absent():
    """PHP 8.0/8.1 were never actually built (phantom options in the
    dropdown); 8.2 was dropped in the April 2026 cleanup. They must
    stay out of the supported list so the UI never proposes them."""
    for retired in ('8.0', '8.1', '8.2'):
        assert retired not in pv.SUPPORTED_PHP_VERSIONS


def test_current_supported_covers_8_5():
    """Regression guard for the 2026-04-21 change: PHP 8.5 must be
    available to users."""
    assert '8.5' in pv.SUPPORTED_PHP_VERSIONS


# ─── helpers ────────────────────────────────────────────────────────


def test_is_supported_true_and_false():
    assert pv.is_supported(pv.DEFAULT_PHP_VERSION) is True
    assert pv.is_supported('garbage') is False
    assert pv.is_supported('8.0') is False  # phantom


def test_image_tag_uses_prefix():
    assert pv.image_tag('8.4') == 'wp-launcher-wordpress:php8.4'
    assert pv.image_tag('8.5') == 'wp-launcher-wordpress:php8.5'


def test_docker_image_exists_handles_missing_binary():
    with patch('app.config.php_versions.subprocess.run',
               side_effect=FileNotFoundError):
        assert pv.docker_image_exists('8.4') is None


def test_docker_image_exists_success_and_failure():
    with patch('app.config.php_versions.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert pv.docker_image_exists('8.4') is True

        mock_run.return_value = MagicMock(returncode=1)
        assert pv.docker_image_exists('8.4') is False


def test_iter_for_build_pairs_version_to_dockerfile():
    pairs = list(pv.iter_for_build())
    assert len(pairs) == len(pv.SUPPORTED_PHP_VERSIONS)
    for (v, dockerfile), expected in zip(pairs, pv.SUPPORTED_PHP_VERSIONS):
        assert v == expected
        assert dockerfile == f'Dockerfile.php{expected}'


# ─── config_service integration ─────────────────────────────────────


def test_config_service_schema_uses_shared_list(tmp_path, monkeypatch):
    """The PHP dropdown options must come from SUPPORTED_PHP_VERSIONS
    — no hardcoded duplicate list."""
    from app.services.config_service import ConfigService
    svc = ConfigService()
    # Override tmp containers folder for isolation.
    svc.containers_folder = str(tmp_path)
    schema = svc.get_php_config_schema()
    assert schema['php_version']['options'] == list(pv.SUPPORTED_PHP_VERSIONS)
    assert schema['php_version']['default'] == pv.DEFAULT_PHP_VERSION


def test_config_service_schema_includes_legacy_version_for_existing_project(tmp_path):
    """A project still pinned to a retired version (e.g. 8.2) must
    keep that option visible so the admin can migrate at their own
    pace — not have it silently swapped."""
    from app.services.config_service import ConfigService
    svc = ConfigService()
    svc.containers_folder = str(tmp_path)
    project_dir = tmp_path / 'legacy-site'
    project_dir.mkdir()
    (project_dir / '.php_version').write_text('8.2\n')

    schema = svc.get_php_config_schema(project_name='legacy-site')
    assert '8.2' in schema['php_version']['options']


def test_config_service_get_php_version_falls_back_to_default(tmp_path):
    from app.services.config_service import ConfigService
    svc = ConfigService()
    svc.containers_folder = str(tmp_path)
    # Missing .php_version → DEFAULT.
    assert svc.get_php_version('missing-project') == pv.DEFAULT_PHP_VERSION


def test_config_service_get_php_version_returns_stored_value(tmp_path):
    from app.services.config_service import ConfigService
    svc = ConfigService()
    svc.containers_folder = str(tmp_path)
    project_dir = tmp_path / 'acme'
    project_dir.mkdir()
    (project_dir / '.php_version').write_text('7.4\n')
    assert svc.get_php_version('acme') == '7.4'


# ─── route-level validation ─────────────────────────────────────────


def test_validate_php_config_rejects_unsupported_version():
    from app.routes.config import _validate_php_config
    result = _validate_php_config({'php_version': '8.0'})  # phantom
    assert result['valid'] is False
    assert '8.0' in result['error'] or 'invalide' in result['error'].lower()


def test_validate_php_config_accepts_supported_with_image():
    from app.routes.config import _validate_php_config
    with patch('app.routes.config.docker_image_exists', return_value=True):
        result = _validate_php_config({'php_version': pv.DEFAULT_PHP_VERSION})
    assert result['valid'] is True
    assert result['config']['php_version'] == pv.DEFAULT_PHP_VERSION


def test_validate_php_config_blocks_supported_without_built_image():
    """Supported in the list, but image isn't built → must fail loud
    rather than trigger a rebuild that crashes the container."""
    from app.routes.config import _validate_php_config
    with patch('app.routes.config.docker_image_exists', return_value=False):
        result = _validate_php_config({'php_version': pv.DEFAULT_PHP_VERSION})
    assert result['valid'] is False
    assert 'build_wordpress_images' in result['error']


def test_validate_php_config_passes_when_docker_unreachable():
    """If we can't probe docker (binary missing / daemon down),
    we accept the version and let the rebuild path handle fallout
    rather than hard-blocking valid configs."""
    from app.routes.config import _validate_php_config
    with patch('app.routes.config.docker_image_exists', return_value=None):
        result = _validate_php_config({'php_version': pv.DEFAULT_PHP_VERSION})
    assert result['valid'] is True
