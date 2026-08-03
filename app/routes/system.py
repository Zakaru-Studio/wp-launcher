#!/usr/bin/env python3
"""
Routes pour la gestion du système
"""

from flask import Blueprint, jsonify, request
from app.utils.logger import wp_logger
import os
import subprocess
import threading
from app.middleware.auth_middleware import login_required, admin_required

system_bp = Blueprint('system', __name__)


@system_bp.route('/api/system/restart', methods=['POST'])
@admin_required
def restart_app():
    """
    Redémarre l'application via systemd (cf. app/services/service_control).

    Passait auparavant par `scripts/restart_app.sh`, hérité de l'époque
    `python3 run.py` : depuis gunicorn + systemd, son `pkill` ne trouvait
    plus le processus et il relançait un serveur Werkzeug sur un port déjà
    pris. Le redémarrage est désormais mutualisé avec la mise à jour.
    """
    try:
        wp_logger.log_system_info("Redémarrage de l'application demandé")

        from app.services.service_control import restart_service

        def restart():
            import time
            time.sleep(1)  # laisser la réponse HTTP partir avant de couper
            try:
                restart_service()
            except Exception as e:
                wp_logger.logger.error(f"Erreur lors du redémarrage: {e}")

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





@system_bp.route('/api/system/update/check', methods=['GET'])
@admin_required
def check_update():
    """
    État de mise à jour (version courante, dernière release, disponibilité).

    Interrogé à chaque chargement de page : le service met le résultat en
    cache une heure pour ne pas épuiser le quota de l'API GitHub.
    """
    from app.services import update_service
    force = request.args.get('force') == '1'
    return jsonify(update_service.check_for_update(force=force))


@system_bp.route('/api/system/update/apply', methods=['POST'])
@admin_required
def apply_update():
    """Applique la dernière release puis redémarre le service."""
    from app.services import update_service
    payload = request.get_json(silent=True) or {}
    result = update_service.apply_update(target=payload.get('version'))
    return jsonify(result), (200 if result.get('success') else 409)
