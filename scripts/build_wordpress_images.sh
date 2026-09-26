#!/bin/bash
# Build Docker images for every PHP version listed in
# app/config/php_versions.py::SUPPORTED_PHP_VERSIONS.
#
# Derives the version list at runtime so this script never drifts
# from the backend's view of what's supported.
#
# Usage:
#   ./scripts/build_wordpress_images.sh             # every supported version
#   ./scripts/build_wordpress_images.sh 8.4 8.5     # only those

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WP_DIR="$REPO_ROOT/docker-template/wordpress"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Construction des images WordPress multi-versions PHP         ║"
echo "╚════════════════════════════════════════════════════════════════╝"

if [ ! -d "$WP_DIR" ]; then
    echo "❌ Répertoire $WP_DIR introuvable."
    exit 1
fi

# Pull supported versions + default from the Python source of truth.
#
# `app/config/php_versions.py` est un module feuille, mais l'importer par son
# paquet traverse `app/__init__.py`, qui charge Flask : hors venv l'import
# échouait, `mapfile` ne renvoyait rien, et le script mourait sur « variable
# sans liaison » sans jamais dire que le venv manquait. On charge donc le
# fichier directement, et on privilégie le python du venv s'il existe.
cd "$REPO_ROOT"
PY="${PYTHON:-python3}"
if [ -x "$REPO_ROOT/venv/bin/python" ]; then
    PY="$REPO_ROOT/venv/bin/python"
fi

READER='
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location(
    "php_versions", pathlib.Path("app/config/php_versions.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(" ".join(mod.SUPPORTED_PHP_VERSIONS))
print(mod.DEFAULT_PHP_VERSION)
'

if ! mapfile -t PY_OUT < <("$PY" -c "$READER"); then
    echo "❌ Lecture de app/config/php_versions.py impossible avec $PY." >&2
    exit 1
fi

if [ "${#PY_OUT[@]}" -lt 2 ]; then
    echo "❌ Versions PHP illisibles — app/config/php_versions.py est-il intact ?" >&2
    exit 1
fi

read -ra SUPPORTED_VERSIONS <<< "${PY_OUT[0]}"
DEFAULT_VERSION="${PY_OUT[1]}"

if [ $# -gt 0 ]; then
    SUPPORTED_VERSIONS=("$@")
fi

echo "→ Versions à construire : ${SUPPORTED_VERSIONS[*]}"
echo "→ Default (taggée aussi :latest) : $DEFAULT_VERSION"
echo ""

cd "$WP_DIR"

FAILED=()

for version in "${SUPPORTED_VERSIONS[@]}"; do
    dockerfile="Dockerfile.php${version}"
    if [ ! -f "$dockerfile" ]; then
        echo "⚠️  $dockerfile manquant — skip PHP $version"
        continue
    fi
    echo "📦 PHP $version…"
    tags=(-t "wp-launcher-wordpress:php${version}")
    if [ "$version" = "$DEFAULT_VERSION" ]; then
        tags+=(-t "wp-launcher-wordpress:latest")
    fi
    # `--pull` est indispensable : sans lui, docker réutilise l'image de base
    # `wordpress:phpX.Y-apache` déjà en cache, qui peut dater de plusieurs
    # mois. Une reconstruction repartait alors d'un WordPress plus ancien que
    # celui déjà déployé, et la version n'avançait jamais.
    # Un `exit 1` ici faisait tomber toutes les versions suivantes dès que la
    # plus ancienne cassait — une image de base en fin de support (Debian
    # archivée) suffisait à ne plus rien produire du tout. On poursuit, et on
    # récapitule les échecs à la fin avec un code de sortie non nul.
    if docker build --pull "${tags[@]}" -f "$dockerfile" .; then
        echo "✅ PHP $version construit avec succès"
    else
        echo "❌ Erreur construction PHP $version — on continue avec les suivantes"
        FAILED+=("$version")
    fi
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Images WordPress disponibles :"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep wp-launcher-wordpress || true
echo ""
if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "⚠️  Versions en échec : ${FAILED[*]}"
    echo "   Les autres images restent utilisables ; relancez le script sur ces"
    echo "   versions une fois leur Dockerfile corrigé."
    exit 1
fi
echo "✅ Toutes les images sont construites et prêtes à l'emploi !"
