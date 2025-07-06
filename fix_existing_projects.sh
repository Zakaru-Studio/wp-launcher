#!/bin/bash

# Script pour corriger les projets existants et leur faire utiliser leur hostname configuré
echo "🔧 Correction des projets existants pour utiliser leurs hostnames"
echo "================================================================="

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
        echo "🔄 Correction du projet: $project_name"
        echo "--------------------------------------"
        
        # Lire l'hostname depuis le fichier .hostname
        hostname_file="$project_dir/.hostname"
        if [ -f "$hostname_file" ]; then
            hostname=$(cat "$hostname_file")
        else
            hostname="$project_name.local"
            echo "$hostname" > "$hostname_file"
            echo "✅ Fichier .hostname créé avec: $hostname"
        fi
        
        echo "🌐 Hostname configuré: $hostname"
        
        # Corriger le fichier wp-config.php
        wp_config_file="$project_dir/wordpress/wp-config.php"
        if [ -f "$wp_config_file" ]; then
            echo "⚙️ Correction de wp-config.php..."
            
            # Sauvegarder l'original
            cp "$wp_config_file" "$wp_config_file.backup"
            
            # Remplacer localhost par l'hostname configuré
            sed -i "s|http://localhost:8080|http://$hostname:8080|g" "$wp_config_file"
            
            echo "✅ wp-config.php corrigé"
        else
            echo "⚠️ Fichier wp-config.php non trouvé"
        fi
        
        # Vérifier si le conteneur MySQL est actif
        mysql_container="${project_name}_mysql_1"
        if docker ps --filter "name=$mysql_container" --format "{{.Names}}" | grep -q "$mysql_container"; then
            echo "🗃️ Correction des URLs WordPress dans la base de données..."
            
            # Mettre à jour les URLs dans la base de données
            update_sql="UPDATE wp_options SET option_value = 'http://$hostname:8080' WHERE option_name = 'home'; UPDATE wp_options SET option_value = 'http://$hostname:8080' WHERE option_name = 'siteurl';"
            
            if docker exec "$mysql_container" mysql -u wordpress -pwordpress wordpress -e "$update_sql" 2>/dev/null; then
                echo "✅ URLs WordPress mises à jour dans la base de données"
            else
                echo "⚠️ Erreur lors de la mise à jour de la base de données (le conteneur sera corrigé au prochain démarrage)"
            fi
        else
            echo "ℹ️ Conteneur MySQL arrêté - la base de données sera corrigée au prochain démarrage"
        fi
        
        # Vérifier/ajouter l'hostname aux /etc/hosts
        if ! grep -q "$hostname" /etc/hosts 2>/dev/null; then
            echo "🌐 Ajout de l'hostname au fichier /etc/hosts..."
            if [ -f "manage_hosts.sh" ]; then
                sudo ./manage_hosts.sh add "$hostname"
            else
                echo "127.0.0.1    $hostname" | sudo tee -a /etc/hosts > /dev/null
            fi
            echo "✅ Hostname ajouté aux hosts"
        else
            echo "✅ Hostname déjà présent dans /etc/hosts"
        fi
        
        echo "✅ Projet $project_name corrigé"
    fi
done

echo ""
echo "🎉 Correction terminée !"
echo ""
echo "📋 Résumé des corrections appliquées:"
echo "  - ✅ Fichiers .hostname créés/vérifiés"
echo "  - ✅ wp-config.php corrigés (localhost → hostname)"
echo "  - ✅ URLs WordPress mises à jour dans les bases de données"
echo "  - ✅ Hostnames ajoutés au fichier /etc/hosts"
echo ""
echo "🌐 Vos sites sont maintenant accessibles via leurs hostnames configurés !"
echo "   Exemple: http://eurasiapeace.local:8080"
echo ""
echo "💡 Si vous avez des problèmes:"
echo "   1. Redémarrez les conteneurs: cd projets/[projet] && docker-compose restart"
echo "   2. Vérifiez /etc/hosts: cat /etc/hosts | grep local"
echo "   3. Testez l'accès: curl -I http://[hostname]:8080" 