#!/bin/bash
# Retire un fichier de configuration de projet corrompu (typiquement créé en
# dossier au lieu de fichier par un bind mount Docker).
#   wpl-reset-config.sh <projet> <php|mysql>
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 2 ] || die "usage: $0 <projet> <php|mysql>"
valid_name "$1" "nom de projet"

case "$2" in
    php)   REL="config/php.ini" ;;
    mysql) REL="config/mysql.cnf" ;;
    *)     die "type inconnu: $2 (php|mysql)" ;;
esac

TARGET="$PROJECTS_DIR/$1/$REL"
[ -e "$TARGET" ] || { echo "${0##*/}: absent, rien à faire: $TARGET"; exit 0; }
RESOLVED="$(resolve_under "$TARGET" "$PROJECTS_DIR/$1")"
echo "${0##*/}: suppression de $RESOLVED"
rm -rf -- "$RESOLVED"
