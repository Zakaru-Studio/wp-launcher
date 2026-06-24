#!/bin/bash

# Script d'initialisation des permissions WordPress - Version permissions partagées renforcée
# S'assure que dev-server (UID 1000) et www-data peuvent tous les deux éditer les fichiers
#
# PERFORMANCE : les opérations récursives utilisent `-exec ... +` (batché) et non
# `-exec ... \;` (un fork par fichier). Le balayage récursif LOURD de wp-content
# (chmod/chown/setfacl sur uploads, qui peut contenir des centaines de milliers de
# fichiers) n'est exécuté qu'UNE seule fois, marqué par une sentinelle. Les démarrages
# suivants ne réappliquent que les permissions légères (racine, wp-config, dossiers
# critiques) + l'héritage ACL par défaut, ce qui rend le boot quasi instantané.
#
# Pour forcer un rebalayage complet : supprimer le fichier sentinelle
#   wp-content/.wp-launcher-perms-done  (ou positionner FORCE_DEEP_PERMISSIONS=true)

echo "🔧 Initialisation des permissions WordPress partagées renforcées..."

# Pas d'attente bloquante : ce script est lancé en arrière-plan par l'entrypoint,
# Apache démarre en parallèle. Un petit délai laisse les volumes se monter.
sleep 2

# Variables d'environnement pour les utilisateurs
DEV_USER_UID=${DEV_USER_UID:-1000}
DEV_USER_GID=${DEV_USER_GID:-1000}
WWW_DATA_UID=${WWW_DATA_UID:-33}
WWW_DATA_GID=${WWW_DATA_GID:-33}

SENTINEL="/var/www/html/wp-content/.wp-launcher-perms-done"

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
if ! grep -q "www-data ALL=(ALL) NOPASSWD: /bin/chown, /bin/chmod" /etc/sudoers 2>/dev/null; then
    echo "www-data ALL=(ALL) NOPASSWD: /bin/chown, /bin/chmod" >> /etc/sudoers 2>/dev/null || true
fi

# Décider si le balayage récursif LOURD doit être exécuté
DEEP=1
if [ -f "$SENTINEL" ] && [ "${FORCE_DEEP_PERMISSIONS:-false}" != "true" ]; then
    DEEP=0
    echo "⏭️  Permissions déjà initialisées (sentinelle présente) → balayage récursif ignoré."
    echo "    (supprimer $SENTINEL ou FORCE_DEEP_PERMISSIONS=true pour forcer)"
fi

# ===== PERMISSIONS RACINE WORDPRESS (légères, à chaque démarrage) =====
echo "🔧 Configuration des permissions WordPress racine (/var/www/html)..."

# Permissions: 755 pour le dossier racine, 644 pour les fichiers de premier niveau
find /var/www/html -maxdepth 0 -exec chmod 755 {} + 2>/dev/null || true
find /var/www/html -maxdepth 1 -type f -exec chmod 644 {} + 2>/dev/null || true
chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html 2>/dev/null || true

if [ "$DEEP" = "1" ]; then
    # Nettoyer les ACL héritées (Samba) qui peuvent bloquer les écritures
    if command -v setfacl >/dev/null 2>&1; then
        echo "🧹 Nettoyage des ACL restrictives sur wp-admin / wp-includes..."
        setfacl -Rb /var/www/html/wp-admin 2>/dev/null || true
        setfacl -Rb /var/www/html/wp-includes 2>/dev/null || true
    fi

    # Dossiers de premier niveau (hors wp-content) en 755
    find /var/www/html -mindepth 1 -maxdepth 1 -type d ! -name wp-content -exec chmod -R 755 {} + 2>/dev/null || true

    # Dossiers critiques pour les mises à jour WordPress
    for core_dir in wp-admin wp-includes; do
        if [ -d "/var/www/html/$core_dir" ]; then
            echo "📁 Permissions $core_dir..."
            chown -R $WWW_DATA_UID:$WWW_DATA_GID "/var/www/html/$core_dir" 2>/dev/null || true
            find "/var/www/html/$core_dir" -type d -exec chmod 755 {} + 2>/dev/null || true
            find "/var/www/html/$core_dir" -type f -exec chmod 644 {} + 2>/dev/null || true
        fi
    done
fi

echo "✅ Permissions racine WordPress configurées"

