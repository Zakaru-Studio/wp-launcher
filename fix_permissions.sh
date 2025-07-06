#!/bin/bash

# Script pour corriger les permissions des projets WordPress
echo "🔧 Correction des permissions des projets WordPress"
echo "=================================================="

# Vérifier que le dossier projets existe
if [ ! -d "projets" ]; then
    echo "❌ Dossier 'projets' non trouvé"
    exit 1
fi

# Fonction pour corriger les permissions d'un projet
fix_project_permissions() {
    local project_path="$1"
    local project_name=$(basename "$project_path")
    
    echo ""
    echo "🔧 Correction des permissions pour: $project_name"
    echo "-------------------------------------------"
    
    if [ ! -d "$project_path" ]; then
        echo "❌ Projet non trouvé: $project_path"
        return 1
    fi
    
    # Vérifier les permissions actuelles
    echo "🔍 Vérification des permissions actuelles..."
    ls -la "$project_path" | head -5
    
    # Corriger les permissions
    echo "⚙️ Correction des permissions..."
    
    # Méthode 1: chmod normal
    if chmod -R 755 "$project_path" 2>/dev/null; then
        echo "✅ Permissions corrigées (méthode normale)"
        return 0
    fi
    
    # Méthode 2: avec sudo
    echo "🔐 Utilisation de sudo pour corriger les permissions..."
    if sudo chmod -R 755 "$project_path" 2>/dev/null; then
        echo "✅ Permissions corrigées (avec sudo)"
        return 0
    fi
    
    # Méthode 3: via Docker (si le conteneur est actif)
    echo "🐳 Tentative via Docker..."
    wp_container="${project_name}_wordpress_1"
    
    if docker ps --format '{{.Names}}' | grep -q "$wp_container"; then
        echo "📦 Conteneur WordPress actif, correction via Docker..."
        
        # Corriger les permissions depuis le conteneur
        docker exec "$wp_container" chown -R www-data:www-data /var/www/html 2>/dev/null
        docker exec "$wp_container" chmod -R 755 /var/www/html 2>/dev/null
        
        # Ensuite corriger les permissions locales
        sudo chown -R $USER:$USER "$project_path" 2>/dev/null
        sudo chmod -R 755 "$project_path" 2>/dev/null
        
        echo "✅ Permissions corrigées (via Docker)"
        return 0
    fi
    
    echo "⚠️ Impossible de corriger les permissions pour $project_name"
    return 1
}

# Fonction pour corriger tous les projets
fix_all_projects() {
    echo "🔄 Correction des permissions pour tous les projets..."
    echo ""
    
    local success_count=0
    local total_count=0
    
    for project_dir in projets/*/; do
        if [ -d "$project_dir" ]; then
            total_count=$((total_count + 1))
            if fix_project_permissions "$project_dir"; then
                success_count=$((success_count + 1))
            fi
        fi
    done
    
    echo ""
    echo "📊 Résumé:"
    echo "   - Projets traités: $total_count"
    echo "   - Corrections réussies: $success_count"
    echo "   - Échecs: $((total_count - success_count))"
}

# Fonction pour nettoyer les fichiers temporaires
cleanup_temp_files() {
    echo ""
    echo "🧹 Nettoyage des fichiers temporaires..."
    
    # Supprimer les fichiers temporaires dans uploads/
    if [ -d "uploads" ]; then
        find uploads/ -name "*.tmp" -delete 2>/dev/null
        find uploads/ -name "temp_*" -delete 2>/dev/null
        find uploads/ -name "update_*" -delete 2>/dev/null
        echo "✅ Fichiers temporaires supprimés"
    fi
    
    # Nettoyer les containers Docker orphelins
    echo "🐳 Nettoyage des containers Docker orphelins..."
    docker system prune -f 2>/dev/null
    echo "✅ Containers orphelins supprimés"
}

# Fonction pour vérifier les permissions
check_permissions() {
    echo ""
    echo "🔍 Vérification des permissions des projets..."
    echo ""
    
    for project_dir in projets/*/; do
        if [ -d "$project_dir" ]; then
            project_name=$(basename "$project_dir")
            echo "📁 $project_name:"
            
            # Vérifier si on peut lire le dossier
            if [ -r "$project_dir" ]; then
                echo "  ✅ Lisible"
            else
                echo "  ❌ Non lisible"
            fi
            
            # Vérifier si on peut écrire dans le dossier
            if [ -w "$project_dir" ]; then
                echo "  ✅ Modifiable"
            else
                echo "  ❌ Non modifiable"
            fi
            
            # Vérifier les permissions du dossier WordPress
            wp_dir="$project_dir/wordpress"
            if [ -d "$wp_dir" ]; then
                if [ -w "$wp_dir" ]; then
                    echo "  ✅ WordPress modifiable"
                else
                    echo "  ❌ WordPress non modifiable"
                fi
            fi
            
            echo ""
        fi
    done
}

# Menu principal
case "$1" in
    "fix")
        if [ -n "$2" ]; then
            # Corriger un projet spécifique
            fix_project_permissions "projets/$2"
        else
            # Corriger tous les projets
            fix_all_projects
        fi
        ;;
    "check")
        check_permissions
        ;;
    "cleanup")
        cleanup_temp_files
        ;;
    "help"|"--help"|"-h")
        echo "Usage: $0 [commande] [options]"
        echo ""
        echo "Commandes disponibles:"
        echo "  fix [projet]  - Corriger les permissions (tous les projets ou un projet spécifique)"
        echo "  check         - Vérifier les permissions actuelles"
        echo "  cleanup       - Nettoyer les fichiers temporaires"
        echo "  help          - Afficher cette aide"
        echo ""
        echo "Exemples:"
        echo "  $0 fix                    # Corriger tous les projets"
        echo "  $0 fix eurasiapeace      # Corriger un projet spécifique"
        echo "  $0 check                 # Vérifier les permissions"
        echo "  $0 cleanup               # Nettoyer les fichiers temporaires"
        ;;
    *)
        echo "Usage: $0 [fix|check|cleanup|help] [projet]"
        echo "Utilisez '$0 help' pour plus d'informations"
        ;;
esac 