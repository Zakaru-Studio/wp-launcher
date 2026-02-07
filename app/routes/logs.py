"""
Routes pour la gestion des logs
"""
import os
import json
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request
from werkzeug.utils import secure_filename

logs_bp = Blueprint('logs', __name__)

LOGS_DIR = '/home/dev-server/Sites/wp-launcher/logs'

def get_log_files():
    """Récupère la liste des fichiers de logs organisés par catégorie"""
    log_structure = {}
    
    if not os.path.exists(LOGS_DIR):
        return log_structure
    
    # Parcourir le dossier logs
    for item in os.listdir(LOGS_DIR):
        item_path = os.path.join(LOGS_DIR, item)
        
        if os.path.isfile(item_path) and (item.endswith('.log') or item.startswith('app.log')):
            # Fichier de log à la racine (inclut app.log et app.log.*)
            if 'general' not in log_structure:
                log_structure['general'] = []
            
            stat = os.stat(item_path)
            log_structure['general'].append({
                'name': item,
                'path': item_path,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
        
        elif os.path.isdir(item_path):
            # Dossier de logs
            category_logs = []
            
            for log_file in os.listdir(item_path):
                log_file_path = os.path.join(item_path, log_file)
                
                if os.path.isfile(log_file_path) and log_file.endswith('.log'):
                    stat = os.stat(log_file_path)
                    category_logs.append({
                        'name': log_file,
                        'path': log_file_path,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            if category_logs:
                log_structure[item] = category_logs
    
    # Trier les fichiers par date de modification (plus récent en premier)
    for category in log_structure:
        log_structure[category].sort(key=lambda x: x['modified'], reverse=True)
    
    return log_structure

def format_file_size(size_bytes):
    """Formate la taille du fichier en unités lisibles"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

@logs_bp.route('/logs')
def logs_page():
    """Page principale des logs"""
    log_structure = get_log_files()
    
    # Formater les tailles de fichiers
    for category, files in log_structure.items():
        for file_info in files:
            file_info['formatted_size'] = format_file_size(file_info['size'])
    
    return render_template('logs.html', log_structure=log_structure)

@logs_bp.route('/api/logs/content')
def get_log_content():
    """Récupère le contenu d'un fichier de log"""
    file_path = request.args.get('file')
    lines = int(request.args.get('lines', 100))
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Fichier non trouvé'}), 404
    
    # Vérifier que le fichier est dans le dossier logs (sécurité)
    if not file_path.startswith(LOGS_DIR):
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
            
            # Prendre les dernières lignes
            content_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            return jsonify({
                'content': ''.join(content_lines),
                'total_lines': len(all_lines),
                'displayed_lines': len(content_lines)
            })
    
    except Exception as e:
        return jsonify({'error': f'Erreur lors de la lecture: {str(e)}'}), 500

@logs_bp.route('/api/logs/delete', methods=['POST'])
def delete_log_file():
    """Supprime un fichier de log spécifique"""
    data = request.get_json()
    file_path = data.get('file')
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Fichier non trouvé'}), 404
    
    # Vérifier que le fichier est dans le dossier logs (sécurité)
    if not file_path.startswith(LOGS_DIR):
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        os.remove(file_path)
        return jsonify({'success': True, 'message': 'Fichier supprimé avec succès'})
    
    except Exception as e:
        return jsonify({'error': f'Erreur lors de la suppression: {str(e)}'}), 500

@logs_bp.route('/api/logs/delete-all', methods=['POST'])
def delete_all_logs():
    """Supprime tous les fichiers de logs"""
    deleted_count = 0
    errors = []
    
    try:
        # Supprimer tous les fichiers .log dans le dossier principal
        for item in os.listdir(LOGS_DIR):
            item_path = os.path.join(LOGS_DIR, item)
            
            if os.path.isfile(item_path) and item.endswith('.log'):
                try:
                    os.remove(item_path)
                    deleted_count += 1
                except Exception as e:
                    errors.append(f"Erreur avec {item}: {str(e)}")
            
            elif os.path.isdir(item_path):
                # Supprimer tous les fichiers .log dans les sous-dossiers
                for log_file in os.listdir(item_path):
                    log_file_path = os.path.join(item_path, log_file)
                    
                    if os.path.isfile(log_file_path) and log_file.endswith('.log'):
                        try:
                            os.remove(log_file_path)
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"Erreur avec {log_file}: {str(e)}")
        
        if errors:
            return jsonify({
                'success': True,
                'message': f'{deleted_count} fichiers supprimés avec quelques erreurs',
                'errors': errors
            })
        else:
            return jsonify({
                'success': True,
                'message': f'{deleted_count} fichiers de logs supprimés avec succès'
            })
    
    except Exception as e:
        return jsonify({'error': f'Erreur générale: {str(e)}'}), 500

@logs_bp.route('/api/logs/refresh')
def refresh_logs():
    """Rafraîchit la liste des logs"""
    log_structure = get_log_files()
    
    # Formater les tailles de fichiers
    for category, files in log_structure.items():
        for file_info in files:
            file_info['formatted_size'] = format_file_size(file_info['size'])
    
    return jsonify(log_structure)