# Configuration RENFORCÉE des permissions wp-content
if [ -d "/var/www/html/wp-content" ]; then
    echo "✅ Configuration de wp-content avec permissions partagées..."

    # S'assurer que les dossiers critiques existent (toujours, rapide)
    mkdir -p /var/www/html/wp-content/plugins 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/themes 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/uploads 2>/dev/null || true
    mkdir -p /var/www/html/wp-content/upgrade 2>/dev/null || true

    # Permissions LÉGÈRES (à chaque démarrage) : sur les dossiers de premier niveau
    # uniquement, sans descendre dans uploads. www-data propriétaire du dossier
    # wp-content lui-même.
    chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/wp-content 2>/dev/null || true
    chmod 777 /var/www/html/wp-content 2>/dev/null || true
    for dir in plugins themes uploads upgrade; do
        if [ -d "/var/www/html/wp-content/$dir" ]; then
            chmod 777 "/var/www/html/wp-content/$dir" 2>/dev/null || true
        fi
    done

    # Héritage ACL par défaut (non récursif, donc rapide) : tout nouveau fichier
    # créé sous wp-content sera éditable par dev-server ET www-data.
    if command -v setfacl >/dev/null 2>&1; then
        setfacl -m u:$DEV_USER_UID:rwx -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        setfacl -d -m u:$DEV_USER_UID:rwx -d -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        for dir in plugins themes uploads upgrade; do
            if [ -d "/var/www/html/wp-content/$dir" ]; then
                setfacl -m u:$DEV_USER_UID:rwx -m u:$WWW_DATA_UID:rwx "/var/www/html/wp-content/$dir" 2>/dev/null || true
                setfacl -d -m u:$DEV_USER_UID:rwx -d -m u:$WWW_DATA_UID:rwx "/var/www/html/wp-content/$dir" 2>/dev/null || true
            fi
        done
    fi

    if [ "$DEEP" = "1" ]; then
        echo "🔁 Balayage récursif complet de wp-content (une seule fois, batché)..."

        # Nettoyer les ACL Samba héritées sur wp-content avant de reconfigurer
        if command -v setfacl >/dev/null 2>&1; then
            setfacl -Rb /var/www/html/wp-content 2>/dev/null || true
        fi

        # Propriétaire www-data, permissions permissives. `-exec ... +` = batché.
        chown -R $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/wp-content 2>/dev/null || true
        find /var/www/html/wp-content -type d -exec chmod 777 {} + 2>/dev/null || true
        find /var/www/html/wp-content -type f -exec chmod 666 {} + 2>/dev/null || true

        # ACL récursives complètes (une seule fois)
        if command -v setfacl >/dev/null 2>&1; then
            echo "🔒 Configuration des ACL récursives..."
            setfacl -R -m u:$DEV_USER_UID:rwx -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
            setfacl -R -d -m u:$DEV_USER_UID:rwx -d -m u:$WWW_DATA_UID:rwx /var/www/html/wp-content 2>/dev/null || true
        fi

        # Marquer comme initialisé pour éviter de refaire ce balayage à chaque boot
        touch "$SENTINEL" 2>/dev/null || true
        chown $WWW_DATA_UID:$WWW_DATA_GID "$SENTINEL" 2>/dev/null || true
        echo "✅ Balayage récursif terminé, sentinelle posée."
    fi

    echo "✅ wp-content configuré"
fi

# Permissions fichiers de base (toujours, rapide)
if [ -f "/var/www/html/.htaccess" ]; then
    chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/.htaccess 2>/dev/null || true
    chmod 666 /var/www/html/.htaccess 2>/dev/null || true
fi

if [ -f "/var/www/html/wp-config.php" ]; then
    chown $WWW_DATA_UID:$WWW_DATA_GID /var/www/html/wp-config.php 2>/dev/null || true
    chmod 666 /var/www/html/wp-config.php 2>/dev/null || true
fi

# Test d'écriture pour vérifier que www-data peut vraiment écrire
echo "🧪 Test d'écriture pour www-data..."
if [ -d "/var/www/html/wp-content" ]; then
    su -s /bin/bash www-data -c "touch /var/www/html/wp-content/test-write-www-data.txt" 2>/dev/null && echo "✅ www-data peut écrire dans wp-content" || echo "❌ www-data ne peut PAS écrire dans wp-content"
    rm -f /var/www/html/wp-content/test-write-www-data.txt 2>/dev/null || true
fi

echo "✅ Permissions partagées initialisées avec succès"
echo "👥 Utilisateurs autorisés:"
echo "   - www-data (UID:$WWW_DATA_UID) : propriétaire des fichiers WordPress"
echo "   - dev-server (UID:$DEV_USER_UID) : accès en écriture via ACL/groupes"
echo "🔄 Fin du script d'initialisation des permissions."
