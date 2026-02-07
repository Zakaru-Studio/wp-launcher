#!/usr/bin/env python3
"""
Routes pour la gestion du système
"""

from flask import Blueprint, jsonify
from app.utils.logger import wp_logger
import os
import subprocess
import threading

system_bp = Blueprint('system', __name__)


@system_bp.route('/api/system/restart', methods=['POST'])
def restart_app():
    """Redémarre l'application en utilisant le script restart_app.sh"""
    try:
        wp_logger.log_system_info("Redémarrage de l'application demandé")
        
        # Chemin vers le script de redémarrage
        # Le script est dans scripts/ à la racine du projet
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts', 'restart_app.sh')
        
        if not os.path.exists(script_path):
            error_msg = f"Script de redémarrage non trouvé: {script_path}"
            wp_logger.logger.error(error_msg)
            return jsonify({
                'success': False,
                'message': 'Script de redémarrage non trouvé'
            }), 404
        
        def restart():
            import time
            time.sleep(1)  # Laisser le temps de répondre à la requête
            wp_logger.log_system_info("Lancement du script de redémarrage...")
            
            try:
                # Rendre le script exécutable
                os.chmod(script_path, 0o755)
                
                # Lancer le script de redémarrage en arrière-plan
                subprocess.Popen(
                    ['bash', script_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                wp_logger.log_system_info("Script de redémarrage lancé avec succès")
            except Exception as e:
                wp_logger.logger.error(f"Erreur lors du lancement du script: {e}")
        
        # Lancer le redémarrage dans un thread séparé
        threading.Thread(target=restart, daemon=True).start()
        
        return jsonify({
            'success': True,
            'message': 'Redémarrage en cours... La page se rechargera automatiquement.'
        })
    except Exception as e:
        wp_logger.logger.error(f"Erreur redémarrage: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



