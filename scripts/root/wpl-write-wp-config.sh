#!/bin/bash
# Écrit wp-config.php quand l'app n'a pas les droits.
#   wpl-write-wp-config.sh <projet> <fichier-source>
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 2 ] || die "usage: $0 <projet> <fichier-source>"
valid_name "$1" "nom de projet"
SRC="$2"

# La source est un temporaire écrit par l'app. On exige un fichier régulier :
# un lien symbolique permettrait de faire lire n'importe quoi à root.
[ -f "$SRC" ] || die "source absente ou non régulière: $SRC"
[ -L "$SRC" ] && die "la source ne peut pas être un lien symbolique: $SRC"
case "$SRC" in /tmp/*|/var/tmp/*) ;; *) die "source hors des répertoires temporaires: $SRC" ;; esac

PROJECT_DIR="$(resolve_under "$PROJECTS_DIR/$1" "$PROJECTS_DIR")"
DEST="$PROJECT_DIR/wp-config.php"
[ -L "$DEST" ] && die "la destination est un lien symbolique: $DEST"

cp -- "$SRC" "$DEST"
chown "$WWW_USER:$WWW_USER" "$DEST"
chmod 640 "$DEST"
echo "${0##*/}: wp-config.php écrit pour $1"
