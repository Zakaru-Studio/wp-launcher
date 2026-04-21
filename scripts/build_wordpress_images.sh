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
cd "$REPO_ROOT"
mapfile -t PY_OUT < <(python3 -c 'import sys; sys.path.insert(0, "."); from app.config.php_versions import SUPPORTED_PHP_VERSIONS, DEFAULT_PHP_VERSION; print(" ".join(SUPPORTED_PHP_VERSIONS)); print(DEFAULT_PHP_VERSION)')
read -ra SUPPORTED_VERSIONS <<< "${PY_OUT[0]}"
DEFAULT_VERSION="${PY_OUT[1]}"

if [ $# -gt 0 ]; then
    SUPPORTED_VERSIONS=("$@")
fi

echo "→ Versions à construire : ${SUPPORTED_VERSIONS[*]}"
echo "→ Default (taggée aussi :latest) : $DEFAULT_VERSION"
echo ""

cd "$WP_DIR"

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
    docker build "${tags[@]}" -f "$dockerfile" . || {
        echo "❌ Erreur construction PHP $version"
        exit 1
    }
    echo "✅ PHP $version construit avec succès"
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Images WordPress disponibles :"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep wp-launcher-wordpress || true
echo ""
echo "✅ Toutes les images sont construites et prêtes à l'emploi !"
