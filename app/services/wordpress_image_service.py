#!/usr/bin/env python3
"""
Service pour vérifier et construire automatiquement l'image WordPress personnalisée
"""

import re
import subprocess
from pathlib import Path

from app.config.php_versions import DEFAULT_PHP_VERSION, IMAGE_PREFIX

# `image: wp-launcher-wordpress:<tag>` dans un docker-compose.yml de projet.
_IMAGE_RE = re.compile(r'^\s*image:\s*(' + re.escape(IMAGE_PREFIX) + r':\S+)\s*$', re.M)


class WordPressImageService:
    """Service de gestion de l'image Docker WordPress personnalisée"""

    def __init__(self):
        self.image_name = f'{IMAGE_PREFIX}:latest'
        self.dockerfile_path = 'docker-template/wordpress'

    @staticmethod
    def php_version_for_tag(tag):
        """Version PHP portée par un tag.

        ``:latest`` suit la version par défaut déclarée dans php_versions —
        c'est ce que produit build_wordpress_images.sh, qui pose les deux tags
        sur la même image.
        """
        suffix = tag.split(':', 1)[1] if ':' in tag else 'latest'
        if suffix == 'latest':
            return DEFAULT_PHP_VERSION
        return suffix[3:] if suffix.startswith('php') else suffix

    def dockerfile_for_tag(self, tag):
        """Chemin du Dockerfile qui produit ``tag``.

        L'ancienne implémentation bâtissait toujours ``Dockerfile`` (générique)
        quel que soit le tag posé : l'image pouvait donc annoncer php8.5 tout en
        embarquant la version du Dockerfile par défaut. On cible désormais le
        ``Dockerfile.phpX.Y`` correspondant.
        """
        version = self.php_version_for_tag(tag)
        return Path(self.dockerfile_path) / f'Dockerfile.php{version}', version

    @staticmethod
    def image_tags_in_compose(compose_file):
        """Tags d'images locales référencés par un docker-compose.yml."""
        try:
            content = Path(compose_file).read_text()
        except OSError:
            return []
        return sorted(set(_IMAGE_RE.findall(content)))

    def check_image_exists(self, image_name=None):
        """Vérifie qu'une image locale existe (par défaut ``:latest``)."""
        image_name = image_name or self.image_name
        try:
            # `docker image inspect` est exact ; `docker images <nom>` filtre sur
            # le dépôt et renvoyait un résultat non vide pour un tag absent dès
            # qu'un autre tag du même dépôt existait.
            result = subprocess.run(
                ['docker', 'image', 'inspect', image_name],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Erreur lors de la vérification de l'image: {e}")
            return False

    def build_wordpress_image(self, image_name=None):
        """Construit l'image WordPress correspondant à ``image_name``."""
        image_name = image_name or self.image_name
        try:
            print(f"🚀 Construction de l'image {image_name}...")

            dockerfile, version = self.dockerfile_for_tag(image_name)
            if not dockerfile.exists():
                print(
                    f"❌ Dockerfile non trouvé: {dockerfile} — PHP {version} n'est "
                    "peut-être plus supporté (voir app/config/php_versions.py)."
                )
                return False

            # `--pull` pour repartir d'une image de base à jour, comme le fait
            # scripts/build_wordpress_images.sh : sans lui une reconstruction
            # pouvait ressortir un WordPress plus ancien que celui déployé.
            cmd = ['docker', 'build', '--pull', '-t', image_name]
            # Le tag de la version par défaut porte aussi `:latest`, exactement
            # comme le script, pour que les deux reposent sur la même image.
            if version == DEFAULT_PHP_VERSION and image_name != f'{IMAGE_PREFIX}:latest':
                cmd += ['-t', f'{IMAGE_PREFIX}:latest']
            cmd += ['-f', dockerfile.name, '.']

            # cwd= plutôt qu'un os.chdir : le répertoire courant est partagé par
            # tout le processus, et une opération concurrente le déplaçait sous
            # nos pieds (cf. DockerService._compose).
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=900,
                cwd=self.dockerfile_path,
            )

            if result.returncode == 0:
                print(f"✅ Image {image_name} construite avec succès!")
                return self.test_wp_cli_in_image(image_name)
            else:
                print(f"❌ Erreur lors de la construction de l'image:")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")
                return False

        except Exception as e:
            print(f"❌ Erreur lors de la construction de l'image: {e}")
            return False

    def test_wp_cli_in_image(self, image_name=None):
        """Teste WP-CLI dans l'image construite selon les recommandations officielles"""
        image_name = image_name or self.image_name
        try:
            print(f"🧪 Test de WP-CLI dans {image_name}...")
            # Utiliser docker-entrypoint.sh directement pour éviter notre script personnalisé
            result = subprocess.run([
                'docker', 'run', '--rm', '--entrypoint', 'wp',
                image_name,
                '--info', '--allow-root'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print("✅ WP-CLI fonctionne correctement:")
                for line in result.stdout.strip().split('\n'):
                    if 'WP-CLI version' in line or 'PHP version' in line or 'OS:' in line:
                        print(f"   {line}")
                return True
            else:
                print(f"❌ WP-CLI ne fonctionne pas: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Erreur lors du test WP-CLI: {e}")
            return False

    def ensure_wordpress_image(self, image_name=None, compose_file=None):
        """S'assure que l'image WordPress attendue existe, en la construisant au besoin.

        ``compose_file`` permet de viser le tag réellement référencé par un
        projet (php8.4, php8.5…) plutôt que de supposer ``:latest``, qui ne
        couvrait pas les projets épinglés sur une version.
        """
        if image_name is None and compose_file is not None:
            tags = self.image_tags_in_compose(compose_file)
            image_name = tags[0] if tags else None
        image_name = image_name or self.image_name

        print(f"🔍 Vérification de l'image {image_name}...")

        if self.check_image_exists(image_name):
            print(f"✅ Image {image_name} déjà disponible")
            # Tester WP-CLI même si l'image existe déjà
            return self.test_wp_cli_in_image(image_name)

        print(f"⚠️ Image {image_name} non trouvée")
        return self.build_wordpress_image(image_name)


# Fonctions pour la rétrocompatibilité
def check_image_exists(image_name=None):
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.check_image_exists(image_name)

def build_wordpress_image(image_name=None):
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.build_wordpress_image(image_name)

def test_wp_cli_in_image(image_name=None):
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.test_wp_cli_in_image(image_name)

def ensure_wordpress_image(image_name=None, compose_file=None):
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.ensure_wordpress_image(image_name, compose_file)


if __name__ == "__main__":
    import sys
    service = WordPressImageService()
    success = service.ensure_wordpress_image()
    sys.exit(0 if success else 1)

