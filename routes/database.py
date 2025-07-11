#!/usr/bin/env python3
"""
Routes pour la gestion des bases de données
"""
import os
import tempfile
from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename

from config.app_config import PROJECTS_FOLDER, CONTAINERS_FOLDER
from utils.file_utils import allowed_file, get_file_size
from utils.database_utils import prepare_sql_file, backup_database
from models.project import Project
from utils.logger import wp_logger

database_bp = Blueprint('database', __name__)


@database_bp.route('/test_upload', methods=['POST'])
def test_upload():
    """Endpoint de test pour débugger l'upload de fichiers"""
    try:
        print(f"🧪 [TEST_UPLOAD] Test d'upload de fichier")
        print(f"🔍 [TEST_UPLOAD] Request method: {request.method}")
        print(f"🔍 [TEST_UPLOAD] Content-Type: {request.content_type}")
        print(f"🔍 [TEST_UPLOAD] Files in request: {list(request.files.keys())}")
        print(f"🔍 [TEST_UPLOAD] Form data: {list(request.form.keys())}")
        
        if 'db_file' in request.files:
            db_file = request.files['db_file']
            print(f"📁 [TEST_UPLOAD] Fichier trouvé: {db_file.filename}")
            print(f"📊 [TEST_UPLOAD] Content-Type du fichier: {db_file.content_type}")
            
            if db_file.filename:
                file_size = get_file_size(db_file)
                print(f"📊 [TEST_UPLOAD] Taille du fichier: {file_size} bytes")
                
                return jsonify({
                    'success': True,
                    'message': 'Test d\'upload réussi',
                    'details': {
                        'filename': db_file.filename,
                        'content_type': db_file.content_type,
                        'file_size': file_size
                    }
                })
            else:
                return jsonify({'success': False, 'message': 'Nom de fichier vide'})
        else:
            return jsonify({'success': False, 'message': 'Aucun fichier db_file trouvé'})
            
    except Exception as e:
        print(f"❌ [TEST_UPLOAD] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/fast_import_database/<project_name>', methods=['POST'])
def fast_import_database(project_name):
    """Import ultra-rapide de base de données avec FastImportService"""
    try:
        print(f"🚀 [FAST_IMPORT] Début import ultra-rapide pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            print(f"❌ [FAST_IMPORT] Projet non trouvé: {project_path}")
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            print(f"❌ [FAST_IMPORT] Aucun fichier db_file dans la requête")
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        print(f"📁 [FAST_IMPORT] Fichier reçu: {db_file.filename}")
        
        if db_file.filename == '':
            print(f"❌ [FAST_IMPORT] Nom de fichier vide")
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            print(f"❌ [FAST_IMPORT] Type de fichier non autorisé: {db_file.filename}")
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        print(f"✅ [FAST_IMPORT] Fichier validé: {db_file.filename}")
        
        # Sauvegarder le fichier temporairement
        filename = secure_filename(db_file.filename)
        temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"temp_{project_name}_{filename}")
        db_file.save(temp_path)
        
        try:
            # Utiliser le FastImportService
            fast_import_service = current_app.extensions.get('fast_import_service')
            if fast_import_service:
                success = fast_import_service.import_database(
                    project_name, 
                    temp_path, 
                    os.path.join(CONTAINERS_FOLDER, project_name)
                )
                
                if success:
                    return jsonify({
                        'success': True,
                        'message': 'Import ultra-rapide terminé avec succès'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Erreur lors de l\'import ultra-rapide'
                    })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Service d\'import rapide non disponible'
                })
                
        finally:
            # Nettoyer le fichier temporaire
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
    except Exception as e:
        print(f"❌ [FAST_IMPORT] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/update_database/<project_name>', methods=['POST'])
def update_database(project_name):
    """Met à jour la base de données d'un projet existant"""
    try:
        print(f"🔄 [UPDATE_DB] Début mise à jour DB pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            print(f"❌ [UPDATE_DB] Projet non trouvé: {project_path}")
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            print(f"❌ [UPDATE_DB] Aucun fichier db_file dans la requête")
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        print(f"📁 [UPDATE_DB] Fichier reçu: {db_file.filename}")
        
        if db_file.filename == '':
            print(f"❌ [UPDATE_DB] Nom de fichier vide")
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            print(f"❌ [UPDATE_DB] Type de fichier non autorisé: {db_file.filename}")
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        print(f"✅ [UPDATE_DB] Fichier validé: {db_file.filename}")
        
        # Sauvegarder le fichier temporairement
        filename = secure_filename(db_file.filename)
        temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"update_{project_name}_{filename}")
        db_file.save(temp_path)
        
        try:
            # Utiliser le DatabaseService
            database_service = current_app.extensions.get('database_service')
            if database_service:
                success = database_service.update_database(
                    project_name, 
                    temp_path, 
                    os.path.join(CONTAINERS_FOLDER, project_name)
                )
                
                if success:
                    return jsonify({
                        'success': True,
                        'message': 'Base de données mise à jour avec succès'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Erreur lors de la mise à jour de la base de données'
                    })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Service de base de données non disponible'
                })
                
        finally:
            # Nettoyer le fichier temporaire
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
    except Exception as e:
        print(f"❌ [UPDATE_DB] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/export_database/<project_name>', methods=['POST'])
def export_database(project_name):
    """Exporte la base de données d'un projet"""
    try:
        print(f"📤 [EXPORT_DB] Début export DB pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Utiliser le service de base de données pour l'export
        database_service = current_app.extensions.get('database_service')
        if database_service:
            export_path = database_service.export_database(project_name)
            
            if export_path and os.path.exists(export_path):
                return jsonify({
                    'success': True,
                    'message': 'Export terminé avec succès',
                    'download_url': f'/download_export/{os.path.basename(export_path)}'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Erreur lors de l\'export de la base de données'
                })
        else:
            return jsonify({
                'success': False,
                'message': 'Service de base de données non disponible'
            })
            
    except Exception as e:
        print(f"❌ [EXPORT_DB] Exception: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/download_export/<filename>')
def download_export(filename):
    """Télécharge un fichier d'export de base de données"""
    try:
        # Sécuriser le nom du fichier
        filename = secure_filename(filename)
        
        # Chemin vers le dossier d'exports
        exports_dir = os.path.join(current_app.root_path, 'exports')
        file_path = os.path.join(exports_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        # Envoyer le fichier en téléchargement
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        print(f"❌ Erreur téléchargement export: {e}")
        return jsonify({'error': str(e)}), 500 