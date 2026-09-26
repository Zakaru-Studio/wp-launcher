"""Import / export de la base Postgres d'un projet Payload.

Même contrat côté client que :class:`FastImportService` (MySQL) : l'event
Socket.IO ``import_progress`` de type ``database_import``, donc le modal de
progression du dashboard sert tel quel.

Déroulé d'un import :

1. préparation du fichier (``.sql``, ``.sql.gz``, ``.zip``, ``.dump``) ;
2. détection du format : l'en-tête ``PGDMP`` signe un dump custom
   (``pg_dump -Fc``), à passer à ``pg_restore`` ; sinon c'est du SQL texte ;
3. sauvegarde de la base actuelle (``pg_dump -Fc``) ;
4. arrêt de l'app Payload — l'équivalent du ``.maintenance`` de WordPress,
   et surtout ce qui libère ses connexions ;
5. ``DROP DATABASE … WITH (FORCE)`` puis ``CREATE DATABASE`` ;
6. import (``psql`` en flux, ou ``pg_restore --no-owner --no-acl``) ;
7. redémarrage de l'app, y compris en cas d'échec.

Pas de rechercher-remplacer d'URL : Payload stocke des chemins relatifs et
prend son URL publique dans ``NEXT_PUBLIC_SERVER_URL``.
"""
from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from typing import Any, Dict, Iterator, Optional, Tuple

from app.utils.pg_target import PgTarget, pg_target

log = logging.getLogger(__name__)

#: Extensions acceptées à l'upload pour un projet Payload, en plus de
#: ALLOWED_EXTENSIONS (sql, gz, zip).
DUMP_EXTENSIONS = ('.dump', '.backup')

_PGDMP_MAGIC = b'PGDMP'
_CHUNK = 1024 * 1024
_IMPORT_TIMEOUT = 3600
_BACKUP_KEEP = 5

