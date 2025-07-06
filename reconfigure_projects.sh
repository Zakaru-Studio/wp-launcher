#!/bin/bash

# Script pour reconfigurer les projets existants avec les nouvelles configurations
echo "🔧 Reconfiguration des projets existants"
echo "======================================="

# Vérifier que le dossier projets existe
if [ ! -d "projets" ]; then
    echo "❌ Dossier 'projets' non trouvé"
    exit 1
fi

# Parcourir tous les projets
for project_dir in projets/*/; do
    if [ -d "$project_dir" ]; then
        project_name=$(basename "$project_dir")
        echo ""
        echo "🔄 Reconfiguration du projet: $project_name"
        echo "----------------------------------------"
        
        # Aller dans le dossier du projet
        cd "$project_dir"
        
        # Vérifier si docker-compose.yml existe
        if [ ! -f "docker-compose.yml" ]; then
            echo "⚠️ Fichier docker-compose.yml manquant, ignoré"
            cd - > /dev/null
            continue
        fi
        
        # Arrêter les conteneurs
        echo "🛑 Arrêt des conteneurs..."
        docker-compose down -v --remove-orphans
        
        # Supprimer l'ancien docker-compose.yml
        echo "🗑️ Suppression de l'ancienne configuration..."
        rm -f docker-compose.yml
        
        # Créer les dossiers de configuration s'ils n'existent pas
        echo "📁 Création des dossiers de configuration..."
        mkdir -p php-config
        mkdir -p mysql-config
        
        # Copier les nouvelles configurations
        echo "📋 Copie des nouvelles configurations..."
        cp ../../docker-template/docker-compose.yml .
        cp ../../docker-template/php-config/php.ini php-config/
        cp ../../docker-template/mysql-config/mysql.cnf mysql-config/
        
        # Remplacer PROJECT_NAME dans docker-compose.yml
        echo "⚙️ Configuration du nom de projet..."
        sed -i "s/PROJECT_NAME/${project_name}/g" docker-compose.yml
        
        # Relancer les conteneurs
        echo "🚀 Relancement des conteneurs..."
        docker-compose up -d
        
        echo "✅ Projet $project_name reconfiguré"
        
        # Retourner au dossier racine
        cd - > /dev/null
    fi
done

echo ""
echo "✅ Reconfiguration terminée"
echo "📊 Nouveaux paramètres:"
echo "  - Mémoire PHP: 1024M"
echo "  - Mémoire MySQL: 512M"
echo "  - Timeout d'exécution: 600s"
echo "  - Max packet size: 1024M"
echo "  - Logs de debug activés"
echo ""
echo "💡 Vous pouvez maintenant tester l'import de vos bases de données" 