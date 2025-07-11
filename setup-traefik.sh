#!/bin/bash

echo "🚀 Migration vers Traefik - WordPress Launcher"
echo "============================================="

# Vérifier que nous sommes dans le bon répertoire
if [ ! -f "app.py" ]; then
    echo "❌ Erreur: Ce script doit être exécuté depuis le répertoire wp-launcher"
    exit 1
fi

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

echo "📋 Étape 1: Installation de Traefik"
echo "-----------------------------------"

# Installer Traefik
cd traefik
if [ -f "install.sh" ]; then
    echo "🔧 Installation de Traefik..."
    chmod +x install.sh
    ./install.sh
    if [ $? -eq 0 ]; then
        echo "✅ Traefik installé avec succès"
    else
        echo "❌ Erreur lors de l'installation de Traefik"
        exit 1
    fi
else
    echo "❌ Fichier install.sh non trouvé dans le répertoire traefik"
    exit 1
fi

cd ..

echo ""
echo "📋 Étape 2: Arrêt de Nginx Proxy Manager (si présent)"
echo "---------------------------------------------------"

# Arrêter nginx-proxy-manager s'il existe
if docker ps | grep -q nginx-proxy-manager; then
    echo "🛑 Arrêt de Nginx Proxy Manager..."
    docker stop nginx-proxy-manager 2>/dev/null || true
    docker rm nginx-proxy-manager 2>/dev/null || true
    echo "✅ Nginx Proxy Manager arrêté"
else
    echo "ℹ️ Nginx Proxy Manager n'est pas en cours d'exécution"
fi

echo ""
echo "📋 Étape 3: Mise à jour des projets existants"
echo "-------------------------------------------"

# Mettre à jour les projets existants pour utiliser le réseau Traefik
if [ -d "containers" ]; then
    for project in containers/*/; do
        if [ -d "$project" ]; then
            project_name=$(basename "$project")
            echo "🔄 Mise à jour du projet: $project_name"
            
            # Arrêter le projet
            cd "$project"
            docker-compose down 2>/dev/null || true
            
            # Redémarrer le projet pour appliquer les nouveaux réseaux
            docker-compose up -d 2>/dev/null || true
            
            cd - > /dev/null
            echo "✅ Projet $project_name mis à jour"
        fi
    done
else
    echo "ℹ️ Aucun projet existant trouvé"
fi

echo ""
echo "📋 Étape 4: Vérification finale"
echo "-------------------------------"

# Vérifier que Traefik est en cours d'exécution
if docker ps | grep -q traefik; then
    echo "✅ Traefik est en cours d'exécution"
    
    # Vérifier que le réseau existe
    if docker network ls | grep -q traefik-network; then
        echo "✅ Réseau traefik-network créé"
    else
        echo "⚠️ Réseau traefik-network non trouvé"
    fi
    
    # Afficher les informations de connexion
    echo ""
    echo "🎉 Migration terminée avec succès!"
    echo "================================="
    echo "🌐 Dashboard Traefik (local): http://localhost:8080"
    echo "🔒 Dashboard Traefik (sécurisé): https://traefik.dev.akdigital.fr"
    echo "📋 Utilisateur: admin | Mot de passe: admin"
    echo ""
    echo "ℹ️ Redémarrez WordPress Launcher pour utiliser Traefik:"
    echo "   python3 app.py"
    echo ""
    echo "📚 Documentation: traefik/README.md"
    
else
    echo "❌ Traefik n'est pas en cours d'exécution"
    echo "Vérifiez les logs: cd traefik && docker-compose logs traefik"
    exit 1
fi

echo ""
echo "🔧 Nettoyage recommandé"
echo "======================="
echo "Si vous n'utilisez plus Nginx Proxy Manager, vous pouvez:"
echo "• Supprimer les volumes: docker volume prune"
echo "• Supprimer les images: docker image prune -a"
echo "• Supprimer les fichiers de configuration NPM (si présents)" 