#: Lignes d'un dump texte qui visent des rôles du serveur d'origine : le
#: rôle cible n'existe pas ici (le propriétaire est l'utilisateur du projet),
#: et ``ON_ERROR_STOP`` ferait échouer tout l'import sur la première.
#: Le cas typique : un dump pris sur la prod en tant que ``postgres``.
#: ``SET transaction_timeout`` n'existe qu'à partir de Postgres 17 : un dump
#: de prod en 17+ l'émet en tête, et le serveur 16 du projet le refuse.
_FOREIGN_ROLE_RE = re.compile(
    rb'^\s*(ALTER\s+.+\s+OWNER\s+TO\s+|GRANT\s+|REVOKE\s+|ALTER\s+DEFAULT\s+PRIVILEGES\s+'
    rb'|SET\s+transaction_timeout\b)',
    re.IGNORECASE,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def quote_ident(name: str) -> str:
    """Identifiant Postgres entre guillemets (les noms de projets ont des tirets)."""
    return '"' + name.replace('"', '""') + '"'


def is_custom_dump(path: str) -> bool:
    try:
        with open(path, 'rb') as fh:
            return fh.read(len(_PGDMP_MAGIC)) == _PGDMP_MAGIC
    except OSError:
        return False


def filter_foreign_roles(lines: Iterator[bytes]) -> Iterator[bytes]:
    """Retire d'un dump texte les instructions liées aux rôles d'origine.

    Ces instructions tiennent sur une ligne dans la sortie de ``pg_dump``.
    """
    for line in lines:
        if _FOREIGN_ROLE_RE.match(line):
            continue
        yield line


def prepare_dump(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Ramène l'upload à un fichier SQL ou dump custom exploitable.

    Retourne (chemin, dossier temporaire à supprimer ou None). Le chemin est
    None si l'archive ne contient rien d'utilisable.
    """
    lower = file_path.lower()
    if lower.endswith('.gz'):
        fd, target = tempfile.mkstemp(suffix='.sql')
        os.close(fd)
        try:
            with gzip.open(file_path, 'rb') as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst, length=_CHUNK)
        except (OSError, EOFError):
            log.exception("gunzip failed for %s", file_path)
            os.remove(target)
            return None, None
        return target, target

    if lower.endswith('.zip'):
        temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(file_path) as zf:
                zf.extractall(temp_dir)
        except (OSError, zipfile.BadZipFile):
            log.exception("unzip failed for %s", file_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None, None
        for root, _, files in os.walk(temp_dir):
            for name in sorted(files):
                if name.lower().endswith(('.sql',) + DUMP_EXTENSIONS):
                    return os.path.join(root, name), temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None

    return file_path, None


class PgImportService:
    """Import / export de la base Postgres d'un projet Payload."""

    def __init__(self, socketio=None):
        self.socketio = socketio

    # ─── progression ──────────────────────────────────────────────────

    def _emit(self, project: str, progress: int, message: str,
              status: str = 'importing') -> None:
        log.info("[pg-import %s] %d%% %s", project, progress, message)
        if self.socketio is None:
            return
        try:
            self.socketio.emit('import_progress', {
                'type': 'database_import', 'project': project,
                'progress': progress, 'message': message, 'status': status,
            })
        except Exception:  # noqa: BLE001
            log.exception("socketio.emit failed for project=%s", project)

    # ─── import ───────────────────────────────────────────────────────

    def import_database(self, project_name: str, file_path: str) -> Dict[str, Any]:
        target = pg_target(project_name)
        self._emit(project_name, 5, 'Préparation du fichier…')
        dump_path, cleanup = prepare_dump(file_path)
        if not dump_path:
            return self._fail(project_name, "Aucun fichier .sql ou .dump exploitable dans l'archive")

        app_stopped = False
        try:
            custom = is_custom_dump(dump_path)
            size = os.path.getsize(dump_path)
            kind = 'dump pg_restore' if custom else 'SQL texte'
            self._emit(project_name, 10, f'Fichier prêt : {kind}, {size / 1_048_576:.1f} Mo')

            if not self._is_ready(target):
                return self._fail(project_name, f'Postgres ne répond pas ({target.container}) — démarrez le projet')

            self._emit(project_name, 15, 'Sauvegarde de la base actuelle…')
            backup = self.backup(project_name, target)
            if backup:
                self._emit(project_name, 25, f'Sauvegarde : {os.path.basename(backup)}')

            self._emit(project_name, 30, "Arrêt de l'app Payload…")
            app_stopped = self._docker('stop', target.app_container)

            self._emit(project_name, 35, 'Recréation de la base…')
            ok, err = self._recreate_database(target)
            if not ok:
                return self._fail(project_name, f'Recréation de la base impossible : {err}')

            self._emit(project_name, 40, 'Import en cours…')
            if custom:
                ok, err = self._restore_custom(project_name, target, dump_path)
            else:
                ok, err = self._import_plain(project_name, target, dump_path, size)
            if not ok:
                hint = f' — sauvegarde : {backup}' if backup else ''
                return self._fail(project_name, f"Échec de l'import : {err}{hint}")

            warning = self._migrations_warning(target)
            message = 'Import terminé' + (f' — {warning}' if warning else '')
            self._emit(project_name, 100, message, status='completed')
            return {'success': True, 'message': message, 'backup': backup}
        finally:
            if app_stopped:
                self._docker('start', target.app_container)
            if cleanup:
                if os.path.isdir(cleanup):
                    shutil.rmtree(cleanup, ignore_errors=True)
                elif os.path.exists(cleanup):
                    os.remove(cleanup)

    def _fail(self, project_name: str, message: str) -> Dict[str, Any]:
        self._emit(project_name, 100, message, status='error')
        return {'success': False, 'message': message}

    @staticmethod
    def _docker(action: str, container: str) -> bool:
        result = subprocess.run(['docker', action, container],
                                capture_output=True, text=True, timeout=120)
        return result.returncode == 0

    @staticmethod
    def _is_ready(target: PgTarget) -> bool:
        result = subprocess.run(
            target.docker_exec('pg_isready', '-U', target.user, '-d', 'postgres'),
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0

    @staticmethod
    def _recreate_database(target: PgTarget) -> Tuple[bool, str]:
        db = quote_ident(target.database)
        owner = quote_ident(target.user)
        for sql in (f'DROP DATABASE IF EXISTS {db} WITH (FORCE)',
                    f'CREATE DATABASE {db} OWNER {owner}'):
            result = subprocess.run(target.psql_cmd('-c', sql, database='postgres'),
                                    capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return False, result.stderr.strip()
        return True, ''

    def _import_plain(self, project_name: str, target: PgTarget, path: str,
                      size: int) -> Tuple[bool, str]:
        proc = subprocess.Popen(target.psql_cmd(interactive=True),
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        assert proc.stdin is not None
        read = 0
        last_emit = 0.0
        try:
            with open(path, 'rb') as fh:
                for line in filter_foreign_roles(fh):
                    proc.stdin.write(line)
                    read += len(line)
                    now = time.monotonic()
                    if now - last_emit > 1 and size:
                        last_emit = now
                        pct = 40 + int(55 * read / size)
                        self._emit(project_name, min(pct, 95),
                                   f'Import : {read / 1_048_576:.0f} / {size / 1_048_576:.0f} Mo')
            proc.stdin.close()
        except BrokenPipeError:
            pass  # psql s'est arrêté sur une erreur : le code retour la porte
        _, stderr = proc.communicate(timeout=_IMPORT_TIMEOUT)
        if proc.returncode != 0:
            return False, stderr.decode('utf-8', errors='replace').strip()[-1000:]
        return True, ''

    def _restore_custom(self, project_name: str, target: PgTarget,
                        path: str) -> Tuple[bool, str]:
        self._emit(project_name, 50, 'pg_restore en cours…')
        with open(path, 'rb') as fh:
            result = subprocess.run(
                target.pg_restore_cmd('--no-owner', '--no-acl', '--exit-on-error'),
                stdin=fh, capture_output=True, timeout=_IMPORT_TIMEOUT,
            )
        if result.returncode != 0:
            return False, result.stderr.decode('utf-8', errors='replace').strip()[-1000:]
        return True, ''

    def _migrations_warning(self, target: PgTarget) -> Optional[str]:
        """Signale un décalage entre les migrations du dump et celles du code.

        En dev, Payload pousse le schéma de lui-même ; mais un dump plus
        récent que le code (ou l'inverse) donne des colonnes manquantes au
        premier affichage de l'admin.
        """
        from app.config.docker_config import DockerConfig
        migrations_dir = os.path.join(DockerConfig.PROJECTS_FOLDER, target.project,
                                      'app', 'src', 'migrations')
        if not os.path.isdir(migrations_dir):
            return None
        in_code = {os.path.splitext(f)[0] for f in os.listdir(migrations_dir)
                   if f.endswith('.ts') and f != 'index.ts'}
        result = subprocess.run(
            target.psql_cmd('-At', '-c', 'SELECT name FROM payload_migrations'),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        in_db = {line.strip() for line in result.stdout.splitlines()
                 if line.strip() and line.strip() != 'dev'}
        missing = sorted(in_code - in_db)
        extra = sorted(in_db - in_code)
        if not missing and not extra:
            return None
        parts = []
        if missing:
            parts.append(f'{len(missing)} migration(s) du code absente(s) du dump')
        if extra:
            parts.append(f'{len(extra)} migration(s) du dump inconnue(s) du code')
        return ', '.join(parts) + ' (lancer « migrate » ou mettre le code à jour)'

    # ─── sauvegarde / export ──────────────────────────────────────────

    def backup(self, project_name: str, target: Optional[PgTarget] = None) -> Optional[str]:
        """``pg_dump -Fc`` vers ``logs/db-backups/<projet>/pre-import_<ts>.dump``."""
        target = target or pg_target(project_name)
        backup_root = os.path.join(_ROOT, 'logs', 'db-backups', project_name)
        os.makedirs(backup_root, exist_ok=True)
        path = os.path.join(backup_root, f"pre-import_{time.strftime('%Y%m%d_%H%M%S')}.dump")
        ok, _ = self.dump(target, path)
        if not ok:
            return None
        self._rotate(backup_root)
        return path

    @staticmethod
    def dump(target: PgTarget, path: str, plain: bool = False) -> Tuple[bool, str]:
        """Écrit la base dans ``path`` : format custom par défaut, SQL texte
        gzippé si ``plain``. Supprime le fichier en cas d'échec."""
        args = ('--no-owner', '--no-acl') + (() if plain else ('-Fc',))
        try:
            proc = subprocess.Popen(target.pg_dump_cmd(*args), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            assert proc.stdout is not None
            opener = gzip.open if plain else open
            with opener(path, 'wb') as out:
                shutil.copyfileobj(proc.stdout, out, length=_CHUNK)
            _, stderr = proc.communicate(timeout=_IMPORT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if os.path.exists(path):
                os.remove(path)
            return False, str(exc)
        if proc.returncode != 0:
            if os.path.exists(path):
                os.remove(path)
            return False, stderr.decode('utf-8', errors='replace').strip()
        return True, ''

    @staticmethod
    def _rotate(backup_root: str) -> None:
        try:
            files = sorted((os.path.join(backup_root, f) for f in os.listdir(backup_root)
                            if f.endswith('.dump')), key=os.path.getmtime)
        except OSError:
            return
        for old in files[:-_BACKUP_KEEP]:
            try:
                os.remove(old)
            except OSError:
                log.warning("backup rotation: failed to remove %s", old)
