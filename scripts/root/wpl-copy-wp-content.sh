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

# La destination finale doit être validée elle aussi : --no-links ne protège
# que la SOURCE. Un « …/wp-content/plugins » remplacé par un lien vers
# /opt/wp-launcher-root faisait écrire rsync à travers le lien, en root, et
# écrasait les helpers eux-mêmes — donc un shell root à l'appel suivant.
DEST_FINAL="$DEST_R/$3"
[ -L "$DEST_FINAL" ] && die "destination liée: $DEST_FINAL"
mkdir -p -- "$DEST_FINAL"
DEST_FINAL="$(resolve_under "$DEST_FINAL" "$PROJECTS_DIR")"

# --safe-links plutôt que --no-links : une instance ne doit pas hériter d'un
# lien du parent qui sortirait de l'arborescence copiée, mais elle a toutes
# les raisons de garder les liens internes. --no-links écartait les deux, et
# faisait donc disparaître sans un mot un thème ou un plugin lié depuis le
# poste du développeur. Les liens écartés sont signalés ci-dessous : rsync ne
# les mentionne que sur stderr, et sort malgré tout en 0.
RSYNC_ERR="$(mktemp)"
trap 'rm -f -- "$RSYNC_ERR"' EXIT

# Un échec de rsync doit rester fatal : la copie est un préalable au reste de
# la création d'instance. On ne détourne stderr que pour pouvoir le rapporter,
# jamais pour l'ignorer.
if ! rsync -a --safe-links --exclude=.git -- "$SRC_R/" "$DEST_FINAL/" 2>"$RSYNC_ERR"; then
    cat "$RSYNC_ERR" >&2
    die "échec de la copie de $3"
fi

chown -R "$DEV_USER:$DEV_USER" "$DEST_FINAL"

if [ -s "$RSYNC_ERR" ]; then
    echo "${0##*/}: liens ignorés lors de la copie de $3 :"
    sed 's/^/  /' "$RSYNC_ERR"
fi
echo "${0##*/}: $3 copié vers $DEST_FINAL"
