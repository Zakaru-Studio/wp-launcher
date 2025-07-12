#!/bin/bash

echo "🚀 Installation de Traefik"
echo "=========================="

# Vérifier Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    exit 1
fi

# Vérifier Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose n'est pas installé"
    exit 1
fi

# Créer le réseau Traefik
echo "🌐 Création du réseau Traefik..."
docker network create traefik-network 2>/dev/null || echo "ℹ️ Le réseau traefik-network existe déjà"

# Arrêter Traefik s'il est en cours d'exécution
echo "🛑 Arrêt de l'instance Traefik existante..."
docker-compose down 2>/dev/null || true

# Vérifier les permissions d'acme.json
echo "🔒 Vérification des permissions d'acme.json..."
chmod 600 acme.json

# Démarrer Traefik
echo "🚀 Démarrage de Traefik..."
docker-compose up -d

# Attendre que Traefik soit prêt
echo "⏳ Attente du démarrage de Traefik..."
sleep 5

# Vérifier le statut
if docker ps | grep -q traefik; then
    echo "✅ Traefik est en cours d'exécution"
    echo "🌐 Dashboard disponible sur: http://localhost:8080"
    echo "🔒 Dashboard sécurisé sur: https://traefik.dev.akdigital.fr"
    echo "📋 Utilisateur: admin | Mot de passe: admin"
else
    echo "❌ Erreur lors du démarrage de Traefik"
    docker-compose logs traefik
    exit 1
fi

echo ""
echo "🎉 Installation terminée avec succès!"
echo "ℹ️ Traefik est maintenant prêt à proxifier vos services" 