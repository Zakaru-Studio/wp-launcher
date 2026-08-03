"""
Single source of truth for PHP version support in wp-launcher.

Ajouter / retirer une version :
  1. Mettre à jour ``SUPPORTED_PHP_VERSIONS`` ci-dessous.
  2. Si nouvelle version : ajouter ``docker-template/wordpress/Dockerfile.phpX.Y``
     héritant de ``wordpress:phpX.Y-apache``, puis relancer
     ``scripts/build_wordpress_images.sh``.
  3. Tests : ``tests/test_php_versions.py`` est paramétré sur la liste.

Les services et routes doivent importer ``SUPPORTED_PHP_VERSIONS`` /
``DEFAULT_PHP_VERSION`` d'ici plutôt que de hardcoder la liste — les
versions dérivées (fallback, validation, dropdown UI) suivront
automatiquement.
"""
from __future__ import annotations

import subprocess
from typing import Iterable, Optional


# Ordered list from oldest to newest — the UI renders the dropdown in
# this order and the latest element is what we pick when a legacy
# site can't keep its current version (e.g. the stored version was
# removed).
#
# PHP 7.4 kept for legacy sites only; WP recommends PHP 8.1+. 8.2 was
# removed on 2026-04-21 in favour of 8.4/8.5 (8.2 EOL is 2026-12-31).
SUPPORTED_PHP_VERSIONS: tuple[str, ...] = ('7.4', '8.3', '8.4', '8.5')

# Version des nouveaux projets, et repli quand ``.php_version`` est absent
# ou illisible.
#
# Dérivée de la liste plutôt que codée en dur : la liste est ordonnée de la
# plus ancienne à la plus récente, donc le dernier élément est la dernière
# version stable qu'on supporte. Ajouter '8.6' à SUPPORTED_PHP_VERSIONS suffit
# à ce que les nouveaux sites l'utilisent, sans toucher à cette ligne — c'est
# précisément l'oubli qui avait laissé les créations sur 8.4 alors que l'image
# 8.5 existait déjà.
DEFAULT_PHP_VERSION: str = SUPPORTED_PHP_VERSIONS[-1]

# Image name prefix. The full tag is ``{PREFIX}:php{version}``.
IMAGE_PREFIX: str = 'wp-launcher-wordpress'


def is_supported(version: str) -> bool:
    """True if ``version`` is one we ship a Docker image for."""
    return version in SUPPORTED_PHP_VERSIONS


def image_tag(version: str) -> str:
    """Return the Docker tag we expect for a given PHP version."""
    return f"{IMAGE_PREFIX}:php{version}"


def docker_image_exists(version: str, timeout: int = 5) -> Optional[bool]:
    """Check that the image for ``version`` is available locally.

    Returns True / False, or None if the check itself couldn't run
    (docker binary missing, daemon down). Callers decide how to
    interpret None — usually "best effort, assume it works".
    """
    tag = image_tag(version)
    try:
        result = subprocess.run(
            ['docker', 'image', 'inspect', tag],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return result.returncode == 0


def iter_for_build() -> Iterable[tuple[str, str]]:
    """Yield (version, dockerfile_suffix) pairs for the build script.

    The earliest supported version uses the bare ``Dockerfile`` (no
    suffix); every other version has a ``Dockerfile.php{version}``.
    """
    for idx, version in enumerate(SUPPORTED_PHP_VERSIONS):
        # Historically the bare Dockerfile was PHP 8.2; that's gone,
        # so all versions now use an explicit Dockerfile.phpX.Y file.
        yield version, f'Dockerfile.php{version}'


def resolve_default_php_version() -> str:
    """Version PHP à utiliser pour un nouveau projet.

    ``DEFAULT_PHP_VERSION`` est la dernière version supportée, mais son image
    peut ne pas avoir été construite sur cette machine : Docker créerait alors
    le conteneur puis boucherait indéfiniment à tenter de tirer une image
    inexistante. On redescend donc vers la plus récente réellement disponible.

    Si la vérification elle-même est impossible (démon arrêté, binaire absent),
    ``docker_image_exists`` renvoie None et on garde la version la plus
    récente — best effort, la création signalera l'erreur d'elle-même.
    """
    for version in reversed(SUPPORTED_PHP_VERSIONS):
        available = docker_image_exists(version)
        if available or available is None:
            return version
    return DEFAULT_PHP_VERSION
