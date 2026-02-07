#!/usr/bin/env python3
"""
Routes pour le monitoring système et la gestion des backups
"""

from flask import Blueprint, render_template, jsonify, request, current_app
from app.utils.logger import wp_logger

monitoring_bp = Blueprint('monitoring', __name__)


@monitoring_bp.route('/monitoring')
def monitoring_page():
    """Page principale du monitoring"""
    return render_template('monitoring.html')


@monitoring_bp.route('/backups')
def backups_page():
    """Page de gestion des backups"""
    return render_template('backups.html')


@monitoring_bp.route('/api/monitoring/system', methods=['GET'])
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
def kill_process():
    """Termine un processus"""
    try:
        data = request.get_json()
        pid = data.get('pid')
        
        if not pid:
            return jsonify({'success': False, 'error': 'PID manquant'}), 400
        
        import psutil
        import signal
        
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
def run_backup():
    """Lance un backup manuel"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        data = request.get_json() or {}
        backup_type = data.get('type', 'all')  # all, mysql, mongodb
        
        result = monitoring_service.run_backup(backup_type=backup_type)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API run backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/api/backups/<path:backup_id>', methods=['DELETE'])
def delete_backup(backup_id):
    """Supprime un backup"""
    try:
        monitoring_service = current_app.extensions['monitoring']
        
        # Reconstruire le chemin complet
        if 'mysql' in backup_id:
            backup_path = f"/home/dev-server/backups/mysql/{backup_id}"
        elif 'mongodb' in backup_id:
            backup_path = f"/home/dev-server/backups/mongodb/{backup_id}"
        else:
            return jsonify({'success': False, 'error': 'Type de backup invalide'}), 400
        
        result = monitoring_service.delete_backup(backup_path)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API delete backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

