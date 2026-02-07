#!/bin/bash

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Construction des images WordPress multi-versions PHP        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

cd /home/dev-server/Sites/wp-launcher/docker-template/wordpress

# PHP 7.4
echo "📦 Construction de l'image PHP 7.4..."
docker build -t wp-launcher-wordpress:php7.4 -f Dockerfile.php7.4 . || {
    echo "❌ Erreur construction PHP 7.4"
    exit 1
}
echo "✅ PHP 7.4 construit avec succès"
echo ""

# PHP 8.2 (latest - existant)
echo "📦 Construction de l'image PHP 8.2 (latest)..."
docker build -t wp-launcher-wordpress:php8.2 -t wp-launcher-wordpress:latest -f Dockerfile . || {
    echo "❌ Erreur construction PHP 8.2"
    exit 1
}
echo "✅ PHP 8.2 construit avec succès"
echo ""

# PHP 8.3
echo "📦 Construction de l'image PHP 8.3..."
docker build -t wp-launcher-wordpress:php8.3 -f Dockerfile.php8.3 . || {
    echo "❌ Erreur construction PHP 8.3"
    exit 1
}
echo "✅ PHP 8.3 construit avec succès"
echo ""

# PHP 8.4
echo "📦 Construction de l'image PHP 8.4..."
docker build -t wp-launcher-wordpress:php8.4 -f Dockerfile.php8.4 . || {
    echo "❌ Erreur construction PHP 8.4"
    exit 1
}
echo "✅ PHP 8.4 construit avec succès"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Images WordPress disponibles :"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker images | grep wp-launcher-wordpress | awk '{printf "%-40s %10s\n", $1":"$2, $7" "$8}'
echo ""
echo "✅ Toutes les images sont construites et prêtes à l'emploi !"






