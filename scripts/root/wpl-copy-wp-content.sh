#!/bin/bash
# Copie un sous-dossier de wp-content du parent vers une instance de dev.
#   wpl-copy-wp-content.sh <projet-parent> <slug> <sous-dossier>
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 3 ] || die "usage: $0 <projet-parent> <slug> <sous-dossier>"
valid_name "$1" "projet parent"
valid_name "$2" "slug d'instance"
valid_name "$3" "sous-dossier"

SRC="$PROJECTS_DIR/$1/wp-content/$3"
DEST_PARENT="$PROJECTS_DIR/$1/.dev-instances/$2/wp-content"

[ -d "$SRC" ] || die "source absente: $SRC"
[ -d "$DEST_PARENT" ] || die "destination absente: $DEST_PARENT"

SRC_R="$(resolve_under "$SRC" "$PROJECTS_DIR/$1/wp-content")"
DEST_R="$(resolve_under "$DEST_PARENT" "$PROJECTS_DIR/$1/.dev-instances")"

# --no-links : une instance ne doit pas hériter d'un lien du parent qui
# pointerait hors de l'arborescence.
rsync -a --no-links --exclude=.git -- "$SRC_R/" "$DEST_R/$3/"
chown -R "$DEV_USER:$DEV_USER" "$DEST_R/$3"
echo "${0##*/}: $3 copié vers $DEST_R"
