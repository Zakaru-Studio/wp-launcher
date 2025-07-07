#!/bin/bash

# Script pour corriger les permissions de tous les projets WordPress Launcher
# Permet à dev-server d'avoir un accès complet à tous les fichiers

echo "🔑 WordPress Launcher - Correction des permissions"
echo "=================================================="

# Vérifier si on est dans le bon répertoire
if [ ! -d "projets" ] || [ ! -d "containers" ]; then
    echo "❌ Erreur: Ce script doit être exécuté depuis le répertoire wp-launcher"
    echo "   Répertoire actuel: $(pwd)"
    echo "   Utilisez: cd /home/dev-server/Sites/wp-launcher && ./fix_permissions.sh"
    exit 1
fi

echo "📂 Correction des permissions pour le dossier projets/..."
sudo chown -R dev-server:dev-server projets/
sudo chmod -R 755 projets/
echo "✅ Permissions projets/ corrigées"

echo "📂 Correction des permissions pour le dossier containers/..."
sudo chown -R dev-server:dev-server containers/
sudo chmod -R 755 containers/
echo "✅ Permissions containers/ corrigées"

echo ""
echo "🎉 Toutes les permissions ont été corrigées !"
echo "💡 dev-server peut maintenant modifier tous les fichiers des projets"
echo ""
echo "📋 Permissions appliquées:"
echo "   • Propriétaire: dev-server:dev-server"
echo "   • Permissions: 755 (rwxr-xr-x)"
echo "   • Accès: Lecture/écriture/exécution pour dev-server"
echo ""
echo "✅ Vous pouvez maintenant éditer les fichiers via SSH/Cursor sans problème" 