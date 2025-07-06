#!/bin/bash

# Script de nettoyage pour WP Launcher
echo "🧹 Nettoyage WP Launcher"
echo "======================="

echo "🔍 Recherche des projets défaillants..."

if [ -d "projets" ] && [ "$(ls -A projets)" ]; then
    for project in projets/*/; do
        if [ -d "$project" ]; then
            project_name=$(basename "$project")
            echo ""
            echo "📂 Vérification du projet: $project_name"
            
            cd "$project" 2>/dev/null || continue
            
            # Vérifier les conteneurs
            mysql_container="${project_name}_mysql_1"
            wp_container="${project_name}_wordpress_1"
            
            mysql_running=$(docker ps --format '{{.Names}}' | grep -c "$mysql_container" || echo 0)
            wp_running=$(docker ps --format '{{.Names}}' | grep -c "$wp_container" || echo 0)
            
            if [ "$mysql_running" -eq 0 ] && [ "$wp_running" -eq 0 ]; then
                echo "  ⚠️  Conteneurs arrêtés"
                
                # Demander confirmation pour nettoyer
                read -p "  🗑️  Supprimer ce projet défaillant? (y/N): " -n 1 -r
                echo
                
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    echo "  🧹 Nettoyage en cours..."
                    
                    # Arrêter et supprimer les conteneurs
                    docker-compose down -v 2>/dev/null
                    
                    # Supprimer les images liées
                    docker rmi $(docker images -q --filter "reference=*${project_name}*") 2>/dev/null
                    
                    # Supprimer le dossier du projet
                    cd - > /dev/null
                    rm -rf "$project"
                    
                    echo "  ✅ Projet $project_name supprimé"
                else
                    echo "  ⏭️  Projet $project_name conservé"
                fi
            else
                echo "  ✅ Conteneurs actifs"
            fi
            
            cd - > /dev/null
        fi
    done
else
    echo "📂 Aucun projet trouvé"
fi

echo ""
echo "🧹 Nettoyage des fichiers temporaires..."

# Nettoyer les fichiers temporaires dans uploads/
if [ -d "uploads" ]; then
    temp_files=$(find uploads/ -name "*.zip" -o -name "*.sql" -mmin +60 2>/dev/null | wc -l)
    if [ "$temp_files" -gt 0 ]; then
        echo "  🗑️  $temp_files fichiers temporaires trouvés (>1h)"
        read -p "  🗑️  Supprimer ces fichiers? (y/N): " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            find uploads/ -name "*.zip" -o -name "*.sql" -mmin +60 -delete 2>/dev/null
            echo "  ✅ Fichiers temporaires supprimés"
        fi
    else
        echo "  ✅ Aucun fichier temporaire ancien"
    fi
fi

echo ""
echo "🐳 Nettoyage Docker..."

# Nettoyer les conteneurs arrêtés
stopped_containers=$(docker ps -a -q --filter "status=exited" 2>/dev/null | wc -l)
if [ "$stopped_containers" -gt 0 ]; then
    echo "  🗑️  $stopped_containers conteneurs arrêtés trouvés"
    read -p "  🗑️  Supprimer ces conteneurs? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker container prune -f 2>/dev/null
        echo "  ✅ Conteneurs arrêtés supprimés"
    fi
fi

# Nettoyer les images inutilisées
unused_images=$(docker images -q --filter "dangling=true" 2>/dev/null | wc -l)
if [ "$unused_images" -gt 0 ]; then
    echo "  🗑️  $unused_images images inutilisées trouvées"
    read -p "  🗑️  Supprimer ces images? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker image prune -f 2>/dev/null
        echo "  ✅ Images inutilisées supprimées"
    fi
fi

# Nettoyer les volumes inutilisés
unused_volumes=$(docker volume ls -q --filter "dangling=true" 2>/dev/null | wc -l)
if [ "$unused_volumes" -gt 0 ]; then
    echo "  🗑️  $unused_volumes volumes inutilisés trouvés"
    read -p "  🗑️  Supprimer ces volumes? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker volume prune -f 2>/dev/null
        echo "  ✅ Volumes inutilisés supprimés"
    fi
fi

echo ""
echo "✅ Nettoyage terminé!"
echo ""
echo "📊 Pour voir l'état actuel :"
echo "  ./diagnose.sh" 