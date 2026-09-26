"""
Tests around locally-built WordPress images.

Ces images ne vivent sur aucun registre : elles sont produites par
``scripts/build_wordpress_images.sh`` et partagées par tous les projets.
Quand elles manquent, Compose partait les chercher sur Docker Hub et
retournait « pull access denied […] may require 'docker login' », un
message qui envoie chercher un problème d'authentification inexistant.
Ces tests verrouillent le garde-fou et la résolution tag → Dockerfile.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from app.config import php_versions as pv
from app.services.docker_service import DockerService
from app.services.wordpress_image_service import WordPressImageService


COMPOSE_PINNED = "services:\n  wordpress:\n    image: wp-launcher-wordpress:php8.3\n"
COMPOSE_LATEST = "services:\n  wordpress:\n    image: wp-launcher-wordpress:latest\n"
COMPOSE_HUB_ONLY = "services:\n  wordpress:\n    image: wordpress:latest\n"


@pytest.fixture
def project(tmp_path):
    """Fabrique un dossier de projet contenant un docker-compose.yml."""
    def _make(content):
        (tmp_path / 'docker-compose.yml').write_text(content)
        return str(tmp_path)
    return _make


@pytest.fixture
def service():
    # __new__ : les helpers testés ne dépendent d'aucun état d'instance.
    return DockerService.__new__(DockerService)


# ─── détection d'image locale absente ────────────────────────────────


def test_missing_local_image_returns_tag_when_absent(service, project):
    path = project(COMPOSE_PINNED)
    with patch('subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], returncode=1)
        assert service._missing_local_image(path) == 'wp-launcher-wordpress:php8.3'


def test_missing_local_image_returns_none_when_present(service, project):
    path = project(COMPOSE_PINNED)
    with patch('subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], returncode=0)
        assert service._missing_local_image(path) is None


def test_hub_images_are_not_guarded(service, project):
    """Les images officielles doivent rester téléchargeables : les signaler
    comme manquantes bloquerait un projet parfaitement valide."""
    path = project(COMPOSE_HUB_ONLY)
    with patch('subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], returncode=1)
        assert service._missing_local_image(path) is None
        run.assert_not_called()


def test_unreadable_compose_does_not_block(service, tmp_path):
    """Sans compose lisible, c'est à docker-compose de se plaindre."""
    assert service._missing_local_image(str(tmp_path)) is None


# ─── court-circuit du `up` ───────────────────────────────────────────


def test_compose_up_short_circuits_with_actionable_message(service, project):
    path = project(COMPOSE_PINNED)
    with patch.object(service, '_missing_local_image', return_value='wp-launcher-wordpress:php8.3'):
        with patch('subprocess.run') as run:
            result = service._compose(path, 'up', '-d')
            run.assert_not_called()          # aucun pull tenté
    assert result.returncode == 1
    assert 'build_wordpress_images.sh' in result.stderr
    assert 'wp-launcher-wordpress:php8.3' in result.stderr


def test_compose_other_commands_are_not_guarded(service, project):
    """`down`, `logs`, `start`… n'ont pas besoin de l'image."""
    path = project(COMPOSE_PINNED)
    with patch.object(service, '_missing_local_image') as missing:
        with patch('subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], returncode=0)
            service._compose(path, 'down')
            missing.assert_not_called()
            run.assert_called_once()


# ─── résolution tag → Dockerfile ─────────────────────────────────────


def test_latest_follows_default_php_version():
    """`:latest` et le tag de la version par défaut désignent la même image —
    c'est ce que pose build_wordpress_images.sh."""
    assert WordPressImageService.php_version_for_tag(
        'wp-launcher-wordpress:latest') == pv.DEFAULT_PHP_VERSION


@pytest.mark.parametrize('version', pv.SUPPORTED_PHP_VERSIONS)
def test_each_supported_version_maps_to_its_dockerfile(version):
    svc = WordPressImageService()
    dockerfile, resolved = svc.dockerfile_for_tag(pv.image_tag(version))
    assert resolved == version
    assert dockerfile.name == f'Dockerfile.php{version}'
    # Une version supportée sans Dockerfile ne se construirait jamais.
    assert dockerfile.exists(), f"{dockerfile} manquant pour une version supportée"


def test_image_tags_in_compose_reads_pinned_tag(project):
    svc = WordPressImageService()
    assert svc.image_tags_in_compose(
        f"{project(COMPOSE_LATEST)}/docker-compose.yml"
    ) == ['wp-launcher-wordpress:latest']


def test_ensure_uses_tag_from_compose(project):
    """Le projet est épinglé sur php8.3 : c'est ce tag qu'il faut vérifier,
    pas `:latest` — la version supposée par l'ancienne implémentation."""
    svc = WordPressImageService()
    compose = f"{project(COMPOSE_PINNED)}/docker-compose.yml"
    with patch.object(svc, 'check_image_exists', return_value=True) as check:
        with patch.object(svc, 'test_wp_cli_in_image', return_value=True):
            svc.ensure_wordpress_image(compose_file=compose)
    check.assert_called_once_with('wp-launcher-wordpress:php8.3')
