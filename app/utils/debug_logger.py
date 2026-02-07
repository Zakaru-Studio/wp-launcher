#!/usr/bin/env python3
"""
Logger de debug simple pour les opérations sur les projets
"""

import os
import datetime


class SimpleDebugLogger:
    """Logger de debug simple pour les opérations sur les projets"""
    
    def __init__(self, project_name):
        self.project_name = project_name
        self.log_dir = "logs"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Créer les dossiers de logs
        os.makedirs(f"{self.log_dir}/create", exist_ok=True)
        os.makedirs(f"{self.log_dir}/debug", exist_ok=True)
        
        # Fichier de log spécifique au projet
        self.log_file = f"{self.log_dir}/create/{project_name}_{timestamp}.log"
        self.debug_file = f"{self.log_dir}/debug/debug_{timestamp}.log"
    
    def _write_log(self, level, step_name, details=""):
        """Écrire dans le fichier de log"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"[{timestamp}] [{level}] {step_name}"
        if details:
            message += f": {details}"
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        except Exception as e:
            print(f"Erreur écriture log: {e}")
    
    def step(self, step_name, details=""):
        """Étape normale"""
        self._write_log("INFO", step_name, details)
    
    def success(self, step_name, details=""):
        """Succès"""
        self._write_log("SUCCESS", step_name, details)
    
    def error(self, step_name, error, exception=None):
        """Erreur"""
        details = str(error)
        if exception:
            details += f" | Exception: {exception}"
        self._write_log("ERROR", step_name, details)
    
    def warning(self, step_name, warning):
        """Avertissement"""
        self._write_log("WARNING", step_name, warning)
    
    def debug(self, step_name, debug_info):
        """Debug"""
        self._write_log("DEBUG", step_name, debug_info)
    
    def log_file_operation(self, operation, file_path, success, details=""):
        """Log d'opération sur fichier"""
        status = "SUCCESS" if success else "ERROR"
        message = f"{operation}: {file_path}"
        if details:
            message += f" | {details}"
        self._write_log(status, "FILE_OP", message)
    
    def close(self):
        """Fermer le logger"""
        self._write_log("INFO", "LOGGER_CLOSED", "Fin du logging")


def create_debug_logger(project_name):
    """Factory pour créer un logger de debug"""
    return SimpleDebugLogger(project_name) 