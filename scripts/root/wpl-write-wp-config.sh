#!/bin/bash
# Écrit wp-config.php quand l'app n'a pas les droits.
#   wpl-write-wp-config.sh <projet>  < contenu
#
# Le contenu arrive par l'entrée standard, pas par un chemin de fichier.
# La version précédente prenait un temporaire dans /tmp, vérifiait qu'il
# n'était pas un lien symbolique, puis le copiait : entre les deux, l'appelant
# — qui est aussi l'attaquant dans notre modèle — pouvait le remplacer par un
# lien vers n'importe quel fichier de root, dont le contenu atterrissait dans
# wp-config.php puis redevenait lisible via le profil wp-config-dev. Sans
# chemin source, cette course n'existe plus.
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 1 ] || die "usage: $0 <projet> < contenu"
valid_name "$1" "nom de projet"

PROJECT_DIR="$(resolve_under "$PROJECTS_DIR/$1" "$PROJECTS_DIR")"
DEST="$PROJECT_DIR/wp-config.php"

# Temporaire créé par root DANS le répertoire projet : nom imprévisible, créé
# en O_EXCL, donc impossible à pré-positionner. On lui donne son propriétaire
# et ses droits définitifs avant la bascule, pour ne pas laisser de fenêtre
# entre la mise en place et le chown.
TMP="$(mktemp -- "$PROJECT_DIR/.wp-config.XXXXXXXX")" || die "temporaire impossible"
trap 'rm -f -- "$TMP"' EXIT

cat > "$TMP"
[ -s "$TMP" ] || die "contenu vide, écriture refusée"

chown "$WWW_USER:$WWW_USER" "$TMP"
chmod 640 "$TMP"

# mv -T et non cp : rename() ne suit pas un lien symbolique de destination,
# il le remplace. Un wp-config.php transformé en lien vers un fichier système
# ne peut donc pas détourner l'écriture.
mv -Tf -- "$TMP" "$DEST"
trap - EXIT

echo "${0##*/}: wp-config.php écrit pour $1"
