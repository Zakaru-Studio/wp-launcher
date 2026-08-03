#!/usr/bin/env python3
"""
Routes pour le monitoring système et la gestion des backups
"""

import os

from flask import Blueprint, render_template, jsonify, request, current_app, send_file
from app.utils.logger import wp_logger
from app.middleware.auth_middleware import login_required, admin_required

monitoring_bp = Blueprint('monitoring', __name__)


@monitoring_bp.route('/monitoring')
@login_required
def monitoring_page():
    """Page principale du monitoring"""
    return render_template('monitoring.html')


@monitoring_bp.route('/backups')
@login_required
def backups_page():
    """Page de gestion des backups"""
    return render_template('backups.html')


@monitoring_bp.route('/api/monitoring/system', methods=['GET'])
@login_required
def get_system_stats():
    """Récupère les statistiques système"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        stats = monitoring_service.get_system_stats()
        return jsonify(stats)
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API system stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/monitoring/docker', methods=['GET'])
@login_required
def get_docker_stats():
    """Récupère les statistiques Docker"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        stats = monitoring_service.get_docker_stats()
        return jsonify(stats)
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API docker stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/monitoring/processes', methods=['GET'])
@login_required
def get_processes():
    """Récupère la liste des processus"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        limit = request.args.get('limit', 20, type=int)
        processes = monitoring_service.get_processes(limit=limit)
        return jsonify(processes)
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API processes: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/monitoring/kill-process', methods=['POST'])
@admin_required
def kill_process():
    """Termine un processus"""
    try:
        data = request.get_json()
        pid = data.get('pid')
        
        if not pid:
            return jsonify({'success': False, 'error': 'PID manquant'}), 400

        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'PID invalide'}), 400

        import psutil
        import signal

        monitoring_service = current_app.extensions['monitoring']

        # N'autoriser que les processus réellement administrés par le
        # launcher. Sans cette garde, une session admin pouvait envoyer un
        # SIGTERM à n'importe quel PID de la machine — sshd, le pare-feu,
        # l'application d'un autre locataire.
        if not monitoring_service.is_managed_pid(pid):
            wp_logger.log_system_info(
                f"Refus de terminer le PID {pid} : hors périmètre du launcher"
            )
            return jsonify({
                'success': False,
                'error': "Ce processus n'appartient pas à un service géré par WP Launcher"
            }), 403

        try:
            process = psutil.Process(pid)
            process_name = process.name()

            # Envoyer SIGTERM (terminaison gracieuse)
            process.send_signal(signal.SIGTERM)
            
            wp_logger.log_system_info(f"Processus {pid} ({process_name}) terminé")
            
            return jsonify({
                'success': True,
                'message': f'Processus {pid} terminé avec succès'
            })
        except psutil.NoSuchProcess:
            return jsonify({'success': False, 'error': 'Processus introuvable'}), 404
        except psutil.AccessDenied:
            return jsonify({'success': False, 'error': 'Permission refusée'}), 403
            
    except Exception as e:
        wp_logger.log_system_info(f"Erreur kill process: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups', methods=['GET'])
@login_required
def list_backups():
    """Liste tous les backups disponibles"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        backups = monitoring_service.list_backups()
        return jsonify(backups)
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API list backups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups/run', methods=['POST'])
@admin_required
def run_backup():
    """Lance un backup manuel en arrière-plan.

    Retourne 202 immédiatement ; le frontend suit l'avancement via
    GET /api/backups/run/status. 409 si un backup tourne déjà.
    """
    try:
        monitoring_service = current_app.extensions['monitoring']
        data = request.get_json(silent=True) or {}
        backup_type = data.get('type', 'all')  # all, mysql, mongodb

        result = monitoring_service.run_backup_async(backup_type=backup_type)

        if result.get('started'):
            return jsonify({'success': True, 'type': backup_type,
                            'message': 'Backup lancé en arrière-plan'}), 202
        status = 409 if result.get('already_running') else 400
        return jsonify({'success': False, 'error': result.get('error')}), status
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API run backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups/run/status', methods=['GET'])
@login_required
def backup_run_status():
    """État du backup en cours (ou du dernier run)."""
    try:
        monitoring_service = current_app.extensions['monitoring']
        return jsonify({'success': True, 'run': monitoring_service.get_backup_run_status()})
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API backup status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups/<backup_type>/<filename>/download', methods=['GET'])
@admin_required
def download_backup(backup_type, filename):
    """Télécharge un fichier de backup (dump complet de base — admin only)."""
    try:
        monitoring_service = current_app.extensions['monitoring']
        backup_path = monitoring_service.resolve_backup_file(backup_type, filename)
        if backup_path is None:
            return jsonify({'success': False, 'error': 'Nom ou type de backup invalide'}), 400
        if not os.path.isfile(backup_path):
            return jsonify({'success': False, 'error': 'Backup non trouvé'}), 404
        return send_file(backup_path, as_attachment=True, download_name=filename)
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API download backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups/<backup_type>/<filename>', methods=['DELETE'])
@admin_required
def delete_backup(backup_type, filename):
    """Supprime un backup identifié par (type, nom de fichier)."""
    try:
        monitoring_service = current_app.extensions['monitoring']
        result = monitoring_service.delete_backup(backup_type, filename)

        if result['success']:
            return jsonify(result)
        status = 404 if result.get('error') == 'Backup non trouvé' else 400
        return jsonify(result), status
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API delete backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

