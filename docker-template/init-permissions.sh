#!/bin/bash

# Script d'initialisation des permissions WordPress - Version permissions partagées renforcée
# S'assure que dev-server (UID 1000) et www-data peuvent tous les deux éditer les fichiers

echo "🔧 Initialisation des permissions WordPress partagées renforcées..."

# Attendre que les volumes soient montés
sleep 2

# Variables d'environnement pour les utilisateurs
DEV_USER_UID=${DEV_USER_UID:-1000}
DEV_USER_GID=${DEV_USER_GID:-1000}
WWW_DATA_UID=${WWW_DATA_UID:-33}
WWW_DATA_GID=${WWW_DATA_GID:-33}

echo "👥 Configuration des utilisateurs partagés:"
echo "   - dev-server: UID=$DEV_USER_UID, GID=$DEV_USER_GID"
echo "   - www-data: UID=$WWW_DATA_UID, GID=$WWW_DATA_GID"

# Créer l'utilisateur dev-server dans le conteneur s'il n'existe pas
if ! id dev-server 2>/dev/null; then
    echo "➕ Création de l'utilisateur dev-server dans le conteneur..."
    groupadd -g $DEV_USER_GID dev-server 2>/dev/null || true
    useradd -u $DEV_USER_UID -g $DEV_USER_GID -s /bin/bash dev-server 2>/dev/null || true
fi

# Ajouter dev-server au groupe www-data ET www-data au groupe dev-server
echo "🔗 Configuration des groupes partagés..."
usermod -a -G www-data dev-server 2>/dev/null || true
usermod -a -G dev-server www-data 2>/dev/null || true

# S'assurer que www-data peut utiliser sudo pour les permissions (si besoin)
echo "www-data ALL=(ALL) NOPASSWD: /bin/chown, /bin/chmod" >> /etc/sudoers 2>/dev/null || true

# Configuration RENFORCÉE des permissions wp-content
if [ -d "/var/www/html/wp-content" ]; then
    echo "✅ Configuration RENFORCÉE de wp-content avec permissions partagées..."
    
    # Méthode 1: Propriétaire www-data, Groupe www-data, mais avec permissions 777 temporaires
    chown -R $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/wp-content 2>/dev/null || true
    
    # Permissions très permissives pour s'assurer que tout fonctionne
    find /var/www/html/wp-content -type d -exec chmod 777 {} \; 2>/dev/null || true
    find /var/www/html/wp-content -type f -exec chmod 666 {} \; 2>/dev/null || true
    
    # S'assurer que les dossiers critiques existent et ont les bonnes permissions
    mkdir -p /var/www/html/wp-content/plugins 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/themes 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/uploads 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/upgrade 2>/dev/null || true
    
    # Permissions spéciales pour tous les dossiers critiques
    for dir in plugins themes uploads upgrade; do
        if [ -d "/var/www/html/wp-content/$dir" ]; then
            echo "📁 Configuration spéciale $dir..."
            chown -R $WWW_DATA_UID:$WWW_DATA_GID "/var/www/html/wp-content/$dir" 2>/dev/null || true
            find "/var/www/html/wp-content/$dir" -type d -exec chmod 777 {} \; 2>/dev/null || true
            find "/var/www/html/wp-content/$dir" -type f -exec chmod 666 {} \; 2>/dev/null || true
        fi
    done
    
    # Ajouter des ACL si disponibles
    if command -v setfacl >/dev/null 2>&1; then
        echo "🔒 Configuration des ACL..."
        setfacl -R -m u:$DEV_USER_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        setfacl -R -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        setfacl -R -d -m u:$DEV_USER_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        setfacl -R -d -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
    fi
    
    echo "✅ wp-content configuré avec permissions renforcées"
fi

# Permissions fichiers de base (www-data en propriétaire pour éviter les conflits)
if [ -f "/var/www/html/.htaccess" ]; then
    echo "📄 Configuration .htaccess avec permissions www-data..."
    chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/.htaccess 2>/dev/null || true
    chmod 666 /var/www/html/.htaccess 2>/dev/null || true
fi

if [ -f "/var/www/html/wp-config.php" ]; then
    echo "📄 Configuration wp-config.php avec permissions www-data..."
    chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/wp-config.php 2>/dev/null || true
    chmod 666 /var/www/html/wp-config.php 2>/dev/null || true
fi

# Test d'écriture pour vérifier que www-data peut vraiment écrire
echo "🧪 Test d'écriture pour www-data..."
if [ -d "/var/www/html/wp-content" ]; then
    su -s /bin/bash www-data -c "touch /var/www/html/wp-content/test-write-www-data.txt" 2>/dev/null && echo "✅ www-data peut écrire" || echo "❌ www-data ne peut PAS écrire"
    rm -f /var/www/html/wp-content/test-write-www-data.txt 2>/dev/null || true
fi

# Test d'écriture pour dev-server aussi
if [ -d "/var/www/html/wp-content" ]; then
    su -s /bin/bash dev-server -c "touch /var/www/html/wp-content/test-write-dev-server.txt" 2>/dev/null && echo "✅ dev-server peut écrire" || echo "❌ dev-server ne peut PAS écrire"
    rm -f /var/www/html/wp-content/test-write-dev-server.txt 2>/dev/null || true
fi

# Vérifier les permissions finales
echo "🔍 Vérification des permissions finales:"
if [ -d "/var/www/html/wp-content" ]; then
    ls -la /var/www/html/wp-content/ | head -5
    echo "Permissions du dossier wp-content:"
    ls -ld /var/www/html/wp-content/
    if [ -d "/var/www/html/wp-content/plugins" ]; then
        echo "Permissions du dossier plugins:"
        ls -ld /var/www/html/wp-content/plugins/
    fi
fi

echo "✅ Permissions partagées renforcées initialisées avec succès"
echo "👥 Utilisateurs autorisés:"
echo "   - www-data (UID:$WWW_DATA_UID) : propriétaire des fichiers WordPress"
echo "   - dev-server (UID:$DEV_USER_UID) : accès en écriture via ACL/groupes"
echo "🔄 Retour au script d'entrypoint principal..." 