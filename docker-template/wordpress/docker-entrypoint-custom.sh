#!/bin/bash
set -euo pipefail

# Script d'entrée personnalisé pour WordPress avec WP-CLI et installation automatique

echo "🚀 Démarrage du conteneur WordPress personnalisé..."

# === GESTION DES PERMISSIONS PARTAGÉES AU DÉBUT ===
if [ "${FORCE_SHARED_PERMISSIONS:-false}" = "true" ]; then
    echo "🔧 Configuration préalable des permissions partagées..."
    
    # Installer ACL si pas disponible
    if ! command -v setfacl >/dev/null 2>&1; then
        echo "📦 Installation d'ACL..."
        apt-get update >/dev/null 2>&1 || true
        apt-get install -y acl >/dev/null 2>&1 || true
    fi
    
    # Créer l'utilisateur dev-server dans le conteneur s'il n'existe pas
    if ! id dev-server 2>/dev/null; then
        echo "➕ Création de l'utilisateur dev-server dans le conteneur..."
        groupadd -g ${DEV_USER_GID:-1000} dev-server 2>/dev/null || true
        useradd -u ${DEV_USER_UID:-1000} -g ${DEV_USER_GID:-1000} -s /bin/bash dev-server 2>/dev/null || true
    fi
    
    # Configuration des groupes
    usermod -a -G www-data dev-server 2>/dev/null || true
    usermod -a -G dev-server www-data 2>/dev/null || true
    
    # Fonction pour appliquer les permissions WordPress renforcées
    apply_wordpress_permissions() {
        local path="$1"
        if [ -d "$path" ] || [ -f "$path" ]; then
            echo "🔐 Application des permissions WordPress sur: $path"
            # dev-server propriétaire, www-data groupe pour permissions partagées
            chown -R 1000:33 "$path" 2>/dev/null || true
            if [ -d "$path" ]; then
                find "$path" -type d -exec chmod 775 {} \; 2>/dev/null || true
                find "$path" -type f -exec chmod 664 {} \; 2>/dev/null || true
            else
                chmod 664 "$path" 2>/dev/null || true
            fi
            
            # Ajouter des ACL pour dev-server et www-data
            if command -v setfacl >/dev/null 2>&1; then
                setfacl -R -m u:${DEV_USER_UID:-1000}:rwx "$path" 2>/dev/null || true
                setfacl -R -m u:33:rwx "$path" 2>/dev/null || true  # www-data
                if [ -d "$path" ]; then
                    setfacl -R -d -m u:${DEV_USER_UID:-1000}:rwx "$path" 2>/dev/null || true
                    setfacl -R -d -m u:33:rwx "$path" 2>/dev/null || true  # www-data
                fi
            fi
        fi
    }
    
    # Fonction spécialisée pour les permissions wp-content (WordPress doit pouvoir écrire)
    apply_wp_content_permissions() {
        local path="$1"
        if [ -d "$path" ] || [ -f "$path" ]; then
            echo "🔐 Application des permissions wp-content (écriture WordPress): $path"
            # www-data propriétaire et groupe pour permettre l'écriture WordPress
            chown -R 33:33 "$path" 2>/dev/null || true
            if [ -d "$path" ]; then
                find "$path" -type d -exec chmod 755 {} \; 2>/dev/null || true
                find "$path" -type f -exec chmod 644 {} \; 2>/dev/null || true
            else
                chmod 644 "$path" 2>/dev/null || true
            fi
            
            # Ajouter des ACL pour dev-server (lecture/écriture) 
            if command -v setfacl >/dev/null 2>&1; then
                setfacl -R -m u:${DEV_USER_UID:-1000}:rwx "$path" 2>/dev/null || true
                setfacl -R -m g:${DEV_USER_GID:-1000}:rwx "$path" 2>/dev/null || true
                if [ -d "$path" ]; then
                    setfacl -R -d -m u:${DEV_USER_UID:-1000}:rwx "$path" 2>/dev/null || true
                    setfacl -R -d -m g:${DEV_USER_GID:-1000}:rwx "$path" 2>/dev/null || true
                fi
            fi
        fi
    }
    
    # Créer un script de surveillance des permissions amélioré
    cat > /usr/local/bin/fix-permissions-loop.sh << 'EOF'
