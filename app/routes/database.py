#!/usr/bin/env python3
"""
Routes pour la gestion des bases de données
"""
import os
import tempfile
from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import subprocess

from app.config.app_config import PROJECTS_FOLDER, CONTAINERS_FOLDER
from app.utils.file_utils import allowed_file, get_file_size
from app.utils.database_utils import prepare_sql_file, backup_database

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
    """Import ultra-rapide de base de données avec FastImportService (asynchrone)"""
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
        if not db_file.filename:
            return jsonify({'success': False, 'message': 'Nom de fichier invalide'})
        
        filename = secure_filename(db_file.filename)
        temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"temp_{project_name}_{filename}")
        db_file.save(temp_path)
        
        # Lancer l'import dans un thread séparé pour ne pas bloquer la requête HTTP
        import threading
        
        # Capturer l'application Flask pour l'utiliser dans le thread
        app = current_app._get_current_object()
        
        def run_import():
            """Fonction pour exécuter l'import en arrière-plan"""
            print(f"🧵 [THREAD] Thread d'import démarré pour {project_name}")
            print(f"📁 [THREAD] Fichier temporaire: {temp_path}")
            
            with app.app_context():
                print(f"🔌 [THREAD] Contexte Flask obtenu")
                fast_import_service = app.extensions.get('fast_import_service')
                print(f"📦 [THREAD] Service trouvé: {fast_import_service is not None}")
                
                if fast_import_service:
                    try:
                        print(f"🚀 [THREAD] Appel de import_database...")
                        result = fast_import_service.import_database(project_name, temp_path)
                        print(f"✅ [THREAD] Import terminé avec résultat: {result}")
                    except Exception as e:
                        print(f"❌ [FAST_IMPORT_THREAD] Erreur dans le thread d'import: {e}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        # Nettoyer le fichier temporaire
                        if os.path.exists(temp_path):
                            print(f"🧹 [THREAD] Suppression du fichier temporaire: {temp_path}")
                            os.remove(temp_path)
                else:
                    print(f"❌ [THREAD] Service fast_import_service non trouvé dans les extensions!")
                    print(f"📋 [THREAD] Extensions disponibles: {list(app.extensions.keys())}")
        
        # Démarrer le thread d'import
        import_thread = threading.Thread(target=run_import, daemon=True)
        import_thread.start()
        
        # Retourner immédiatement au client - le suivi se fait via SocketIO
        return jsonify({
            'success': True,
            'message': f'Import de {filename} démarré avec succès. Suivez la progression dans les notifications.'
        })
            
    except Exception as e:
        print(f"❌ [FAST_IMPORT] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/update_database/<project_name>', methods=['POST'])
def update_database(project_name):
    """Met à jour la base de données d'un projet existant (asynchrone)"""
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
        if not db_file.filename:
            return jsonify({'success': False, 'message': 'Nom de fichier invalide'})
        
        filename = secure_filename(db_file.filename)
        temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"update_{project_name}_{filename}")
        db_file.save(temp_path)
        
        # Lancer l'import dans un thread séparé pour ne pas bloquer la requête HTTP
        import threading
        
        # Capturer l'application Flask pour l'utiliser dans le thread
        app = current_app._get_current_object()
        
        def run_update():
            """Fonction pour exécuter la mise à jour en arrière-plan"""
            with app.app_context():
                database_service = app.extensions.get('database_service')
                if database_service:
                    try:
                        database_service.update_database(
                            project_name, 
                            temp_path, 
                            os.path.join(CONTAINERS_FOLDER, project_name)
                        )
                    except Exception as e:
                        print(f"❌ [UPDATE_DB_THREAD] Erreur dans le thread de mise à jour: {e}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        # Nettoyer le fichier temporaire
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        # Retirer des imports en cours
                        if project_name in import_processes:
                            del import_processes[project_name]
        
        # Démarrer le thread de mise à jour
        update_thread = threading.Thread(target=run_update, daemon=True)
        update_thread.start()
        
        # Stocker le thread pour pouvoir l'arrêter plus tard
        import_processes[project_name] = update_thread
        
        # Retourner immédiatement au client - le suivi se fait via SocketIO
        return jsonify({
            'success': True,
            'message': f'Import de {filename} démarré avec succès. Suivez la progression dans les notifications.'
        })
            
    except Exception as e:
        print(f"❌ [UPDATE_DB] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/export_database/<project_name>', methods=['POST'])
def export_database(project_name):
    """Exporte la base de données d'un projet avec mysqldump direct"""
    try:
        print(f"📤 [EXPORT_DB] Début export DB pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Créer un nom de fichier unique
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        export_filename = f"{project_name}_export_{timestamp}.sql"
        export_path = os.path.join(current_app.config['UPLOAD_FOLDER'], export_filename)
        
        # Vérifier que le conteneur MySQL existe
        mysql_container = f"{project_name}_mysql_1"
        
        # Déterminer les paramètres de connexion selon le type de projet
        # Pour les projets Next.js+MySQL, utiliser les paramètres du projet
        # Pour les projets WordPress, utiliser les paramètres wordpress
        if os.path.exists(os.path.join(project_path, 'client')):
            # Projet Next.js+MySQL
            db_user = project_name
            db_password = 'projectpassword'
            db_name = project_name
        else:
            # Projet WordPress
            db_user = 'wordpress'
            db_password = 'wordpress'
            db_name = 'wordpress'
        
        print(f"🔍 [EXPORT_DB] Conteneur: {mysql_container}")
        print(f"🔍 [EXPORT_DB] Base de données: {db_name}")
        print(f"🔍 [EXPORT_DB] Utilisateur: {db_user}")
        
        try:
            # Commande mysqldump optimisée
            export_cmd = [
                'docker', 'exec', mysql_container,
                'mysqldump',
                '--quick',  # Récupérer les lignes une par une
                '--lock-tables=false',  # Éviter le verrouillage
                '--single-transaction',  # Export transactionnel
                '--routines',  # Exporter les procédures stockées
                '--triggers',  # Exporter les triggers
                '--complete-insert',  # Insérer avec noms de colonnes
                '--extended-insert',  # Grouper les INSERT
                '--hex-blob',  # Encoder les BLOB en hexadécimal
                '--default-character-set=utf8mb4',
                f'-u{db_user}',
                f'-p{db_password}',
                db_name
            ]
            
            print(f"🚀 [EXPORT_DB] Exécution de mysqldump...")
            
            # Exécuter l'export avec timeout étendu
            with open(export_path, 'w', encoding='utf-8') as export_file:
                result = subprocess.run(
                    export_cmd,
                    stdout=export_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=1800  # 30 minutes max
                )
            
            if result.returncode == 0:
                # Vérifier la taille du fichier exporté
                if os.path.exists(export_path):
                    export_size = os.path.getsize(export_path)
                    export_size_mb = export_size / (1024 * 1024)
                    
                    print(f"✅ [EXPORT_DB] Export réussi: {export_path} ({export_size_mb:.2f}MB)")
                    
                    return jsonify({
                        'success': True,
                        'message': f'Export terminé avec succès ({export_size_mb:.1f}MB)',
                        'download_url': f'/download_export/{export_filename}',
                        'filename': export_filename
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Fichier d\'export non créé'
                    })
            else:
                print(f"❌ [EXPORT_DB] Erreur lors de l'export: {result.stderr}")
                if os.path.exists(export_path):
                    os.remove(export_path)  # Supprimer le fichier incomplet
                return jsonify({
                    'success': False,
                    'message': f'Erreur lors de l\'export: {result.stderr}'
                })
                
        except subprocess.TimeoutExpired:
            print("❌ [EXPORT_DB] Timeout lors de l'export")
            if os.path.exists(export_path):
                os.remove(export_path)
            return jsonify({
                'success': False,
                'message': 'Timeout lors de l\'export (plus de 30 minutes)'
            })
        except Exception as e:
            print(f"❌ [EXPORT_DB] Erreur lors de l'export: {e}")
            if os.path.exists(export_path):
                os.remove(export_path)
            return jsonify({
                'success': False,
                'message': f'Erreur lors de l\'export: {str(e)}'
            })
            
    except Exception as e:
        print(f"❌ [EXPORT_DB] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@database_bp.route('/api/database/stop-import/<project_name>', methods=['POST'])
def stop_import(project_name):
    """Arrête un import de base de données en cours"""
    try:
        print(f"🛑 [STOP_IMPORT] Demande d'arrêt pour le projet: {project_name}")
        
        # Vérifier si un import est en cours pour ce projet
        if project_name not in import_processes:
            print(f"⚠️ [STOP_IMPORT] Aucun import en cours pour {project_name}")
            return jsonify({
                'success': False,
                'message': 'Aucun import en cours pour ce projet'
            })
        
        # Récupérer le thread d'import
        import_thread = import_processes[project_name]
        
        # On ne peut pas vraiment arrêter un thread Python de force
        # Mais on peut marquer qu'il doit s'arrêter et nettoyer les ressources
        print(f"⚠️ [STOP_IMPORT] Marquage de l'import comme annulé pour {project_name}")
        
        # Supprimer de la liste des imports en cours
        del import_processes[project_name]
        
        # Désactiver le mode maintenance
        try:
            from app.services.fast_import_service import FastImportService
            fast_import_service = current_app.extensions.get('fast_import_service')
            if fast_import_service:
                project_path = os.path.join(fast_import_service.projects_folder, project_name)
                fast_import_service._disable_maintenance_mode(project_path)
                print(f"✅ [STOP_IMPORT] Mode maintenance désactivé pour {project_name}")
        except Exception as e:
            print(f"⚠️ [STOP_IMPORT] Erreur lors de la désactivation du mode maintenance: {e}")
        
        print(f"✅ [STOP_IMPORT] Import marqué comme arrêté pour {project_name}")
        
        return jsonify({
            'success': True,
            'message': f'Import arrêté pour {project_name}'
        })
        
    except Exception as e:
        print(f"❌ [STOP_IMPORT] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur lors de l\'arrêt de l\'import: {str(e)}'
        })


@database_bp.route('/download_export/<filename>')
def download_export(filename):
    """Télécharge un fichier d'export de base de données"""
    try:
        # Sécuriser le nom du fichier
        secure_name = secure_filename(filename)
        if not secure_name.endswith('.sql'):
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        # Chemin vers le fichier d'export dans UPLOAD_FOLDER
        upload_folder = current_app.config['UPLOAD_FOLDER']
        # Assurer un chemin absolu
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(os.getcwd(), upload_folder)
        export_path = os.path.join(upload_folder, secure_name)
        
        print(f"🔍 [DOWNLOAD_EXPORT] Recherche fichier: {export_path}")
        
        if not os.path.exists(export_path):
            return jsonify({'success': False, 'message': f'Fichier d\'export non trouvé: {export_path}'})
        
        # Envoyer le fichier en téléchargement
        return send_file(
            export_path,
            as_attachment=True,
            download_name=secure_name,
            mimetype='application/sql'
        )
        
    except Exception as e:
        print(f"❌ [DOWNLOAD_EXPORT] Exception: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}) 