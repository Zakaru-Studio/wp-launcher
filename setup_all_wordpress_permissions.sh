#!/bin/bash

# Configuration permissions WordPress pour TOUS les projets existants
# Nouvelle architecture containers/projets

echo "🔧 Configuration permissions WordPress pour TOUS les projets"
echo "==========================================================="

# Compteurs
TOTAL_PROJECTS=0
SUCCESS_COUNT=0
ERROR_COUNT=0

# Vérifier que le dossier containers/ existe
if [ ! -d "containers" ]; then
    echo "❌ Dossier 'containers/' non trouvé"
    echo "💡 La nouvelle architecture utilise containers/ pour la configuration Docker"
    exit 1
fi

# Parcourir tous les projets dans containers/
echo "🔍 Recherche des projets dans containers/..."

for project_dir in containers/*/; do
    if [ -d "$project_dir" ]; then
        project_name=$(basename "$project_dir")
        
        # Vérifier que le projet a un docker-compose.yml
        if [ -f "$project_dir/docker-compose.yml" ]; then
            echo ""
            echo "➡️ Projet trouvé: $project_name"
            ((TOTAL_PROJECTS++))
            
            # Exécuter le script de permissions pour ce projet
            if ./setup_wordpress_permissions.sh "$project_name"; then
                echo "✅ $project_name: Permissions configurées avec succès"
                ((SUCCESS_COUNT++))
            else
                echo "❌ $project_name: Erreur lors de la configuration"
                ((ERROR_COUNT++))
            fi
        else
            echo "⚠️ $project_name: Pas de docker-compose.yml, ignoré"
        fi
    fi
done

echo ""
echo "📊 Résumé de la configuration"
echo "=========================="
echo "📈 Projets traités: $TOTAL_PROJECTS"
echo "✅ Succès: $SUCCESS_COUNT"
echo "❌ Erreurs: $ERROR_COUNT"

if [ $TOTAL_PROJECTS -eq 0 ]; then
    echo ""
    echo "🤔 Aucun projet trouvé dans containers/"
    echo "💡 Nouvelle structure:"
    echo "   containers/mon-projet/    ← Configuration Docker" 
    echo "   projets/mon-projet/       ← Fichiers éditables"
elif [ $SUCCESS_COUNT -eq $TOTAL_PROJECTS ]; then
    echo ""
    echo "🎉 Tous les projets ont été configurés avec succès !"
    echo ""
    echo "📋 Actions maintenant possibles sur TOUS les projets :"
    echo "   ✅ Créer/supprimer des fichiers et dossiers"
    echo "   ✅ Modifier wp-config.php directement"
    echo "   ✅ Éditer tous les fichiers wp-content"
    echo "   ✅ Renommer/déplacer des fichiers"
    echo "   ✅ Installer/supprimer des plugins/thèmes"
    echo ""
    echo "⚠️  IMPORTANT :"
    echo "   Reconnectez-vous SSH pour que l'ajout au groupe www-data soit effectif"
    echo "   newgrp www-data  # ou déconnexion/reconnexion complète"
else
    echo ""
    echo "⚠️ Certains projets ont rencontré des erreurs"
    echo "🔄 Vous pouvez relancer le script ou corriger manuellement les projets en erreur"
fi 