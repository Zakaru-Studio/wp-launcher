#!/usr/bin/env python3
"""
Service de monitoring système et Docker
"""

import os
import subprocess
import psutil
import time
from typing import Dict, List, Any
from app.utils.logger import wp_logger


class MonitoringService:
    """Service pour le monitoring des ressources système et Docker"""
    
    def __init__(self):
        self.backup_dir = "/home/dev-server/backups"
        self.backup_script = "/home/dev-server/Sites/wp-launcher/scripts/backup_databases.sh"
    
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
    
    def list_backups(self) -> Dict[str, Any]:
        """Liste tous les backups disponibles"""
        try:
            backups = {
                'mysql': [],
                'mongodb': []
            }
            
            # Liste les backups MySQL
            mysql_dir = os.path.join(self.backup_dir, 'mysql')
            if os.path.exists(mysql_dir):
                for filename in os.listdir(mysql_dir):
                    if filename.endswith('.sql') or filename.endswith('.sql.gz'):
                        filepath = os.path.join(mysql_dir, filename)
                        stat = os.stat(filepath)
                        
                        backups['mysql'].append({
                            'filename': filename,
                            'path': filepath,
                            'size': stat.st_size,
                            'size_mb': round(stat.st_size / (1024 * 1024), 2),
                            'created': stat.st_mtime,
                            'project': filename.split('_')[0] if '_' in filename else 'unknown'
                        })
            
            # Liste les backups MongoDB
            mongodb_dir = os.path.join(self.backup_dir, 'mongodb')
            if os.path.exists(mongodb_dir):
                for filename in os.listdir(mongodb_dir):
                    if filename.endswith('.tar.gz'):
                        filepath = os.path.join(mongodb_dir, filename)
                        stat = os.stat(filepath)
                        
                        backups['mongodb'].append({
                            'filename': filename,
                            'path': filepath,
                            'size': stat.st_size,
                            'size_mb': round(stat.st_size / (1024 * 1024), 2),
                            'created': stat.st_mtime,
                            'project': filename.split('_')[0] if '_' in filename else 'unknown'
                        })
            
            # Trier par date de création décroissante
            backups['mysql'].sort(key=lambda x: x['created'], reverse=True)
            backups['mongodb'].sort(key=lambda x: x['created'], reverse=True)
            
            return {
                'success': True,
                'backups': backups,
                'total_mysql': len(backups['mysql']),
                'total_mongodb': len(backups['mongodb'])
            }
        except Exception as e:
            wp_logger.log_system_info(f"Erreur liste backups: {e}")
            return {'success': False, 'error': str(e)}
    
    def run_backup(self, backup_type: str = 'all') -> Dict[str, Any]:
        """Lance un backup manuel"""
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
    
    def delete_backup(self, backup_path: str) -> Dict[str, Any]:
        """Supprime un backup"""
        try:
            # Vérifier que le chemin est dans le dossier de backups
            if not backup_path.startswith(self.backup_dir):
                return {'success': False, 'error': 'Chemin de backup invalide'}
            
            if not os.path.exists(backup_path):
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

