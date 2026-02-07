#!/bin/bash
# Configuration de la rotation automatique des logs via crontab

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ROTATE_SCRIPT="$SCRIPT_DIR/rotate_app_log.py"

echo "🔄 Configuration de la rotation automatique des logs"
echo "=" echo "📂 Dossier du projet: $PROJECT_ROOT"
echo "📄 Script de rotation: $ROTATE_SCRIPT"

# Vérifier si le script existe
if [ ! -f "$ROTATE_SCRIPT" ]; then
    echo "❌ Erreur: Script $ROTATE_SCRIPT non trouvé"
    exit 1
fi

# Rendre le script exécutable
chmod +x "$ROTATE_SCRIPT"

# Créer l'entrée cron (exécution tous les jours à 3h du matin)
CRON_LINE="0 3 * * * cd $PROJECT_ROOT && python3 $ROTATE_SCRIPT >> $PROJECT_ROOT/logs/rotation.log 2>&1"

# Vérifier si l'entrée existe déjà
if crontab -l 2>/dev/null | grep -F "$ROTATE_SCRIPT" > /dev/null; then
    echo "ℹ️  La tâche cron existe déjà"
    echo ""
    echo "📋 Tâches cron actuelles pour la rotation des logs:"
    crontab -l | grep -F "$ROTATE_SCRIPT"
else
    # Ajouter l'entrée cron
    (crontab -l 2>/dev/null; echo "# WP Launcher - Rotation des logs app.log"; echo "$CRON_LINE") | crontab -
    echo "✅ Tâche cron ajoutée avec succès"
    echo ""
    echo "📋 La rotation des logs s'exécutera tous les jours à 3h00"
    echo "   - Limite: 10 000 lignes par fichier"
    echo "   - Conservation: 7 fichiers backup (7 jours)"
    echo "   - Logs de rotation: logs/rotation.log"
fi

echo ""
echo "🔍 Pour tester manuellement la rotation:"
echo "   cd $PROJECT_ROOT && python3 $ROTATE_SCRIPT"
echo ""
echo "📊 Pour voir les logs de rotation:"
echo "   tail -f $PROJECT_ROOT/logs/rotation.log"


