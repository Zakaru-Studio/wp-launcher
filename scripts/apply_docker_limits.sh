#!/bin/bash
# Script pour appliquer les nouvelles limites Docker aux projets actifs
# Usage: ./apply_docker_limits.sh [project_name]
# Sans argument: applique à tous les projets actifs

set -e

CONTAINERS_DIR="/home/dev-server/Sites/wp-launcher/containers"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Application des nouvelles limites Docker optimisées         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Si un projet spécifique est fourni
if [ -n "$1" ]; then
    PROJECT="$1"
    echo "🔄 Application des limites pour: $PROJECT"
    cd "$CONTAINERS_DIR/$PROJECT"
    
    if [ ! -f "docker-compose.yml" ]; then
        echo "❌ Erreur: docker-compose.yml non trouvé pour $PROJECT"
        exit 1
    fi
    
    echo "  ⏸️  Arrêt des conteneurs..."
    docker-compose down
    
    echo "  🚀 Redémarrage avec nouvelles limites..."
    docker-compose up -d
    
    echo "  ✅ Limites appliquées pour $PROJECT"
    echo ""
    docker-compose ps
    
else
    # Appliquer à tous les projets actifs
    echo "🔍 Détection des projets actifs..."
    ACTIVE_PROJECTS=$(docker ps --format "{{.Names}}" | sed 's/_.*//g' | sort -u)
    
    if [ -z "$ACTIVE_PROJECTS" ]; then
        echo "ℹ️  Aucun projet actif détecté"
        exit 0
    fi
    
    echo "📋 Projets actifs détectés:"
    echo "$ACTIVE_PROJECTS" | while read project; do
        echo "  - $project"
    done
    echo ""
    
    read -p "⚠️  Appliquer les nouvelles limites à ces projets? (y/N) " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Opération annulée"
        exit 0
    fi
    
    echo ""
    echo "$ACTIVE_PROJECTS" | while read project; do
        if [ -d "$CONTAINERS_DIR/$project" ]; then
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "🔄 Application pour: $project"
            cd "$CONTAINERS_DIR/$project"
            
            echo "  ⏸️  Arrêt..."
            docker-compose down
            
            echo "  🚀 Redémarrage..."
            docker-compose up -d
            
            echo "  ✅ Terminé"
            echo ""
        fi
    done
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Toutes les limites ont été appliquées!"
    echo ""
    echo "📊 État des conteneurs:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
fi

echo ""
echo "💡 Vérifiez l'utilisation mémoire avec: docker stats --no-stream"