#!/bin/bash
while true; do
    sleep 180  # Vérifier toutes les 3 minutes
    if [ "${FORCE_SHARED_PERMISSIONS:-false}" = "true" ]; then
        # Réappliquer les permissions wp-content (WordPress doit pouvoir écrire)
        if [ -d "/var/www/html/wp-content" ]; then
            # www-data propriétaire pour permettre l'écriture WordPress
            chown -R 33:33 /var/www/html/wp-content 2>/dev/null || true
            find /var/www/html/wp-content -type d -exec chmod 755 {} \; 2>/dev/null || true
            find /var/www/html/wp-content -type f -exec chmod 644 {} \; 2>/dev/null || true
            
            # S'assurer que les dossiers critiques existent avec bonnes permissions
            mkdir -p /var/www/html/wp-content/plugins 2>/dev/null || true
            mkdir -p /var/www/html/wp-content/themes 2>/dev/null || true
            mkdir -p /var/www/html/wp-content/uploads 2>/dev/null || true
            mkdir -p /var/www/html/wp-content/upgrade 2>/dev/null || true
            
            # Dossiers spéciaux pour WordPress
            chmod 755 /var/www/html/wp-content/plugins 2>/dev/null || true
            chmod 755 /var/www/html/wp-content/themes 2>/dev/null || true
            chmod 755 /var/www/html/wp-content/uploads 2>/dev/null || true
            chmod 755 /var/www/html/wp-content/upgrade 2>/dev/null || true
            
            # ACL pour dev-server (lecture/écriture depuis l'hôte)
            if command -v setfacl >/dev/null 2>&1; then
                setfacl -R -m u:1000:rwx /var/www/html/wp-content 2>/dev/null || true
                setfacl -R -d -m u:1000:rwx /var/www/html/wp-content 2>/dev/null || true
                setfacl -R -m g:1000:rwx /var/www/html/wp-content 2>/dev/null || true
                setfacl -R -d -m g:1000:rwx /var/www/html/wp-content 2>/dev/null || true
            fi
        fi
        
        # Fichiers de configuration
        for file in "/var/www/html/wp-config.php" "/var/www/html/.htaccess"; do
            if [ -f "$file" ]; then
                chown 1000:33 "$file" 2>/dev/null || true
                chmod 664 "$file" 2>/dev/null || true
                if command -v setfacl >/dev/null 2>&1; then
                    setfacl -m u:1000:rw "$file" 2>/dev/null || true
                fi
            fi
        done
    fi
done
EOF
    
    chmod +x /usr/local/bin/fix-permissions-loop.sh
    
    # Démarrer le script de surveillance en arrière-plan
    /usr/local/bin/fix-permissions-loop.sh &
fi

# Démarrer le script d'entrée original de WordPress en arrière-plan
docker-entrypoint.sh "$@" &

# Attendre que MySQL soit prêt
echo "⏳ Attente de la base de données..."
while ! wp db check --allow-root 2>/dev/null; do
    echo "   Base de données non prête, attente..."
    sleep 5
done

echo "✅ Base de données prête !"

# Aller dans le répertoire WordPress
cd /var/www/html

