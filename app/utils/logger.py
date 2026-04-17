import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
import json
import traceback
from logging.handlers import RotatingFileHandler


class WPLauncherLogger:
    """Logger spécialisé pour les opérations WordPress Launcher"""
    
    def __init__(self, logs_dir="logs"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(exist_ok=True)
        
        # Créer des sous-dossiers pour chaque type d'opération
        self.operation_dirs = {
            'create': self.logs_dir / 'create',
            'delete': self.logs_dir / 'delete', 
            'start': self.logs_dir / 'start',
            'stop': self.logs_dir / 'stop',
            'general': self.logs_dir / 'general',
            'docker': self.logs_dir / 'docker',
            'database': self.logs_dir / 'database'
        }
        
        for dir_path in self.operation_dirs.values():
            dir_path.mkdir(exist_ok=True)
        
        # Configuration du logger principal
        self.logger = logging.getLogger('wp_launcher')
        self.logger.setLevel(logging.INFO)
        
        # Éviter les doublons de handlers
        if not self.logger.handlers:
            self._setup_handlers()
    
    def _setup_handlers(self):
        """Configure les handlers de logging"""
        
        # Handler avec rotation pour les logs généraux
        # Rotation : 10 000 lignes ~= 1 MB par fichier (estimation), on garde 7 fichiers backup
        general_handler = RotatingFileHandler(
            self.logs_dir / 'wp_launcher.log',
            maxBytes=1024*1024,  # 1 MB
            backupCount=7,
            encoding='utf-8'
        )
        general_handler.setLevel(logging.INFO)
        
        # Format détaillé avec timestamp
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        general_handler.setFormatter(formatter)
        
        self.logger.addHandler(general_handler)
    
    def _get_operation_log_file(self, operation_type):
        """Génère le nom de fichier pour une opération donnée"""
        today = datetime.now().strftime('%Y-%m-%d')
        operation_dir = self.operation_dirs.get(operation_type, self.operation_dirs['general'])
        return operation_dir / f'{operation_type}_{today}.log'
    
    def _log_to_operation_file(self, operation_type, message):
        """Log un message dans le fichier spécifique à l'opération"""
        log_file = self._get_operation_log_file(operation_type)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # S'assurer que le dossier parent existe
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} | {message}\n")
    
    def log_operation_start(self, operation_type, project_name, **kwargs):
        """Log le début d'une opération"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        message = f"START | {operation_type.upper()} | Project: {project_name}"
        if extra_info:
            message += f" | {extra_info}"
        
        self.logger.info(message)
        self._log_to_operation_file(operation_type, message)
    
    def log_operation_success(self, operation_type, project_name, message="", **kwargs):
        """Log le succès d'une opération"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        log_message = f"SUCCESS | {operation_type.upper()} | Project: {project_name}"
        if message:
            log_message += f" | {message}"
        if extra_info:
            log_message += f" | {extra_info}"
        
        self.logger.info(log_message)
        self._log_to_operation_file(operation_type, log_message)
    
    def log_operation_error(self, operation_type, project_name, error, context="", **kwargs):
        """Log une erreur d'opération avec contexte détaillé"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        
        # Message principal
        error_message = f"ERROR | {operation_type.upper()} | Project: {project_name} | Error: {str(error)}"
        if context:
            error_message += f" | Context: {context}"
        if extra_info:
            error_message += f" | {extra_info}"
        
        # Log dans le fichier principal
        self.logger.error(error_message)
        
        # Log détaillé dans le fichier d'opération
        detailed_message = f"{error_message}\n"
        
        # Ajouter la stack trace si disponible
        if hasattr(error, '__traceback__') and error.__traceback__:
            detailed_message += f"Traceback:\n{''.join(traceback.format_tb(error.__traceback__))}"
        
        self._log_to_operation_file(operation_type, detailed_message)
        
        # Log supplémentaire dans le fichier d'erreurs du jour
        error_log_file = self.logs_dir / f"errors_{datetime.now().strftime('%Y-%m-%d')}.log"
        with open(error_log_file, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {detailed_message}\n")
    
    def log_docker_operation(self, operation, project_name, success, output="", error="", **kwargs):
        """Log spécialisé pour les opérations Docker"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        
        status = "SUCCESS" if success else "ERROR"
        message = f"{status} | DOCKER {operation.upper()} | Project: {project_name}"
        
        if extra_info:
            message += f" | {extra_info}"
        
        if output:
            message += f"\nOutput: {output}"
        
        if error:
            message += f"\nError: {error}"
        
        if success:
            self.logger.info(message)
        else:
            self.logger.error(message)
        
        self._log_to_operation_file('docker', message)
    
    def log_database_operation(self, operation, project_name, success, details="", **kwargs):
        """Log spécialisé pour les opérations de base de données"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        
        status = "SUCCESS" if success else "ERROR"
        message = f"{status} | DATABASE {operation.upper()} | Project: {project_name}"
        
        if details:
            message += f" | {details}"
        
        if extra_info:
            message += f" | {extra_info}"
        
        if success:
            self.logger.info(message)
        else:
            self.logger.error(message)
        
        self._log_to_operation_file('database', message)
    
    def log_system_info(self, message, **kwargs):
        """Log d'informations système générales"""
        extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
        log_message = f"SYSTEM | {message}"
        if extra_info:
            log_message += f" | {extra_info}"
        
        self.logger.info(log_message)
        self._log_to_operation_file('general', log_message)
    
    def get_recent_logs(self, operation_type=None, days=7):
        """Récupère les logs récents pour une opération donnée"""
        logs = []
        
        if operation_type and operation_type in self.operation_dirs:
            log_dir = self.operation_dirs[operation_type]
        else:
            log_dir = self.logs_dir
        
        # Parcourir les fichiers de log des derniers jours
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            
            if operation_type:
                log_file = log_dir / f'{operation_type}_{date}.log'
            else:
                log_file = self.logs_dir / f'wp_launcher_{date}.log'
            
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            logs.append({
                                'date': date,
                                'operation': operation_type or 'general',
                                'content': content
                            })
                except Exception as e:
                    continue
        
        return logs
    
    def cleanup_old_logs(self, days_to_keep=7):
        """Nettoie les logs anciens (par défaut 7 jours)"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_timestamp = cutoff_date.timestamp()
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        
        cleaned_files = []
        
        # Nettoyer tous les dossiers de logs
        for operation_type, log_dir in self.operation_dirs.items():
            for log_file in log_dir.glob('*.log*'):
                try:
                    # Vérifier la date de modification du fichier
                    if log_file.stat().st_mtime < cutoff_timestamp:
                        log_file.unlink()
                        cleaned_files.append(str(log_file))
                except Exception as e:
                    continue
        
        # Nettoyer les logs généraux et app.log
        for log_file in self.logs_dir.glob('*.log*'):
            if log_file.parent == self.logs_dir:  # Fichiers dans le dossier racine
                try:
                    # Vérifier la date de modification du fichier
                    if log_file.stat().st_mtime < cutoff_timestamp:
                        # Garder le fichier principal app.log
                        if log_file.name == 'app.log':
                            continue
                        log_file.unlink()
                        cleaned_files.append(str(log_file))
                except Exception as e:
                    continue
        
        if cleaned_files:
            self.log_system_info(f"Nettoyage des logs: {len(cleaned_files)} fichiers supprimés (plus de {days_to_keep} jours)")
        
        return cleaned_files


# Instance globale du logger
wp_logger = WPLauncherLogger()


class OperationLogger:
    """
    Logger léger orienté "opération/projet" qui délègue vers ``WPLauncherLogger``
    pour la sortie centralisée (``logs/wp_launcher.log`` + fichier par opération),
    tout en conservant un fichier dédié par projet et par timestamp
    (ex: ``logs/create/<project>_<YYYYmmdd_HHMMSS>.log``) pour préserver la
    compatibilité avec les appels historiques de ``SimpleDebugLogger``.

    API publique attendue par les callers existants :
        - step(name, details="")
        - success(name, details="")
        - error(name, error, exception=None)
        - warning(name, warning)
        - info(msg)
        - debug(name, debug_info)
        - log_file_operation(operation, file_path, success, details="")
        - close()
    """

    def __init__(self, operation_name, project_name=None, wp_logger_instance=None):
        # operation_name = 'create', 'delete', 'start', etc. (utilisé comme
        # dossier + préfixe de log). Si inconnu, on retombe sur 'general'.
        self.operation_name = operation_name or 'general'
        self.project_name = project_name or 'unknown'
        self._wp = wp_logger_instance if wp_logger_instance is not None else wp_logger

        # Déterminer le dossier de log pour cette opération (fallback: general)
        op_dir = self._wp.operation_dirs.get(
            self.operation_name, self._wp.operation_dirs['general']
        )
        op_dir.mkdir(parents=True, exist_ok=True)

        # Fichier dédié : <op_dir>/<project>_<timestamp>.log
        # (identique au schéma historique de SimpleDebugLogger pour l'op 'create')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = op_dir / f"{self.project_name}_{timestamp}.log"

    # --- helpers internes -----------------------------------------------------

    def _write(self, level, step_name, details=""):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"[{ts}] [{level}] {step_name}"
        if details:
            message += f": {details}"
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        except Exception as e:
            # On évite de planter si le disque est plein / permissions KO ;
            # on laisse quand même la trace via WPLauncherLogger ci-dessous.
            try:
                self._wp.logger.warning(
                    f"OperationLogger write failed ({self.log_file}): {e}"
                )
            except Exception:
                pass

    # --- API publique ---------------------------------------------------------

    def step(self, step_name, details=""):
        self._write("INFO", step_name, details)

    def success(self, step_name, details=""):
        self._write("SUCCESS", step_name, details)

    def error(self, step_name, error=None, exception=None):
        # Accepte: error("STEP", "msg", exc)  (signature legacy SimpleDebugLogger)
        #         error("STEP", "msg")         (sans exception)
        #         error("msg")                 (appel simplifié — "msg" est alors le détail)
        if error is None:
            error_detail = step_name
            step_label = "ERROR"
        else:
            error_detail = str(error)
            step_label = step_name

        details = error_detail
        if exception is not None:
            details += f" | Exception: {exception}"
        self._write("ERROR", step_label, details)

        # Propager aussi vers le logger global
        # (fichier wp_launcher.log + errors_YYYY-MM-DD.log)
        try:
            err_obj = exception if exception is not None else (
                error if isinstance(error, BaseException) else Exception(error_detail)
            )
            self._wp.log_operation_error(
                self.operation_name, self.project_name, err_obj, context=step_label
            )
        except Exception:
            pass

    def warning(self, step_name, warning):
        self._write("WARNING", step_name, warning)

    def info(self, msg):
        self._write("INFO", "INFO", msg)

    def debug(self, step_name, debug_info):
        self._write("DEBUG", step_name, debug_info)

    def log_file_operation(self, operation, file_path, success, details=""):
        status = "SUCCESS" if success else "ERROR"
        message = f"{operation}: {file_path}"
        if details:
            message += f" | {details}"
        self._write(status, "FILE_OP", message)

    def close(self):
        self._write("INFO", "LOGGER_CLOSED", "Fin du logging")


def get_operation_logger(operation_name, project_name=None):
    """
    Factory recommandée pour obtenir un logger orienté opération/projet.

    Remplace l'ancienne ``debug_logger.create_debug_logger(project_name)``
    tout en permettant de cibler un dossier d'opération (``create``, ``delete``,
    ``start``...). Par défaut, l'opération est ``create`` (comportement legacy).
    """
    return OperationLogger(operation_name=operation_name, project_name=project_name)
