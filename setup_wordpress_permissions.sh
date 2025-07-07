#!/bin/bash

# Configuration permissions WordPress complètes avec architecture containers/projets
# Utilisation: ./setup_wordpress_permissions.sh <nom_du_projet>

if [ $# -ne 1 ]; then
    echo "❌ Usage: $0 <nom_du_projet>"
    echo "Exemple: $0 monsite"
    exit 1
fi

PROJECT_NAME="$1"
CURRENT_USER=$(whoami)

# Nouveaux chemins avec architecture containers/projets
CONTAINER_PATH="containers/$PROJECT_NAME"
PROJECT_PATH="projets/$PROJECT_NAME"
WP_PATH="$CONTAINER_PATH/wordpress"

echo "🔧 Configuration permissions WordPress complètes pour $PROJECT_NAME"
echo "================================================================="
echo "📂 Configuration Docker: $CONTAINER_PATH"
echo "📂 Fichiers éditables: $PROJECT_PATH"
echo "📂 WordPress: $WP_PATH"
echo ""
echo "👤 Utilisateur: $CURRENT_USER ($(id -u):$(id -g))"

# Vérifier que les dossiers existent
if [ ! -d "$CONTAINER_PATH" ]; then
    echo "❌ Dossier containers/$PROJECT_NAME non trouvé"
    exit 1
fi

if [ ! -d "$PROJECT_PATH" ]; then
    echo "❌ Dossier projets/$PROJECT_NAME non trouvé"
    exit 1
fi

if [ ! -d "$WP_PATH" ]; then
    echo "❌ Dossier WordPress non trouvé: $WP_PATH"
    exit 1
fi

# 1. Ajouter l'utilisateur au groupe www-data s'il n'y est pas déjà
echo ""
echo "1️⃣ Ajout de $CURRENT_USER au groupe www-data..."

if groups $CURRENT_USER | grep -q "\bwww-data\b"; then
    echo "ℹ️ $CURRENT_USER est déjà dans le groupe www-data"
else
    echo "➕ Ajout de $CURRENT_USER au groupe www-data..."
    sudo usermod -a -G www-data $CURRENT_USER
    echo "✅ $CURRENT_USER ajouté au groupe www-data"
fi

# 2. Configuration de la propriété partagée
echo ""
echo "2️⃣ Configuration de la propriété partagée..."

# WordPress core (containers/)
sudo chgrp -R www-data "$WP_PATH"
find "$WP_PATH" -type d -exec sudo chmod 775 {} \;
find "$WP_PATH" -type f -exec sudo chmod 664 {} \;

echo "✅ Permissions de base configurées"

# 3. Configuration des ACL avancées pour plus de granularité
echo ""
echo "3️⃣ Configuration des ACL avancées..."

# Installer ACL si nécessaire
if ! command -v setfacl &> /dev/null; then
    echo "📦 Installation d'ACL..."
    sudo apt update && sudo apt install -y acl
fi

# ACL pour l'utilisateur actuel (accès complet)
sudo setfacl -R -m u:$CURRENT_USER:rwx "$WP_PATH"
sudo setfacl -R -d -m u:$CURRENT_USER:rwx "$WP_PATH"

# ACL pour www-data (accès complet aussi)
sudo setfacl -R -m u:www-data:rwx "$WP_PATH"
sudo setfacl -R -d -m u:www-data:rwx "$WP_PATH"

# ACL pour le groupe www-data (accès complet)
sudo setfacl -R -m g:www-data:rwx "$WP_PATH"
sudo setfacl -R -d -m g:www-data:rwx "$WP_PATH"

echo "✅ ACL configurées"

# 4. Préparer les volumes externes s'ils n'existent pas
echo ""
echo "4️⃣ Préparation des volumes externes..."

WP_CONTENT_EXTERNAL="$PROJECT_PATH/wp-content"
WP_CONFIG_EXTERNAL="$PROJECT_PATH/wp-config.php"

# Si wp-content n'existe pas encore, le créer
if [ ! -d "$WP_CONTENT_EXTERNAL" ]; then
    echo "📁 Création du volume wp-content externe..."
    if [ -d "$WP_PATH/wp-content" ]; then
        cp -r "$WP_PATH/wp-content" "$WP_CONTENT_EXTERNAL"
        echo "✅ wp-content copié vers le volume externe"
    else
        mkdir -p "$WP_CONTENT_EXTERNAL"
        echo "✅ wp-content externe créé"
    fi
fi

# Si wp-config.php n'existe pas encore, le créer
if [ ! -f "$WP_CONFIG_EXTERNAL" ]; then
    echo "📄 Création du wp-config.php externe..."
    if [ -f "$WP_PATH/wp-config.php" ]; then
        cp "$WP_PATH/wp-config.php" "$WP_CONFIG_EXTERNAL"
        echo "✅ wp-config.php copié vers le volume externe"
    else
        echo "⚠️ wp-config.php non trouvé dans WordPress"
    fi
fi

# 5. Mettre à jour les fichiers docker-compose.yml
echo ""
echo "5️⃣ Mise à jour des fichiers docker-compose..."

# Fonction pour ajouter les volumes aux fichiers docker-compose
update_docker_compose() {
    local compose_file="$1"
    if [ -f "$compose_file" ]; then
        # Vérifier si les volumes externes sont déjà présents
        if ! grep -q "../../projets/$PROJECT_NAME/wp-content:/var/www/html/wp-content" "$compose_file"; then
            echo "📝 Mise à jour de $compose_file..."
            
            # Créer une sauvegarde
            cp "$compose_file" "$compose_file.backup"
            
            # Ajouter les volumes après la ligne "./wordpress:/var/www/html"
            sed -i '/- \.\/wordpress:\/var\/www\/html$/a\      - ../../projets/'$PROJECT_NAME'/wp-content:/var/www/html/wp-content\n      - ../../projets/'$PROJECT_NAME'/wp-config.php:/var/www/html/wp-config.php' "$compose_file"
            
            echo "✅ $compose_file mis à jour"
        else
            echo "ℹ️ $compose_file déjà à jour"
        fi
    fi
}

# Mettre à jour les deux fichiers docker-compose
update_docker_compose "$CONTAINER_PATH/docker-compose.yml"
update_docker_compose "$CONTAINER_PATH/docker-compose-no-nextjs.yml"

# 6. Appliquer les permissions aux volumes externes
echo ""
echo "6️⃣ Configuration des permissions sur les volumes externes..."

# wp-content
if [ -d "$WP_CONTENT_EXTERNAL" ]; then
    sudo chown -R $CURRENT_USER:www-data "$WP_CONTENT_EXTERNAL"
    find "$WP_CONTENT_EXTERNAL" -type d -exec chmod 775 {} \;
    find "$WP_CONTENT_EXTERNAL" -type f -exec chmod 664 {} \;
    
    # ACL pour wp-content
    sudo setfacl -R -m u:$CURRENT_USER:rwx "$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -d -m u:$CURRENT_USER:rwx "$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -m u:www-data:rwx "$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -d -m u:www-data:rwx "$WP_CONTENT_EXTERNAL"
    
    echo "✅ Permissions wp-content configurées"
fi

# wp-config.php
if [ -f "$WP_CONFIG_EXTERNAL" ]; then
    sudo chown $CURRENT_USER:www-data "$WP_CONFIG_EXTERNAL"
    chmod 664 "$WP_CONFIG_EXTERNAL"
    
    # ACL pour wp-config.php
    sudo setfacl -m u:$CURRENT_USER:rw "$WP_CONFIG_EXTERNAL"
    sudo setfacl -m u:www-data:rw "$WP_CONFIG_EXTERNAL"
    
    echo "✅ Permissions wp-config.php configurées"
fi

# 7. Redémarrer les conteneurs pour appliquer les changements
echo ""
echo "7️⃣ Redémarrage des conteneurs..."
cd "$CONTAINER_PATH"
echo "🔄 Arrêt des conteneurs..."
docker-compose down
echo "🚀 Démarrage avec les nouveaux volumes..."
docker-compose up -d
cd - > /dev/null

# 8. Créer un script de maintenance
echo ""
echo "8️⃣ Création du script de maintenance..."

MAINTAIN_SCRIPT="maintain_permissions_$PROJECT_NAME.sh"

cat > "$MAINTAIN_SCRIPT" << EOF
#!/bin/bash
# Script de maintenance des permissions pour $PROJECT_NAME

CONTAINER_PATH="$CONTAINER_PATH"
PROJECT_PATH="$PROJECT_PATH"
WP_PATH="$CONTAINER_PATH/wordpress"
WP_CONTENT_EXTERNAL="$PROJECT_PATH/wp-content"
WP_CONFIG_EXTERNAL="$PROJECT_PATH/wp-config.php"
CURRENT_USER="$CURRENT_USER"

echo "🔄 Maintenance des permissions WordPress pour $PROJECT_NAME..."

# Restaurer les permissions WordPress core
if [ -d "\$WP_PATH" ]; then
    sudo chgrp -R www-data "\$WP_PATH"
    find "\$WP_PATH" -type d -exec sudo chmod 775 {} \;
    find "\$WP_PATH" -type f -exec sudo chmod 664 {} \;
fi

# Restaurer les permissions volumes externes
if [ -d "\$WP_CONTENT_EXTERNAL" ]; then
    sudo chown -R \$CURRENT_USER:www-data "\$WP_CONTENT_EXTERNAL"
    find "\$WP_CONTENT_EXTERNAL" -type d -exec chmod 775 {} \;
    find "\$WP_CONTENT_EXTERNAL" -type f -exec chmod 664 {} \;
    
    sudo setfacl -R -m u:\$CURRENT_USER:rwx "\$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -d -m u:\$CURRENT_USER:rwx "\$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -m u:www-data:rwx "\$WP_CONTENT_EXTERNAL"
    sudo setfacl -R -d -m u:www-data:rwx "\$WP_CONTENT_EXTERNAL"
fi

if [ -f "\$WP_CONFIG_EXTERNAL" ]; then
    sudo chown \$CURRENT_USER:www-data "\$WP_CONFIG_EXTERNAL"
    chmod 664 "\$WP_CONFIG_EXTERNAL"
    sudo setfacl -m u:\$CURRENT_USER:rw "\$WP_CONFIG_EXTERNAL"
    sudo setfacl -m u:www-data:rw "\$WP_CONFIG_EXTERNAL"
fi

echo "✅ Permissions restaurées"
EOF

chmod +x "$MAINTAIN_SCRIPT"
echo "✅ Script de maintenance créé: $MAINTAIN_SCRIPT"

# 9. Tests de permissions
echo ""
echo "9️⃣ Tests de permissions..."

# Test de création de fichier dans wp-content
if [ -d "$WP_CONTENT_EXTERNAL" ]; then
    if touch "$WP_CONTENT_EXTERNAL/test_permissions.txt" 2>/dev/null; then
        echo "✅ Test wp-content : Création de fichier OK"
        rm "$WP_CONTENT_EXTERNAL/test_permissions.txt"
    else
        echo "❌ Test wp-content : Échec création de fichier"
    fi
fi

# Test de modification de wp-config.php
if [ -f "$WP_CONFIG_EXTERNAL" ]; then
    if echo "// Test permissions" >> "$WP_CONFIG_EXTERNAL" 2>/dev/null; then
        echo "✅ Test wp-config.php : Écriture OK"
        # Supprimer la ligne de test
        sed -i '/\/\/ Test permissions/d' "$WP_CONFIG_EXTERNAL"
    else
        echo "❌ Test wp-config.php : Échec écriture"
    fi
fi

echo ""
echo "🎉 Configuration terminée !"
echo "================================"
echo ""
echo "✅ dev-server ajouté au groupe www-data"
echo "✅ Permissions partagées configurées"
echo "✅ ACL configurées pour accès granulaire"
echo "✅ Volumes externes préparés"
echo "✅ Script de maintenance disponible"
echo ""
echo "📋 Actions maintenant possibles :"
echo "   ✅ Créer/supprimer des fichiers et dossiers"
echo "   ✅ Modifier wp-config.php directement"
echo "   ✅ Éditer tous les fichiers wp-content"
echo "   ✅ Renommer/déplacer des fichiers"
echo "   ✅ Installer/supprimer des plugins/thèmes"
echo ""
echo "🔄 Si problème de permissions :"
echo "   ./$MAINTAIN_SCRIPT"
echo ""
echo "⚠️  IMPORTANT :"
echo "   Reconnectez-vous SSH pour que l'ajout au groupe www-data soit effectif"
echo "   newgrp www-data  # ou déconnexion/reconnexion complète"
echo ""
echo "📂 Structure optimisée :"
echo "   containers/$PROJECT_NAME/     ← Configuration Docker"
echo "   projets/$PROJECT_NAME/wp-content/     ← Volume éditable"
echo "   projets/$PROJECT_NAME/wp-config.php   ← Fichier éditable"
echo "   projets/$PROJECT_NAME/nextjs/         ← Frontend éditable (si activé)" 