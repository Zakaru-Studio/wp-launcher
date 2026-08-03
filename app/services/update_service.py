#!/usr/bin/env python3
"""
Mise à jour de l'application depuis les releases GitHub.

Le déploiement est un checkout Git : mettre à jour revient donc à avancer
la copie de travail jusqu'au tag de la dernière release, puis à redémarrer
le service.

Garde-fous (l'objectif est de ne jamais laisser une installation cassée) :
  * refus si la copie de travail contient des modifications locales — une
    mise à jour ne doit jamais écraser du travail en cours ;
  * avance rapide uniquement : si le tag n'est pas un descendant direct de
    HEAD, on s'arrête plutôt que de forcer ;
  * les dépendances ne sont réinstallées que si `requirements.txt` a changé ;
  * en cas d'échec après le déplacement du HEAD, retour automatique au
    commit de départ.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from app.utils.logger import wp_logger
from app.utils.version_utils import get_app_version


def _current_version() -> str:
    """
    Version installée, résolue à chaque appel.

    On passe par `get_app_version()` — qui consulte l'archive puis le tag Git
    avant de retomber sur la constante — et non par `__version__` : cette
    constante n'est qu'un repli de dernier recours, et la lire à l'import
    figerait la valeur, donc l'afficherait périmée juste après une mise à
    jour. Le comparateur doit voir la même version que la barre latérale.
    """
    return get_app_version().lstrip('v')

# Fenêtre de cache : l'API GitHub non authentifiée est limitée à 60 appels
# par heure et par IP, et le bouton est interrogé à chaque chargement de page.
_CACHE_TTL_SECONDS = 3600
_HTTP_TIMEOUT = 8
_GIT_TIMEOUT = 120
_PIP_TIMEOUT = 600

_cache = {'fetched_at': 0, 'payload': None}
_lock = threading.Lock()


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(args, timeout=_GIT_TIMEOUT):
    """Exécute une commande dans la racine du projet et renvoie (ok, sortie)."""
    try:
        proc = subprocess.run(
            args, cwd=_project_root(), capture_output=True, text=True, timeout=timeout
        )
        out = (proc.stdout or '') + (proc.stderr or '')
        return proc.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, f"délai dépassé ({timeout}s) : {' '.join(args)}"
    except FileNotFoundError:
        return False, f"commande introuvable : {args[0]}"


def parse_version(value: str):
    """'v1.4.1' -> (1, 4, 1). Renvoie None si non parsable."""
    if not value:
        return None
    m = re.match(r'^v?(\d+)\.(\d+)(?:\.(\d+))?', value.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_newer(latest: str, current: str) -> bool:
    """Compare deux versions numériquement (et non lexicalement)."""
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def _repo_slug() -> str:
    """'owner/repo' déduit du remote, surchargeable par WPL_UPDATE_REPO."""
    override = os.environ.get('WPL_UPDATE_REPO')
    if override:
        return override.strip()

    ok, url = _run(['git', 'remote', 'get-url', 'origin'], timeout=15)
    if not ok or not url:
        return ''
    m = re.search(r'github\.com[:/]+([^/]+/[^/\s]+?)(?:\.git)?$', url.strip())
    return m.group(1) if m else ''


def _github_latest_tag(slug: str):
    """Dernière release publiée ; repli sur le tag le plus récent."""
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'wp-launcher-updater',
    }
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'

    def _get(url):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))

    try:
        data = _get(f'https://api.github.com/repos/{slug}/releases/latest')
        return data.get('tag_name'), data.get('html_url'), data.get('published_at')
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        # Aucune release publiée : on retombe sur les tags.
        tags = _get(f'https://api.github.com/repos/{slug}/tags?per_page=100')
        versions = [t.get('name') for t in tags if parse_version(t.get('name'))]
        if not versions:
            return None, None, None
        best = max(versions, key=parse_version)
        return best, f'https://github.com/{slug}/releases/tag/{best}', None


def check_for_update(force: bool = False) -> dict:
    """État de mise à jour, mis en cache pour ménager le quota GitHub."""
    with _lock:
        fresh = (time.time() - _cache['fetched_at']) < _CACHE_TTL_SECONDS
        if _cache['payload'] and fresh and not force:
            return _cache['payload']

    current = _current_version()
    result = {
        'current_version': f'v{current}',
        'latest_version': None,
        'update_available': False,
        'release_url': None,
        'published_at': None,
        'error': None,
    }

    slug = _repo_slug()
    if not slug:
        result['error'] = "dépôt GitHub non déterminé (remote 'origin' absent ou non GitHub)"
        return result

    try:
        tag, url, published = _github_latest_tag(slug)
        result['latest_version'] = tag
        result['release_url'] = url
        result['published_at'] = published
        result['update_available'] = bool(tag) and is_newer(tag, current)
    except urllib.error.HTTPError as exc:
        result['error'] = f'GitHub a répondu {exc.code}'
    except Exception as exc:  # réseau coupé, DNS, JSON invalide…
        result['error'] = str(exc)

    if not result['error']:
        with _lock:
            _cache['fetched_at'] = time.time()
            _cache['payload'] = result
    return result


def preflight() -> dict:
    """Vérifie que la mise à jour peut se faire sans rien perdre."""
    root = _project_root()
    if not os.path.isdir(os.path.join(root, '.git')):
        return {'ok': False, 'reason': "l'installation n'est pas un dépôt Git"}

    ok, _ = _run(['git', 'rev-parse', '--is-inside-work-tree'], timeout=15)
    if not ok:
        return {'ok': False, 'reason': 'dépôt Git illisible'}

    ok, dirty = _run(['git', 'status', '--porcelain'], timeout=30)
    if not ok:
        return {'ok': False, 'reason': 'statut Git indisponible'}
    if dirty:
        count = len(dirty.splitlines())
        return {
            'ok': False,
            'reason': f'{count} fichier(s) modifié(s) localement — '
                      'committez ou annulez ces changements avant de mettre à jour',
            'dirty_files': dirty.splitlines()[:20],
        }
    return {'ok': True}


def _restart_service():
    """Redémarre via le mécanisme commun (cf. app/services/service_control)."""
    time.sleep(1)  # laisser la réponse HTTP partir
    from app.services.service_control import restart_service
    restart_service()


def apply_update(target: str = None) -> dict:
    """
    Avance la copie de travail jusqu'au tag cible puis redémarre.

    Retourne un dict ; le redémarrage est différé pour que la réponse HTTP
    parvienne au navigateur.
    """
    checks = preflight()
    if not checks['ok']:
        return {'success': False, 'error': checks['reason'], 'details': checks.get('dirty_files')}

    info = check_for_update(force=True)
    tag = target or info.get('latest_version')
    if not tag:
        return {'success': False, 'error': info.get('error') or 'aucune release trouvée'}
    current = _current_version()
    if not is_newer(tag, current):
        return {'success': False, 'error': f'déjà à jour (version {current})'}

    ok, before = _run(['git', 'rev-parse', 'HEAD'], timeout=15)
    if not ok:
        return {'success': False, 'error': 'commit courant illisible'}

    ok, out = _run(['git', 'fetch', '--tags', '--prune', 'origin'])
    if not ok:
        return {'success': False, 'error': f'git fetch a échoué : {out}'}

    ok, before_req = _run(['git', 'rev-parse', 'HEAD:requirements.txt'], timeout=15)

    # Avance rapide uniquement : on ne réécrit ni ne force jamais l'historique.
    ok, out = _run(['git', 'merge', '--ff-only', tag])
    if not ok:
        return {
            'success': False,
            'error': f"impossible d'avancer jusqu'à {tag} sans réécriture : {out}",
        }

    # Dépendances : réinstallation seulement si le fichier a bougé.
    ok, after_req = _run(['git', 'rev-parse', 'HEAD:requirements.txt'], timeout=15)
    deps_changed = before_req != after_req
    if deps_changed:
        pip = os.path.join(_project_root(), 'venv', 'bin', 'pip')
        if not os.path.exists(pip):
            pip = sys.executable.replace('python3', 'pip') if sys.executable else 'pip'
        ok, out = _run([pip, 'install', '-r', 'requirements.txt'], timeout=_PIP_TIMEOUT)
        if not ok:
            # Dépendances cassées : on revient au point de départ.
            _run(['git', 'reset', '--hard', before])
            return {
                'success': False,
                'error': f'installation des dépendances échouée, retour à la version précédente : {out[-400:]}',
            }

    wp_logger.log_system_info(f'Mise à jour appliquée : {current} -> {tag}')
    threading.Thread(target=_restart_service, daemon=True).start()

    return {
        'success': True,
        'previous_version': f'v{current}',
        'new_version': tag,
        'dependencies_updated': deps_changed,
        'message': 'Mise à jour appliquée. Le service redémarre…',
    }
