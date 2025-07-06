#!/bin/bash

# Script pour résoudre les conflits de ports entre GitLab et WordPress
echo "🔧 Résolution des conflits de ports GitLab/WordPress"
echo "===================================================="

# Vérifier les conteneurs actifs
echo "🔍 Vérification des conteneurs actifs..."
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" | grep -E "(gitlab|wordpress)"

echo ""
echo "📋 Solutions disponibles :"
echo "1. Accéder aux sites WordPress via hostname:8080"
echo "2. Configurer Traefik comme reverse proxy"
echo "3. Changer le port de GitLab"
echo "4. Utiliser des sous-domaines différents"
echo ""

read -p "Choisissez une solution (1-4) : " choice

case $choice in
    1)
        echo "✅ Solution 1 : Accès via port 8080"
        echo "Pour accéder à vos sites WordPress, utilisez :"
        echo "  - http://eurasiapeace.local:8080"
        echo "  - http://[hostname]:8080"
        echo ""
        echo "💡 L'interface WP Launcher a été mise à jour pour ouvrir automatiquement les sites sur le port 8080"
        ;;
    2)
        echo "🔧 Solution 2 : Configuration de Traefik"
        echo "Installation de Traefik comme reverse proxy..."
        
        # Créer un fichier docker-compose pour Traefik
        cat > traefik-docker-compose.yml << 'EOF'
version: '3.8'

services:
  traefik:
    image: traefik:v3.0
    container_name: traefik
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:8080"
      - "--entrypoints.wordpress.address=:8081"
    ports:
      - "8080:8080"  # Traefik dashboard
      - "8081:8081"  # WordPress sites
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - traefik_network
    restart: unless-stopped

networks:
  traefik_network:
    external: true

EOF
        
        # Créer le réseau Traefik
        docker network create traefik_network 2>/dev/null || true
        
        echo "📁 Fichier traefik-docker-compose.yml créé"
        echo "🚀 Pour démarrer Traefik : docker-compose -f traefik-docker-compose.yml up -d"
        echo "🌐 Dashboard Traefik : http://localhost:8080"
        echo "📝 Vous devrez ensuite modifier vos docker-compose.yml pour utiliser Traefik"
        ;;
    3)
        echo "🔧 Solution 3 : Changer le port de GitLab"
        echo "Pour changer le port de GitLab :"
        echo "1. Arrêter GitLab : docker stop gitlab"
        echo "2. Modifier la configuration pour utiliser le port 8083 au lieu de 80"
        echo "3. Redémarrer GitLab"
        echo ""
        echo "⚠️ Attention : Cela peut nécessiter de reconfigurer GitLab"
        
        read -p "Voulez-vous changer le port de GitLab maintenant ? (y/n) : " change_gitlab
        if [[ $change_gitlab == "y" || $change_gitlab == "Y" ]]; then
            echo "🛑 Arrêt de GitLab..."
            docker stop gitlab 2>/dev/null || echo "GitLab n'est pas en cours d'exécution"
            echo "💡 Vous devez maintenant modifier la configuration de GitLab pour utiliser le port 8083"
            echo "   puis redémarrer avec : docker start gitlab"
        fi
        ;;
    4)
        echo "🔧 Solution 4 : Sous-domaines différents"
        echo "Configuration de sous-domaines pour éviter les conflits..."
        
        # Ajouter des entrées /etc/hosts pour différents sous-domaines
        echo "📝 Ajout d'entrées /etc/hosts..."
        
        # Backup du fichier hosts
        sudo cp /etc/hosts /etc/hosts.backup.$(date +%Y%m%d_%H%M%S)
        
        # Ajouter les entrées
        echo "127.0.0.1    wp.local" | sudo tee -a /etc/hosts
        echo "127.0.0.1    gitlab.local" | sudo tee -a /etc/hosts
        
        echo "✅ Entrées ajoutées :"
        echo "  - http://wp.local:8080 → WordPress"
        echo "  - http://gitlab.local → GitLab"
        echo "  - http://eurasiapeace.local:8080 → WordPress eurasiapeace"
        ;;
    *)
        echo "❌ Choix invalide"
        exit 1
        ;;
esac

echo ""
echo "🎯 Résumé des accès :"
echo "====================="
echo "GitLab : http://localhost (port 80)"
echo "WordPress : http://[hostname]:8080"
echo "Portainer : http://localhost:9443"
echo ""
echo "💡 Conseil : Utilisez des hostnames différents pour éviter les conflits"
echo "   Exemple : gitlab.local, wp.local, site1.local, etc."
echo ""
echo "✅ Configuration terminée !" 