"""Écriture de ``wp-config.php``.

Deux contraintes que l'écriture naïve (``open(path, 'w')``) ne respecte pas,
et qui expliquent le « Permission denied » du gestionnaire WP Debug :

1. **L'inode.** ``wp-config.php`` est monté fichier par fichier dans le
   conteneur (``projets/<site>/wp-config.php:/var/www/html/wp-config.php``).
   Un bind mount de fichier attache l'inode, pas le chemin : écrire dans un
   temporaire puis le renommer par-dessus laisse le conteneur sur l'ANCIEN
   contenu jusqu'au prochain ``docker restart``. Le réglage apparaîtrait
   activé dans l'interface sans que WordPress le voie. L'écriture doit donc
   se faire en place, par troncature de l'inode existant.

2. **Le masque ACL.** Le fichier appartient à ``www-data`` et porte des ACL
   (héritées de Samba, ou posées par ``init-permissions.sh``). Un ``chmod``
   en 644 — le conteneur en fait un à chaque démarrage sur les fichiers de
   la racine WordPress — rabat le masque ACL à ``r--`` et retire donc
   silencieusement le droit d'écriture au groupe ``www-data``, dont
   l'utilisateur applicatif fait pourtant partie. D'où un ``PermissionError``
   sur un fichier qui semble en groupe rwx.

On ne contourne pas ce second point au coup par coup : on réapplique le
profil ``wp-config-dev`` (``dev-server:www-data`` en 664, ce qui repositionne
aussi le masque), ce qui rend la main DURABLEMENT, puis on réessaie. Les
écritures suivantes n'ont plus besoin de sudo.
"""
import os
from typing import Optional

from app.utils import root_helpers


class WpConfigWriteError(RuntimeError):
    """wp-config.php n'a pas pu être écrit."""


def _write_in_place(path: str, data: bytes) -> None:
    """Remplace le contenu SANS changer d'inode (cf. bind mount fichier).

    On écrit d'abord, on tronque ensuite à la position courante : une
    troncature préalable laisserait le fichier vide si l'écriture échouait
    en cours de route, et un wp-config.php vide met le site hors ligne.
    """
    fd = os.open(path, os.O_WRONLY)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
        fh.truncate()


def _reclaim(path: str) -> None:
    """Rend le fichier accessible à l'utilisateur applicatif, durablement.

    Le profil ``wp-config-dev`` est fermé côté helper racine : il repose
    ``dev-server:www-data`` en 664 sur CE fichier et rien d'autre. Le chmod
    repositionne aussi le masque ACL, qui est le vrai coupable des refus.
    """
    if not root_helpers.available():
        raise WpConfigWriteError(
            f"{path} n'est pas accessible et les helpers racine ne sont pas "
            f"installés ({root_helpers.ROOT_HELPERS_DIR}) — relancer install.sh."
        )
    try:
        root_helpers.fix_perms(path, 'wp-config-dev', timeout=30)
    except root_helpers.RootHelperError as exc:
        raise WpConfigWriteError(
            f"Droits insuffisants sur {path} et récupération impossible: {exc}"
        ) from exc


def read_wp_config(path: str) -> str:
    """Lit wp-config.php, en reprenant les droits si l'app les a perdus.

    Le profil ``wp-config-lock`` (600 www-data) et un simple chmod 644 sur un
    fichier porteur d'ACL suffisent à rendre le fichier illisible depuis
    l'application. Lire devait donc pouvoir se rattraper comme écrire, sinon
    l'écran WP Debug tombait en erreur avant même d'afficher les cases.
    """
    if not os.path.isfile(path):
        raise WpConfigWriteError(f"wp-config.php introuvable: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return fh.read()
    except PermissionError:
        pass

    _reclaim(path)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return fh.read()
    except PermissionError as exc:
        raise WpConfigWriteError(
            f"{path} reste illisible après application du profil "
            f"wp-config-dev: {exc}"
        ) from exc


def write_wp_config(path: str, content: str) -> None:
    """Écrit ``content`` dans le ``wp-config.php`` désigné par ``path``.

    Reprend les droits via le helper racine si l'utilisateur applicatif ne
    les a plus. Lève ``WpConfigWriteError`` si même cela ne suffit pas —
    jamais de succès silencieux, l'appelant doit pouvoir le dire à
    l'utilisateur.
    """
    if not os.path.isfile(path):
        raise WpConfigWriteError(f"wp-config.php introuvable: {path}")

    data = content.encode('utf-8')

    try:
        _write_in_place(path, data)
        return
    except PermissionError:
        pass

    _reclaim(path)

    try:
        _write_in_place(path, data)
    except PermissionError as exc:
        raise WpConfigWriteError(
            f"Droits insuffisants sur {path} même après application du "
            f"profil wp-config-dev: {exc}"
        ) from exc


def ensure_writable(path: str) -> Optional[str]:
    """Rend ``path`` inscriptible par l'application, sans l'écrire.

    Renvoie None si c'était déjà le cas, sinon le message du helper. Sert
    aux appelants qui veulent préparer le terrain avant une série
    d'écritures.
    """
    if os.access(path, os.W_OK):
        return None
    if not root_helpers.available():
        raise WpConfigWriteError(
            f"{path} non inscriptible et helpers racine absents."
        )
    return root_helpers.fix_perms(path, 'wp-config-dev', timeout=30)
