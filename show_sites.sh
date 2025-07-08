#!/bin/bash

echo "🌐 ===== WP LAUNCHER - ACCÈS DIRECT AUX SITES ====="
echo ""

# Obtenir l'IP locale
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo "📡 Adresse IP locale : $LOCAL_IP"
echo ""

# Afficher le WP Launcher
echo "🚀 WP LAUNCHER INTERFACE :"
echo "   └─ Interface principale : http://$LOCAL_IP:5000"
echo ""

# Lister les conteneurs actifs
echo "🚀 SITES ACTIFS :"
echo "=================="

# Conteneurs WordPress
for container in $(docker ps --format "table {{.Names}}" | grep "_wordpress_"); do
    project=$(echo $container | cut -d'_' -f1)
    port=$(docker port $container 80/tcp | cut -d':' -f2)
    echo "📝 $project (WordPress) :"
    echo "   └─ Site : http://$LOCAL_IP:$port"
    echo "   └─ Admin : http://$LOCAL_IP:$port/wp-admin"
    echo ""
done

# Conteneurs Next.js
for container in $(docker ps --format "table {{.Names}}" | grep "_nextjs_"); do
    project=$(echo $container | cut -d'_' -f1)
    port=$(docker port $container 3000/tcp | cut -d':' -f2)
    echo "⚡ $project (Next.js) :"
    echo "   └─ Frontend : http://$LOCAL_IP:$port"
    echo ""
done

# Conteneurs phpMyAdmin
for container in $(docker ps --format "table {{.Names}}" | grep "_phpmyadmin_"); do
    project=$(echo $container | cut -d'_' -f1)
    port=$(docker port $container 80/tcp | cut -d':' -f2)
    echo "🗄️ $project (phpMyAdmin) :"
    echo "   └─ Database : http://$LOCAL_IP:$port"
    echo ""
done

# Conteneurs Mailpit
for container in $(docker ps --format "table {{.Names}}" | grep "_mailpit_"); do
    project=$(echo $container | cut -d'_' -f1)
    port=$(docker port $container 8025/tcp | cut -d':' -f2)
    echo "📧 $project (Mailpit) :"
    echo "   └─ Emails : http://$LOCAL_IP:$port"
    echo ""
done

echo ""
echo "💡 ACCÈS EXTERNE (depuis mobile/autres appareils) :"
echo "====================================================="
echo "   Utilisez la même IP : $LOCAL_IP"
echo "   Exemple : http://$LOCAL_IP:8080 (WordPress)"
echo "   Exemple : http://$LOCAL_IP:8085 (Next.js)"
echo ""
echo "✅ AVANTAGES ACCÈS DIRECT :"
echo "============================"
echo "   - Pas de configuration DNS/hosts"
echo "   - Accès rapide et direct"
echo "   - Pas de reverse proxy"
echo "   - Compatible tous appareils du réseau"
echo "" 