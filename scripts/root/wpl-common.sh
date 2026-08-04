# Validations partagées par les helpers racine de WP Launcher.
# Fichier SOURCÉ, jamais exécuté — il ne figure donc pas dans sudoers.
#
# Tout ce qui suit part du principe que les arguments viennent d'un processus
# potentiellement compromis : l'intérêt de ces scripts est justement de rester
# sûrs même si l'application ne l'est plus.

# Emplacement du dépôt et compte du développeur. install.sh les écrit dans un
# wpl.conf posé à côté de ces scripts, appartenant à root : les variables
# d'environnement ne peuvent pas servir ici, `env_reset` étant actif dans
# sudo — et c'est heureux, sinon il suffirait d'exporter WPL_BASE_DIR pour
# faire opérer root n'importe où. Le fichier n'existe pas dans le dépôt ; les
# valeurs par défaut ne servent qu'aux tests, jamais à l'exécution privilégiée.
_wpl_conf="$(dirname "${BASH_SOURCE[0]}")/wpl.conf"
[ -r "$_wpl_conf" ] && . "$_wpl_conf"

BASE_DIR="${WPL_BASE_DIR:-/home/dev-server/Sites/wp-launcher}"
PROJECTS_DIR="$BASE_DIR/projets"
CONTAINERS_DIR="$BASE_DIR/containers"
DEV_USER="${WPL_DEV_USER:-dev-server}"
WWW_USER="www-data"

die() { echo "${0##*/}: $*" >&2; exit 1; }

# Nom de projet : jeu de caractères strict, première lettre alphanumérique.
# Le refus de commencer par un point écarte d'emblée « . » et « .. ».
valid_name() {
    local name="$1" label="${2:-nom}"
    [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$ ]] || die "$label invalide: $name"
    [[ "$name" == *".."* ]] && die "$label invalide: $name"
    return 0
}

# Sous-chemin relatif : autorise les séparateurs, interdit la remontée.
#
# Le point initial est toléré — les instances de dev vivent sous
# « .dev-instances/<slug> », et les refuser rendait leurs permissions
# irréparables. Il doit être suivi d'un caractère alphanumérique, ce qui
# écarte « . » et « .. » ; « .. » est de toute façon rejeté ensuite, où
# qu'il apparaisse. La garde qui compte reste resolve_under.
valid_subpath() {
    local sub="$1"
    [[ "$sub" =~ ^\.?[a-zA-Z0-9][a-zA-Z0-9._/-]{0,199}$ ]] || die "sous-chemin invalide: $sub"
    [[ "$sub" == *".."* ]] && die "sous-chemin invalide: $sub"
    return 0
}

# Vérifie qu'une racine résolue est bien l'une des deux racines constantes,
# ou vit dessous.
#
# Sans ce contrôle, resolve_under se laissait contourner par sa propre racine.
# Plusieurs appelants lui passent une racine DÉRIVÉE — « …/wp-content »,
# « …/.dev-instances » — c'est-à-dire un chemin que l'application peut
# remplacer par un lien symbolique. realpath résolvait alors la racine ET la
# cible à travers ce même lien : la comparaison de préfixe réussissait
# toujours, et l'opération s'appliquait où pointait le lien. Un
# « .dev-instances -> /etc » suivi d'une suppression d'instance nommée « ssl »
# donnait un rm -rf /etc/ssl en root.
assert_known_root() {
    local root_resolved="$1" projects containers
    projects="$(realpath -- "$PROJECTS_DIR")" || die "racine projets introuvable"
    containers="$(realpath -- "$CONTAINERS_DIR")" || die "racine containers introuvable"
    case "$root_resolved" in
        "$projects"|"$projects"/*|"$containers"|"$containers"/*) return 0 ;;
    esac
    die "racine non autorisée: $root_resolved"
}

# Résout le chemin et vérifie qu'il reste SOUS la racine attendue.
#
# C'est la garde qui compte : sans elle, un répertoire remplacé par un lien
# symbolique ferait appliquer l'opération ailleurs sur le système. realpath
# suit les liens, donc la comparaison porte sur la cible réelle.
#
# Reste une course résiduelle : entre cette résolution et l'usage du chemin,
# l'application peut déplacer un répertoire et lui substituer un lien. On la
# réduit en n'opérant que sur le chemin déjà résolu (donc sans traverser de
# lien), sans prétendre la supprimer — bash n'a pas d'équivalent des appels
# *at(). Ce qui est fermé ici, ce sont les contournements déterministes.
#
# Affiche le chemin résolu sur stdout.
resolve_under() {
    local target="$1" root="$2"
    [ -e "$target" ] || die "chemin inexistant: $target"
    local resolved root_resolved
    resolved="$(realpath -- "$target")" || die "résolution impossible: $target"
    root_resolved="$(realpath -- "$root")" || die "racine introuvable: $root"
    assert_known_root "$root_resolved"
    case "$resolved" in
        "$root_resolved"/*) printf '%s\n' "$resolved" ;;
        *) die "chemin hors de $root_resolved: $resolved" ;;
    esac
}
