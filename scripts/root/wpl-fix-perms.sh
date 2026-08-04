#!/bin/bash
#
# Applique un profil de permissions à un projet. Lancé en root via sudo.
#
#     wpl-fix-perms.sh <projet> <profil> [sous-chemin]
#
# Ce script existe pour retirer `NOPASSWD: ALL` à l'utilisateur applicatif.
# L'app faisait 71 appels `sudo chown/chmod/find/setfacl/chgrp` sur des chemins
# qu'elle composait elle-même ; chacun était une porte ouverte si une injection
# de commande atteignait l'un d'eux. Ils se ramènent tous aux quelques profils
# ci-dessous, sur un chemin qui ne peut pas sortir de l'arborescence du projet.
#
# Règles de sûreté, dans l'ordre où elles s'appliquent :
#   1. le nom de projet est validé sur une liste de caractères stricte ;
#   2. le sous-chemin optionnel est validé et ne peut contenir « .. » ;
#   3. le chemin final est résolu puis vérifié comme étant SOUS la racine des
#      projets — un lien symbolique pointant ailleurs est donc rejeté ;
#   4. le profil est choisi dans une liste fermée, jamais construit.
#
# Ce fichier doit appartenir à root et ne pas être modifiable par l'utilisateur
# applicatif, sinon il suffirait de le réécrire pour obtenir un shell root.

set -euo pipefail

BASE_DIR="${WPL_BASE_DIR:-/home/dev-server/Sites/wp-launcher}"
PROJECTS_DIR="$BASE_DIR/projets"
DEV_USER="${WPL_DEV_USER:-dev-server}"
WWW_USER="www-data"

die() { echo "wpl-fix-perms: $*" >&2; exit 1; }

[ $# -ge 2 ] || die "usage: $0 <projet> <profil> [sous-chemin]"

PROJECT="$1"
PROFILE="$2"
SUBPATH="${3:-}"

# ─── 1. nom de projet ─────────────────────────────────────────────────────
[[ "$PROJECT" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$ ]] \
    || die "nom de projet invalide: $PROJECT"
[[ "$PROJECT" == *".."* ]] && die "nom de projet invalide: $PROJECT"

# ─── 2. sous-chemin ───────────────────────────────────────────────────────
if [ -n "$SUBPATH" ]; then
    [[ "$SUBPATH" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,199}$ ]] \
        || die "sous-chemin invalide: $SUBPATH"
    [[ "$SUBPATH" == *".."* ]] && die "sous-chemin invalide: $SUBPATH"
    TARGET="$PROJECTS_DIR/$PROJECT/$SUBPATH"
else
    TARGET="$PROJECTS_DIR/$PROJECT"
fi

[ -e "$TARGET" ] || die "chemin inexistant: $TARGET"

# ─── 3. le chemin résolu doit rester sous la racine des projets ───────────
# realpath suit les liens symboliques : un wp-content pointant vers /etc est
# donc écarté ici, pas après le chown.
RESOLVED="$(realpath -- "$TARGET")"
RESOLVED_BASE="$(realpath -- "$PROJECTS_DIR")"
case "$RESOLVED" in
    "$RESOLVED_BASE"/*) ;;
    *) die "chemin hors de $RESOLVED_BASE: $RESOLVED" ;;
esac

# ─── 4. profils ───────────────────────────────────────────────────────────
# `-exec … +` et non `\;` : un fork par fichier sur une arborescence
# d'uploads volumineuse prenait des heures et bloquait le démarrage d'Apache.
apply() {
    local owner="$1" dirmode="$2" filemode="$3"
    chown -R "$owner" "$RESOLVED"
    find "$RESOLVED" -type d -exec chmod "$dirmode" {} +
    find "$RESOLVED" -type f -exec chmod "$filemode" {} +
}

case "$PROFILE" in
    # Le développeur possède, www-data écrit via le groupe. Profil courant.
    shared)      apply "$DEV_USER:$WWW_USER" 775 664 ;;
    # Tout à www-data : le conteneur écrit, l'hôte lit.
    www)         apply "$WWW_USER:$WWW_USER" 775 664 ;;
    # Tout au développeur : édition depuis l'hôte.
    dev)         apply "$DEV_USER:$DEV_USER" 755 644 ;;
    # wp-content côté conteneur, plus restrictif.
    container)   apply "$WWW_USER:$WWW_USER" 755 644 ;;
    # Uploads : www-data doit pouvoir créer des fichiers.
    uploads)     apply "$DEV_USER:$WWW_USER" 775 664 ;;

    # wp-config.php seul : lisible par le conteneur uniquement.
    wp-config-lock)
        [ -f "$RESOLVED" ] || die "wp-config-lock attend un fichier"
        chown "$WWW_USER:$WWW_USER" "$RESOLVED"
        chmod 600 "$RESOLVED"
        ;;
    # wp-config.php seul : éditable depuis l'hôte.
    wp-config-dev)
        [ -f "$RESOLVED" ] || die "wp-config-dev attend un fichier"
        chown "$DEV_USER:$WWW_USER" "$RESOLVED"
        chmod 664 "$RESOLVED"
        ;;

    # ACL pour que www-data conserve l'écriture sur les fichiers créés
    # ensuite. Le masque est réaffirmé : un chmod le rabat sinon à r-x et
    # retire silencieusement le droit d'écriture (bug récurrent).
    acl)
        command -v setfacl >/dev/null || die "setfacl absent"
        setfacl -R -m "u:$DEV_USER:rwx" -m "g:$WWW_USER:rwx" -m "m::rwX" "$RESOLVED"
        setfacl -R -d -m "u:$DEV_USER:rwx" -m "g:$WWW_USER:rwx" -m "m::rwX" "$RESOLVED"
        ;;

    *) die "profil inconnu: $PROFILE" ;;
esac

echo "wpl-fix-perms: $PROFILE appliqué à $RESOLVED"
