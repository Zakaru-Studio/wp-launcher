"""Projets Payload CMS : scaffold du code, .env, premier admin, commandes npm.

Un projet Payload vit dans ``projets/<projet>/app`` (le code généré par
``create-payload-app``) et tourne dans ``<projet>_payload_1`` (next dev),
à côté de ``<projet>_postgres_1``, d'Adminer et de Mailpit — voir
``docker-template/docker-compose-payload.yml``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from app.config.docker_config import DockerConfig

log = logging.getLogger(__name__)

#: Sous-dossier de projets/<projet> qui porte le code Payload.
APP_DIR = 'app'

#: Commandes npm lançables depuis le dashboard, par nom affiché → argv.
#: Liste blanche stricte : rien de ce que le client envoie n'est interpolé.
ALLOWED_COMMANDS: Dict[str, List[str]] = {
    'install': ['npm', 'install', '--no-audit', '--no-fund'],
    'generate:types': ['npm', 'run', 'generate:types'],
    'generate:importmap': ['npm', 'run', 'generate:importmap'],
    'migrate': ['npm', 'run', 'payload', '--', 'migrate'],
    'migrate:status': ['npm', 'run', 'payload', '--', 'migrate:status'],
    'migrate:create': ['npm', 'run', 'payload', '--', 'migrate:create'],
}

_SCAFFOLD_TIMEOUT = 600
_COMMAND_TIMEOUT = 600

#: Variables que le launcher gère dans app/.env. Le compose les fournit déjà
#: au conteneur (et l'environnement l'emporte sur .env pour Next), mais un
#: .env cohérent évite les surprises quand on lance une commande à la main.
_MANAGED_ENV_KEYS = ('DATABASE_URL', 'DATABASE_URI', 'PAYLOAD_SECRET', 'NEXT_PUBLIC_SERVER_URL')

#: Valeurs d'exemple laissées par le template « website ».
_PLACEHOLDER_SECRET_RE = re.compile(r'^(CRON_SECRET|PREVIEW_SECRET)=YOUR_\w+$', re.MULTILINE)


def app_path(project_name: str, projects_folder: Optional[str] = None) -> str:
    return os.path.join(projects_folder or DockerConfig.PROJECTS_FOLDER, project_name, APP_DIR)


def app_container(project_name: str) -> str:
    return f'{project_name}_payload_1'


def public_url(port) -> str:
    return f'http://{DockerConfig.LOCAL_IP}:{port}'


# ─── création ────────────────────────────────────────────────────────────


def scaffold(editable_path: str, template: str, database_uri: str,
             payload_secret: str) -> Tuple[bool, str]:
    """Génère ``<editable_path>/app`` avec create-payload-app.

    Tourne dans un conteneur jetable sous l'uid de l'hôte : les fichiers
    générés lui appartiennent, pas à root. ``--no-deps`` : l'installation se
    fait au premier démarrage du conteneur de l'app, dans son volume
    node_modules. Retourne (succès, sortie ou message d'erreur).
    """
    if template not in DockerConfig.PAYLOAD_TEMPLATES:
        return False, f'Template Payload inconnu: {template}'

    cmd = [
        'docker', 'run', '--rm',
        '--user', f'{os.getuid()}:{os.getgid()}',
        '-e', 'HOME=/tmp', '-e', 'npm_config_cache=/tmp/.npm', '-e', 'CI=true',
        '-v', f'{editable_path}:/work', '-w', '/work',
        DockerConfig.PAYLOAD_NODE_IMAGE,
        'npx', '-y', f'create-payload-app@{DockerConfig.PAYLOAD_CLI_VERSION}',
        '-n', APP_DIR, '-t', template,
        '--db', 'postgres', '--db-connection-string', database_uri,
        '--secret', payload_secret,
        '--no-deps', '--no-git', '--no-agent', '--use-npm',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_SCAFFOLD_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f'create-payload-app a dépassé {_SCAFFOLD_TIMEOUT} s'
    except OSError as exc:
        return False, f'Impossible de lancer docker: {exc}'

    output = _strip_ansi(result.stdout + result.stderr)
    config = os.path.join(editable_path, APP_DIR, 'src', 'payload.config.ts')
    if result.returncode != 0 or not os.path.isfile(config):
        return False, output[-2000:] or f'create-payload-app a échoué (code {result.returncode})'
    return True, output


def write_env(project_name: str, database_uri: str, payload_secret: str, port,
              projects_folder: Optional[str] = None) -> str:
    """Aligne ``app/.env`` sur le compose, sans toucher aux autres clés."""
    path = os.path.join(app_path(project_name, projects_folder), '.env')
    try:
        with open(path) as fh:
            content = fh.read()
    except FileNotFoundError:
        content = ''

    values = {
        'DATABASE_URL': database_uri,
        'DATABASE_URI': database_uri,
        'PAYLOAD_SECRET': payload_secret,
        'NEXT_PUBLIC_SERVER_URL': public_url(port),
    }
    for key in _MANAGED_ENV_KEYS:
        line = f'{key}={values[key]}'
        pattern = re.compile(rf'^{key}=.*$', re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(lambda _m: line, content, count=1)
        else:
            content = content.rstrip('\n') + ('\n' if content else '') + line + '\n'

    content = _PLACEHOLDER_SECRET_RE.sub(
        lambda m: f'{m.group(1)}={secrets.token_hex(16)}', content)

    with open(path, 'w') as fh:
        fh.write(content)
    return path


#: Blocs insérés dans le code généré. Les valeurs viennent de l'environnement
#: du conteneur (compose), jamais du fichier : rien de sensible n'est commité.
_NEXT_CONFIG_ANCHOR = 'const nextConfig: NextConfig = {'
_NEXT_CONFIG_PATCH = """
  // wp-launcher : le site est ouvert via l'IP du serveur, pas localhost. Sans
  // ça, next dev refuse de servir ses scripts à cette origine → page blanche.
  allowedDevOrigins: (process.env.WPL_DEV_ORIGINS || '').split(',').filter(Boolean),"""

_PAYLOAD_CONFIG_ANCHOR = 'export default buildConfig({'
_PAYLOAD_COOKIE_PATCH = """
  // wp-launcher : un préfixe par projet. Les cookies ignorent le port, donc
  // tous les projets de http://<ip>:<port> partageraient `payload-token`.
  cookiePrefix: process.env.WPL_COOKIE_PREFIX || 'payload',"""
_PAYLOAD_ADMIN_ANCHOR = '  admin: {'
_PAYLOAD_AUTOLOGIN_PATCH = """
    // wp-launcher : connexion automatique avec l'admin créé à l'installation,
    // en dev uniquement (variables absentes du build de prod).
    autoLogin:
      process.env.NODE_ENV === 'development' && process.env.WPL_AUTOLOGIN_EMAIL
        ? { email: process.env.WPL_AUTOLOGIN_EMAIL, prefillOnly: false }
        : false,"""


def _insert_after(text: str, anchor: str, block: str, marker: str,
                  after: str = '') -> Tuple[str, bool]:
    """Insère ``block`` juste après ``anchor`` (cherchée après ``after``),
    sauf si ``marker`` est déjà là."""
    if marker in text:
        return text, True
    index = text.find(anchor, max(text.find(after), 0) if after else 0)
    if index < 0:
        return text, False
    end = index + len(anchor)
    return text[:end] + block + text[end:], True


def patch_app_config(project_name: str, projects_folder: Optional[str] = None) -> List[str]:
    """Adapte le code généré par create-payload-app au launcher.

    Idempotent. Retourne la liste des patchs qui n'ont pas pu être posés
    (ancre introuvable : template modifié en amont).
    """
    root = app_path(project_name, projects_folder)
    failures = []
    targets = (
        ('next.config.ts', ((_NEXT_CONFIG_ANCHOR, _NEXT_CONFIG_PATCH, 'allowedDevOrigins', ''),)),
        (os.path.join('src', 'payload.config.ts'), (
            (_PAYLOAD_CONFIG_ANCHOR, _PAYLOAD_COOKIE_PATCH, 'cookiePrefix', ''),
            (_PAYLOAD_ADMIN_ANCHOR, _PAYLOAD_AUTOLOGIN_PATCH, 'autoLogin', _PAYLOAD_CONFIG_ANCHOR),
        )),
    )
    for relative, patches in targets:
        path = os.path.join(root, relative)
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            failures.append(relative)
            continue
        for anchor, block, marker, after in patches:
            text, ok = _insert_after(text, anchor, block, marker, after)
            if not ok:
                failures.append(f'{relative} ({marker})')
        with open(path, 'w') as fh:
            fh.write(text)
    return failures


def register_first_user(port, email: str, password: str,
                        timeout: int = 600) -> Tuple[bool, str]:
    """Crée le premier admin dès que l'app répond.

    Au premier démarrage, le conteneur installe les dépendances puis compile
    /admin : compter plusieurs minutes. ``/api/users/first-register`` ne
    marche que tant qu'aucun utilisateur n'existe ; sinon Payload répond 403
    et on considère que c'est déjà fait. Suppose la collection d'auth
    ``users`` des templates officiels.
    """
    from app.utils.security_config import site_bind_address
    bind = site_bind_address()
    host = '127.0.0.1' if bind in ('0.0.0.0', '::') else bind
    base = f'http://{host}:{port}'
    deadline = time.monotonic() + timeout
    last_error = ''
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f'{base}/api/users/me', timeout=30):
                break
        except urllib.error.HTTPError:
            break  # l'API répond (même en erreur) : l'app est prête
        except (urllib.error.URLError, OSError) as exc:
            last_error = str(exc)
            time.sleep(5)
    else:
        return False, f"l'app ne répond pas après {timeout} s ({last_error})"

    body = json.dumps({'email': email, 'password': password}).encode()
    request = urllib.request.Request(
        f'{base}/api/users/first-register', data=body, method='POST',
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=120):
            return True, f'Admin Payload créé : {email}'
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return True, 'Un utilisateur existe déjà'
        return False, f'first-register a répondu {exc.code}'
    except (urllib.error.URLError, OSError) as exc:
        return False, f'first-register injoignable: {exc}'


def remove_app(editable_path: str) -> None:
    """Nettoie un scaffold raté pour qu'une nouvelle tentative reparte à zéro."""
    shutil.rmtree(os.path.join(editable_path, APP_DIR), ignore_errors=True)


# ─── exploitation ────────────────────────────────────────────────────────


def run_command(project_name: str, command: str) -> Tuple[bool, str]:
    """Lance une commande npm de la liste blanche dans le conteneur de l'app.

    Sous l'uid de l'hôte, comme le serveur de dev : les types générés et les
    migrations créées lui appartiennent.
    """
    argv = ALLOWED_COMMANDS.get(command)
    if argv is None:
        return False, f'Commande non autorisée: {command}'

    cmd = ['docker', 'exec', '-u', f'{os.getuid()}:{os.getgid()}',
           '-e', 'HOME=/home/app', '-w', '/app', app_container(project_name), *argv]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_COMMAND_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f'La commande a dépassé {_COMMAND_TIMEOUT} s'
    except OSError as exc:
        return False, str(exc)
    output = _strip_ansi(result.stdout + result.stderr).strip()
    return result.returncode == 0, output


_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text or '')