# Vérifier si WordPress est déjà installé
if ! wp core is-installed --allow-root 2>/dev/null; then
    echo "🔧 Installation automatique de WordPress..."
    
    # Télécharger WordPress si nécessaire
    if [ ! -f wp-load.php ]; then
        echo "📥 Téléchargement des fichiers WordPress..."
        wp core download --allow-root --skip-content
    fi
    
    # Créer wp-config.php avec les variables d'environnement
    echo "📄 Création du fichier wp-config.php..."
    wp config create \
        --dbname="${WORDPRESS_DB_NAME}" \
        --dbuser="${WORDPRESS_DB_USER}" \
        --dbpass="${WORDPRESS_DB_PASSWORD}" \
        --dbhost="${WORDPRESS_DB_HOST}" \
        --locale="${WPLANG:-fr_FR}" \
        --allow-root \
        --force
    
    # Ajouter des configurations supplémentaires
    wp config set WP_DEBUG "${WORDPRESS_DEBUG:-false}" --raw --allow-root
    wp config set WP_DEBUG_LOG "${WORDPRESS_DEBUG_LOG:-false}" --raw --allow-root
    wp config set WP_DEBUG_DISPLAY "${WORDPRESS_DEBUG_DISPLAY:-false}" --raw --allow-root
    wp config set WP_HOME "${WP_HOME}" --allow-root
    wp config set WP_SITEURL "${WP_HOME}" --allow-root
    wp config set DISALLOW_FILE_EDIT "false" --raw --allow-root
    wp config set DISALLOW_FILE_MODS "false" --raw --allow-root
    wp config set WP_POST_REVISIONS "3" --raw --allow-root
    wp config set EMPTY_TRASH_DAYS "30" --raw --allow-root
    wp config set WP_AUTO_UPDATE_CORE "false" --raw --allow-root
    wp config set FS_METHOD "direct" --allow-root
    wp config set FORCE_SSL_ADMIN "false" --raw --allow-root
    wp config set WP_MEMORY_LIMIT "512M" --allow-root
    
    # Installer WordPress automatiquement
    echo "⚙️ Installation du core WordPress..."
    wp core install \
        --url="${WP_HOME}" \
        --title="${WP_TITLE:-Mon Site WordPress}" \
        --admin_user="${WP_ADMIN_USER:-admin}" \
        --admin_password="${WP_ADMIN_PASSWORD:-admin123}" \
        --admin_email="${WP_ADMIN_EMAIL:-admin@example.com}" \
        --allow-root
    
    echo "🎉 WordPress installé avec succès !"
    echo "🔗 URL: ${WP_HOME}"
    echo "👤 Admin: ${WP_ADMIN_USER:-admin}"
    echo "🔑 Password: ${WP_ADMIN_PASSWORD:-admin123}"
    
    # Configuration post-installation
    echo "🔧 Configuration post-installation..."
    
    # Supprimer le contenu par défaut
    wp post delete 1 --allow-root 2>/dev/null || true
    wp comment delete 1 --allow-root 2>/dev/null || true
    
    # Configurer les permaliens
    wp rewrite structure '/%postname%/' --allow-root
    
    # Installer des plugins essentiels si disponibles
    if [ -d /var/www/html/wp-content/plugins/classic-editor ]; then
        echo "🔌 Activation du plugin Classic Editor..."
        wp plugin activate classic-editor --allow-root 2>/dev/null || true
    fi
    
    if [ -d /var/www/html/wp-content/plugins/advanced-custom-fields-pro ]; then
        echo "🔌 Activation du plugin Advanced Custom Fields Pro..."
        wp plugin activate advanced-custom-fields-pro --allow-root 2>/dev/null || true
    fi
    
    # Activer le thème personnalisé si disponible
    if [ -d /var/www/html/wp-content/themes/otfm-headless-master ]; then
        echo "🎨 Activation du thème otfm-headless-master..."
        wp theme activate otfm-headless-master --allow-root 2>/dev/null || true
    fi
    
    # Configurer la langue française
    wp language core install fr_FR --allow-root 2>/dev/null || true
    wp site switch-language fr_FR --allow-root 2>/dev/null || true
    
    # Configurer le fuseau horaire
    wp option update timezone_string 'Europe/Paris' --allow-root
    
    # Désactiver les commentaires par défaut
    wp option update default_comment_status 'closed' --allow-root
    
    # Copier wp-config.php vers le dossier du projet
    echo "📁 Copie du fichier wp-config.php vers le dossier du projet..."
    if [ -d "/var/www/html/wp-content" ]; then
        # Trouver le chemin du dossier du projet (parent de wp-content)
        PROJECT_DIR=$(dirname "$(readlink -f /var/www/html/wp-content)")
        if [ -w "$PROJECT_DIR" ]; then
            cp wp-config.php "$PROJECT_DIR/wp-config.php" 2>/dev/null || true
            echo "✅ wp-config.php copié vers $PROJECT_DIR/"
        fi
    fi
    
    # Copier le template wp-content (remplacer plugins/themes par défaut)
    echo "📋 Copie du template wp-content depuis le template..."
    TEMPLATE_WP_CONTENT="/var/www/html/wp-content-template"
    
    # Vérifier si le template existe (monté depuis docker-template/wordpress/wp-content)
    if [ -d "$TEMPLATE_WP_CONTENT" ]; then
        echo "📁 Template wp-content trouvé dans $TEMPLATE_WP_CONTENT"
        
        # Sauvegarder le dossier uploads s'il existe
        if [ -d "/var/www/html/wp-content/uploads" ]; then
            echo "💾 Sauvegarde temporaire du dossier uploads..."
            cp -r /var/www/html/wp-content/uploads /tmp/uploads-backup
            RESTORE_UPLOADS=true
        else
            RESTORE_UPLOADS=false
        fi
        
        # Vider les dossiers plugins et themes
        echo "🗑️ Vidage des dossiers plugins et themes..."
        if [ -d "/var/www/html/wp-content/plugins" ]; then
            rm -rf /var/www/html/wp-content/plugins/*
            echo "✅ Dossier plugins vidé"
        fi
        
        if [ -d "/var/www/html/wp-content/themes" ]; then
            rm -rf /var/www/html/wp-content/themes/*
            echo "✅ Dossier themes vidé"
        fi
        
        # Copier le contenu du template
        echo "📋 Copie du contenu du template..."
        
        # Copier plugins du template
        if [ -d "$TEMPLATE_WP_CONTENT/plugins" ]; then
            cp -r "$TEMPLATE_WP_CONTENT/plugins"/* /var/www/html/wp-content/plugins/
            echo "✅ Plugins du template copiés"
        fi
        
        # Copier themes du template
        if [ -d "$TEMPLATE_WP_CONTENT/themes" ]; then
            cp -r "$TEMPLATE_WP_CONTENT/themes"/* /var/www/html/wp-content/themes/
            echo "✅ Thèmes du template copiés"
        fi
        
        # Supprimer les thèmes par défaut de WordPress pour éviter les conflits
        echo "🗑️ Suppression des thèmes WordPress par défaut..."
        wp theme delete twentytwentyfive --allow-root 2>/dev/null && echo "✅ Thème twentytwentyfive supprimé" || echo "⚠️ Thème twentytwentyfive non trouvé"
        wp theme delete twentytwentyfour --allow-root 2>/dev/null && echo "✅ Thème twentytwentyfour supprimé" || echo "⚠️ Thème twentytwentyfour non trouvé"
        wp theme delete twentytwentythree --allow-root 2>/dev/null && echo "✅ Thème twentytwentythree supprimé" || echo "⚠️ Thème twentytwentythree non trouvé"
        
        # Copier mu-plugins du template
        if [ -d "$TEMPLATE_WP_CONTENT/mu-plugins" ]; then
            mkdir -p /var/www/html/wp-content/mu-plugins
            cp -r "$TEMPLATE_WP_CONTENT/mu-plugins"/* /var/www/html/wp-content/mu-plugins/
            echo "✅ MU-plugins du template copiés"
        fi
        
        # Copier autres fichiers du template
        for file in "$TEMPLATE_WP_CONTENT"/*; do
            if [ -f "$file" ]; then
                filename=$(basename "$file")
                cp "$file" "/var/www/html/wp-content/"
                echo "📄 Fichier $filename copié"
            fi
        done
        
        # Restaurer le dossier uploads
        if [ "$RESTORE_UPLOADS" = true ]; then
            echo "🔄 Restauration du dossier uploads..."
            mkdir -p /var/www/html/wp-content/uploads
            cp -r /tmp/uploads-backup/* /var/www/html/wp-content/uploads/
            rm -rf /tmp/uploads-backup
            echo "✅ Dossier uploads restauré"
        fi
        
        # Activer le thème du template s'il existe
        echo "🎨 Activation du thème du template..."

        # Trouver et activer le premier thème disponible dans le template
        if [ -d "/var/www/html/wp-content/themes" ]; then
            for theme_dir in /var/www/html/wp-content/themes/*/; do
                if [ -d "$theme_dir" ]; then
                    theme_name=$(basename "$theme_dir")
                    echo "🎨 Tentative d'activation du thème: $theme_name"
                    wp theme activate "$theme_name" --allow-root 2>/dev/null && echo "✅ Thème $theme_name activé" || echo "⚠️ Impossible d'activer le thème $theme_name"
                    break
                fi
            done
        fi

        # Vérifier quel thème est actuellement actif
        echo "🔍 Vérification du thème actif..."
        ACTIVE_THEME=$(wp theme get --allow-root --field=name 2>/dev/null || echo "Erreur")
        echo "📄 Thème actuellement actif: $ACTIVE_THEME"
        
        # Activer tous les plugins du template
        echo "🔌 Activation des plugins du template..."
        if [ -d "/var/www/html/wp-content/plugins" ]; then
            for plugin_dir in /var/www/html/wp-content/plugins/*/; do
                if [ -d "$plugin_dir" ]; then
                    plugin_name=$(basename "$plugin_dir")
                    echo "🔌 Tentative d'activation du plugin: $plugin_name"
                    wp plugin activate "$plugin_name" --allow-root 2>/dev/null && echo "✅ Plugin $plugin_name activé" || echo "⚠️ Impossible d'activer le plugin $plugin_name"
                fi
            done
        fi
        
        echo "✅ Template wp-content appliqué avec succès!"
    else
        echo "⚠️ Template wp-content non trouvé dans $TEMPLATE_WP_CONTENT"
    fi
    
    echo "✅ Configuration terminée !"
    
else
    echo "ℹ️ WordPress déjà installé."
    
    # Vérifier si wp-config.php existe dans le conteneur, sinon le créer
    if [ ! -f wp-config.php ]; then
        echo "📄 Création du fichier wp-config.php manquant..."
        wp config create \
            --dbname="${WORDPRESS_DB_NAME}" \
            --dbuser="${WORDPRESS_DB_USER}" \
            --dbpass="${WORDPRESS_DB_PASSWORD}" \
            --dbhost="${WORDPRESS_DB_HOST}" \
            --locale="${WPLANG:-fr_FR}" \
            --allow-root \
            --force
        
        # Copier vers le dossier du projet
        if [ -d "/var/www/html/wp-content" ]; then
            PROJECT_DIR=$(dirname "$(readlink -f /var/www/html/wp-content)")
            if [ -w "$PROJECT_DIR" ]; then
                cp wp-config.php "$PROJECT_DIR/wp-config.php" 2>/dev/null || true
                echo "✅ wp-config.php copié vers $PROJECT_DIR/"
            fi
        fi
    fi
    
    # Vérifier si le template wp-content doit être appliqué (plugins manquants)
    TEMPLATE_WP_CONTENT="/var/www/html/wp-content-template"
    if [ -d "$TEMPLATE_WP_CONTENT" ]; then
        # Vérifier si les plugins du template sont présents
        TEMPLATE_THEME_MISSING=true
        if [ -d "/var/www/html/wp-content/themes" ]; then
            for td in /var/www/html/wp-content/themes/*/; do
                if [ -d "$td" ]; then
                    TEMPLATE_THEME_MISSING=false
                    break
                fi
            done
        fi
        if [ ! -d "/var/www/html/wp-content/plugins/advanced-custom-fields-pro" ] || [ "$TEMPLATE_THEME_MISSING" = true ]; then
            echo "🔄 Les plugins/thèmes du template sont manquants, application du template..."
            
            # Sauvegarder le dossier uploads s'il existe
            if [ -d "/var/www/html/wp-content/uploads" ]; then
                echo "💾 Sauvegarde temporaire du dossier uploads..."
                cp -r /var/www/html/wp-content/uploads /tmp/uploads-backup
                RESTORE_UPLOADS=true
            else
                RESTORE_UPLOADS=false
            fi
            
            # Vider et copier plugins
            echo "🗑️ Mise à jour des plugins..."
            rm -rf /var/www/html/wp-content/plugins/*
            cp -r "$TEMPLATE_WP_CONTENT/plugins"/* /var/www/html/wp-content/plugins/
            
            # Vider et copier themes
            echo "🗑️ Mise à jour des thèmes..."
            rm -rf /var/www/html/wp-content/themes/*
            cp -r "$TEMPLATE_WP_CONTENT/themes"/* /var/www/html/wp-content/themes/
            
            # Copier mu-plugins
            if [ -d "$TEMPLATE_WP_CONTENT/mu-plugins" ]; then
                echo "📋 Mise à jour des mu-plugins..."
                mkdir -p /var/www/html/wp-content/mu-plugins
                cp -r "$TEMPLATE_WP_CONTENT/mu-plugins"/* /var/www/html/wp-content/mu-plugins/
            fi
            
            # Restaurer le dossier uploads
            if [ "$RESTORE_UPLOADS" = true ]; then
                echo "🔄 Restauration du dossier uploads..."
                mkdir -p /var/www/html/wp-content/uploads
                cp -r /tmp/uploads-backup/* /var/www/html/wp-content/uploads/
                rm -rf /tmp/uploads-backup
            fi
            
            echo "✅ Template wp-content appliqué sur installation existante!"
        else
            echo "ℹ️ Template wp-content déjà appliqué"
        fi
    fi
fi

# === PERMISSIONS FINALES ===
if [ "${FORCE_SHARED_PERMISSIONS:-false}" = "true" ]; then
    echo "🔐 Application des permissions partagées finales..."
    
    # Appliquer les permissions sur les volumes montés
    apply_wp_content_permissions "/var/www/html/wp-content"
    apply_wordpress_permissions "/var/www/html/wp-config.php"
    apply_wordpress_permissions "/var/www/html/.htaccess"
    
    echo "✅ Permissions partagées appliquées"
fi

# Garder le conteneur en vie
wait 