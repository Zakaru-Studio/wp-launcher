#!/usr/bin/env python3
"""
Service de monitoring système et Docker
"""

import os
import re
import shutil
import subprocess
import threading
import psutil
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from app.utils.logger import wp_logger

# Sous-dossier et extensions acceptées par type de backup. Toute valeur
# hors de ce mapping est rejetée avant de toucher au filesystem.
_BACKUP_TYPES = {
    'mysql': {'subdir': 'mysql', 'suffixes': ('.sql', '.sql.gz')},
    'mongodb': {'subdir': 'mongodb', 'suffixes': ('.tar.gz',)},
}

# Noms de fichiers générés par backup_databases.sh : <projet>_YYYYMMDD_HHMMSS.<ext>
_BACKUP_FILENAME_RE = re.compile(r'^(?P<project>.+)_(?P<ts>\d{8}_\d{6})\.(sql(\.gz)?|tar\.gz)$')
# Charset strict pour tout nom de fichier reçu de l'API (pas de / ni de ..).
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$')

_DEFAULT_BACKUP_DIR = "/home/dev-server/backups"
_DEFAULT_BACKUP_SCRIPT = "/home/dev-server/Sites/wp-launcher/scripts/backup_databases.sh"


class MonitoringService:
    """Service pour le monitoring des ressources système et Docker"""

    def __init__(self, backup_dir: Optional[str] = None, backup_script: Optional[str] = None):
        self.backup_dir = os.path.abspath(
            backup_dir or os.environ.get('WP_BACKUP_DIR', _DEFAULT_BACKUP_DIR)
        )
        self.backup_script = (
            backup_script or os.environ.get('WP_BACKUP_SCRIPT', _DEFAULT_BACKUP_SCRIPT)
        )
        # Un seul backup à la fois : le lock protège _backup_state et
        # empêche deux exécutions concurrentes du script.
        self._backup_lock = threading.Lock()
        self._backup_state: Dict[str, Any] = {'status': 'idle'}
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques système (CPU, RAM, Disque)"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # RAM
            memory = psutil.virtual_memory()
            memory_total = memory.total / (1024 ** 3)  # GB
            memory_used = memory.used / (1024 ** 3)    # GB
            memory_percent = memory.percent
            
            # Disque
            disk = psutil.disk_usage('/')
            disk_total = disk.total / (1024 ** 3)  # GB
            disk_used = disk.used / (1024 ** 3)    # GB
            disk_percent = disk.percent
            
            # Uptime
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            
            return {
                'success': True,
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count
                },
                'memory': {
                    'total': round(memory_total, 2),
                    'used': round(memory_used, 2),
                    'percent': memory_percent
                },
                'disk': {
                    'total': round(disk_total, 2),
                    'used': round(disk_used, 2),
                    'percent': disk_percent
                },
                'uptime': {
                    'seconds': uptime_seconds,
                    'formatted': self._format_uptime(uptime_seconds)
                }
            }
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération stats système: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_docker_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques Docker par conteneur"""
        try:
            result = subprocess.run([
                'docker', 'stats', '--no-stream', '--format',
                '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return {'success': False, 'error': result.stderr}
            
            containers = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                parts = line.split('|')
                if len(parts) == 6:
                    name, cpu, mem_usage, mem_percent, net_io, block_io = parts
                    
                    # Extraire le nom du projet depuis le nom du conteneur
                    project_name = name.split('_')[0] if '_' in name else name
                    
                    containers.append({
                        'name': name,
                        'project': project_name,
                        'cpu': cpu,
                        'memory_usage': mem_usage,
                        'memory_percent': mem_percent,
                        'network': net_io,
                        'block_io': block_io
                    })
            
            return {
                'success': True,
                'containers': containers,
                'total_containers': len(containers)
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Timeout lors de la récupération des stats Docker'}
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération stats Docker: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_processes(self, limit: int = 20) -> Dict[str, Any]:
        """Récupère la liste des processus système"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
                try:
                    pinfo = proc.info
                    processes.append({
                        'pid': pinfo['pid'],
                        'name': pinfo['name'],
                        'user': pinfo['username'],
                        'cpu': pinfo['cpu_percent'] or 0,
                        'memory': pinfo['memory_percent'] or 0
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Trier par utilisation CPU décroissante
            processes.sort(key=lambda x: x['cpu'], reverse=True)
            
            return {
                'success': True,
                'processes': processes[:limit],
                'total_processes': len(processes)
            }
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération processus: {e}")
            return {'success': False, 'error': str(e)}
    
    def _scan_backup_dir(self, backup_type: str) -> List[Dict[str, Any]]:
        """Liste les fichiers de backup d'un type donné (mysql/mongodb)."""
        spec = _BACKUP_TYPES[backup_type]
        directory = os.path.join(self.backup_dir, spec['subdir'])
        items: List[Dict[str, Any]] = []
        if not os.path.isdir(directory):
            return items
        for filename in os.listdir(directory):
            if not filename.endswith(spec['suffixes']):
                continue
            filepath = os.path.join(directory, filename)
            if not os.path.isfile(filepath):
                continue
            try:
                stat = os.stat(filepath)
            except OSError:
                continue  # supprimé entre listdir et stat
            match = _BACKUP_FILENAME_RE.match(filename)
            items.append({
                'filename': filename,
                'type': backup_type,
                'size': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'created': stat.st_mtime,
                'project': match.group('project') if match else 'unknown',
            })
        items.sort(key=lambda x: x['created'], reverse=True)
        return items

    def _storage_stats(self, backups: Dict[str, List[dict]]) -> Dict[str, Any]:
        """Occupation réelle des backups + capacité du disque hôte."""
        per_type = {
            btype: round(sum(b['size'] for b in items) / (1024 * 1024), 2)
            for btype, items in backups.items()
        }
        stats: Dict[str, Any] = {'per_type_mb': per_type,
                                 'total_mb': round(sum(per_type.values()), 2)}
        try:
            usage = shutil.disk_usage(self.backup_dir)
            stats['disk_total_gb'] = round(usage.total / (1024 ** 3), 1)
            stats['disk_free_gb'] = round(usage.free / (1024 ** 3), 1)
        except OSError:
            pass
        return stats

    def list_backups(self) -> Dict[str, Any]:
        """Liste tous les backups disponibles"""
        try:
            backups = {btype: self._scan_backup_dir(btype) for btype in _BACKUP_TYPES}
            return {
                'success': True,
                'backups': backups,
                'total_mysql': len(backups['mysql']),
                'total_mongodb': len(backups['mongodb']),
                'storage': self._storage_stats(backups),
                'last_run': self.get_backup_run_status(),
            }
        except Exception as e:
            wp_logger.log_system_info(f"Erreur liste backups: {e}")
            return {'success': False, 'error': str(e)}

    # ─── exécution (asynchrone) ──────────────────────────────────────

    def get_backup_run_status(self) -> Dict[str, Any]:
        """État du dernier (ou du courant) run de backup."""
        with self._backup_lock:
            return dict(self._backup_state)

    def run_backup_async(self, backup_type: str = 'all') -> Dict[str, Any]:
        """Lance un backup en arrière-plan.

        Retourne {'started': True} ou {'started': False, 'error': ...}.
        Un seul backup à la fois : si un run est en cours, on refuse au
        lieu d'empiler des mysqldump concurrents.
        """
        if backup_type not in ('all', 'mysql', 'mongodb'):
            return {'started': False, 'error': f'Type de backup invalide: {backup_type}'}
        if not os.path.exists(self.backup_script):
            return {'started': False, 'error': 'Script de backup non trouvé'}

        with self._backup_lock:
            if self._backup_state.get('status') == 'running':
                return {'started': False, 'error': 'Un backup est déjà en cours',
                        'already_running': True}
            self._backup_state = {
                'status': 'running',
                'type': backup_type,
                'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            }

        thread = threading.Thread(
            target=self._run_backup_worker,
            args=(backup_type,),
            daemon=True,
            name=f'backup-{backup_type}',
        )
        thread.start()
        return {'started': True, 'type': backup_type}

    def _run_backup_worker(self, backup_type: str) -> None:
        result = self.run_backup(backup_type)
        finished = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self._backup_lock:
            self._backup_state.update({
                'status': 'success' if result.get('success') else 'failed',
                'finished_at': finished,
                'error': result.get('error'),
            })

    def run_backup(self, backup_type: str = 'all') -> Dict[str, Any]:
        """Exécute le script de backup (bloquant — préférer run_backup_async)."""
        try:
            if not os.path.exists(self.backup_script):
                return {'success': False, 'error': 'Script de backup non trouvé'}

            # Choisir la commande selon le type
            if backup_type == 'mysql':
                cmd = [self.backup_script, 'mysql-only']
            elif backup_type == 'mongodb':
                cmd = [self.backup_script, 'mongodb-only']
            else:
                cmd = [self.backup_script]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes max
            )

            if result.returncode == 0:
                wp_logger.log_system_info(f"Backup {backup_type} exécuté avec succès")
                return {
                    'success': True,
                    'message': 'Backup exécuté avec succès',
                    'output': result.stdout
                }
            else:
                return {
                    'success': False,
                    'error': result.stderr or 'Erreur lors du backup'
                }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Timeout lors du backup (> 10 minutes)'}
        except Exception as e:
            wp_logger.log_system_info(f"Erreur exécution backup: {e}")
            return {'success': False, 'error': str(e)}

    # ─── résolution sûre d'un fichier de backup ──────────────────────

    def resolve_backup_file(self, backup_type: str, filename: str) -> Optional[str]:
        """Chemin absolu d'un backup, ou None si le couple (type, nom)
        est invalide ou sort du dossier de backups.

        Toute la validation anti-traversal vit ici : type whitelisté,
        charset strict (pas de /, pas de ..), extension attendue, et
        confinement vérifié sur le chemin résolu (realpath).
        """
        spec = _BACKUP_TYPES.get(backup_type)
        if spec is None:
            return None
        if not filename or not _SAFE_FILENAME_RE.match(filename):
            return None
        if os.path.basename(filename) != filename:
            return None
        if not filename.endswith(spec['suffixes']):
            return None
        directory = os.path.realpath(os.path.join(self.backup_dir, spec['subdir']))
        candidate = os.path.realpath(os.path.join(directory, filename))
        if os.path.dirname(candidate) != directory:
            return None
        return candidate

    def delete_backup(self, backup_type: str, filename: str) -> Dict[str, Any]:
        """Supprime un backup identifié par (type, nom de fichier)."""
        try:
            backup_path = self.resolve_backup_file(backup_type, filename)
            if backup_path is None:
                return {'success': False, 'error': 'Nom ou type de backup invalide'}

            if not os.path.isfile(backup_path):
                return {'success': False, 'error': 'Backup non trouvé'}

            os.remove(backup_path)
            wp_logger.log_system_info(f"Backup supprimé: {backup_path}")

            return {
                'success': True,
                'message': 'Backup supprimé avec succès'
            }
        except Exception as e:
            wp_logger.log_system_info(f"Erreur suppression backup: {e}")
            return {'success': False, 'error': str(e)}
    
    def _format_uptime(self, seconds: float) -> str:
        """Formate l'uptime en format lisible"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}j {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

