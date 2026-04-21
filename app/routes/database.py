#!/usr/bin/env python3
"""
Routes pour la gestion des bases de données.

Flow d'un import :
  POST /fast_import_database/<project>  (multipart form, field ``db_file``)
    -> sauvegarde temporaire dans UPLOAD_FOLDER/uuid_{name}
    -> thread daemon -> FastImportService.import_database
    -> suivi via Socket.IO event ``import_progress``
"""
import logging
import os
import subprocess
import threading
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from app.config.app_config import CONTAINERS_FOLDER, PROJECTS_FOLDER
from app.middleware.auth_middleware import admin_required
from app.utils.file_utils import allowed_file

database_bp = Blueprint('database', __name__)
log = logging.getLogger(__name__)

# Registry of running imports — referenced by the stop-import endpoint.
# Keyed by project_name; value is the worker thread. Defined at module
# scope so nested functions can ``del import_processes[project_name]``
# without the previous NameError.
import_processes: dict[str, threading.Thread] = {}


def _save_upload_to_tmp(db_file, project_name: str, prefix: str = "import") -> str:
    """Save the uploaded FileStorage to a unique path under UPLOAD_FOLDER.

    Uses a UUID suffix to avoid clobbering concurrent imports on the
    same project (the old ``temp_<project>_<filename>`` scheme would
    overwrite if two uploads raced).
    """
    filename = secure_filename(db_file.filename or "")
    if not filename:
        raise ValueError("Invalid filename.")
    unique = uuid.uuid4().hex[:8]
    target = os.path.join(
        current_app.config['UPLOAD_FOLDER'],
        f"{prefix}_{project_name}_{unique}_{filename}",
    )
    db_file.save(target)
    return target


@database_bp.route('/fast_import_database/<project_name>', methods=['POST'])
@admin_required
def fast_import_database(project_name):
    """Launch an async ultra-fast DB import for the target WordPress project.

    Response is immediate (202-style via HTTP 200) — progress streams
    through Socket.IO room-less events so the existing
    ``showImportLogsModal`` UI picks them up.
    """
    project_path = os.path.join(PROJECTS_FOLDER, project_name)
    if not os.path.exists(project_path):
        return jsonify({'success': False, 'message': 'Projet non trouvé'}), 404

    if 'db_file' not in request.files:
        return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'}), 400

    db_file = request.files['db_file']
    if not db_file.filename:
        return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'}), 400
    if not allowed_file(db_file.filename):
        return jsonify({'success': False, 'message': 'Type de fichier non autorisé (.sql, .sql.gz, .zip)'}), 400

    try:
        temp_path = _save_upload_to_tmp(db_file, project_name, prefix="import")
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

    filename = os.path.basename(temp_path)
    log.info("fast_import_database queued: project=%s file=%s", project_name, filename)

    app = current_app._get_current_object()

    def run_import():
        with app.app_context():
            fast_import_service = app.extensions.get('fast_import_service')
            if not fast_import_service:
                log.error("fast_import_service missing from app.extensions")
                return
            try:
                fast_import_service.import_database(project_name, temp_path)
            except Exception:  # noqa: BLE001
                log.exception("fast_import worker crashed for %s", project_name)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        log.warning("Could not remove temp file %s", temp_path)
                import_processes.pop(project_name, None)

    thread = threading.Thread(target=run_import, daemon=True, name=f"fast-import-{project_name}")
    import_processes[project_name] = thread
    thread.start()

    return jsonify({
        'success': True,
        'message': f'Import de {filename} démarré. Suivez la progression dans les notifications.'
    })


@database_bp.route('/update_database/<project_name>', methods=['POST'])
@admin_required
def update_database(project_name):
    """Legacy alias — delegates to the fast import service."""
    return fast_import_database(project_name)


@database_bp.route('/export_database/<project_name>', methods=['POST'])
@admin_required
def export_database(project_name):
    """Exporte la base de données d'un projet avec mysqldump direct."""
    project_path = os.path.join(PROJECTS_FOLDER, project_name)
    if not os.path.exists(project_path):
        return jsonify({'success': False, 'message': 'Projet non trouvé'}), 404

    import datetime
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    export_filename = f"{project_name}_export_{timestamp}.sql"
    export_path = os.path.join(current_app.config['UPLOAD_FOLDER'], export_filename)

    mysql_container = f"{project_name}_mysql_1"

    # Project type detection — Next.js uses per-project DB/user, WP uses fixed.
    if os.path.exists(os.path.join(project_path, 'client')):
        db_user = project_name
        db_password = 'projectpassword'
        db_name = project_name
    else:
        db_user = 'wordpress'
        db_password = 'wordpress'
        db_name = 'wordpress'

    config_cmd = (
        "printf '[mysqldump]\\nuser=%s\\npassword=%s\\n' "
        f"{_sh_quote(db_user)} {_sh_quote(db_password)} "
        "> /tmp/.mysqldump.cnf && chmod 600 /tmp/.mysqldump.cnf"
    )

    try:
        config_result = subprocess.run(
            ['docker', 'exec', mysql_container, 'bash', '-c', config_cmd],
            capture_output=True, text=True, timeout=10,
        )
        if config_result.returncode != 0:
            return jsonify({
                'success': False,
                'message': f'Erreur création config: {config_result.stderr}',
            }), 500

        export_cmd = [
            'docker', 'exec', mysql_container,
            'mysqldump',
            '--defaults-file=/tmp/.mysqldump.cnf',
            '--quick',
            '--lock-tables=false',
            '--single-transaction',
            '--routines',
            '--triggers',
            '--complete-insert',
            '--extended-insert',
            '--hex-blob',
            '--no-tablespaces',
            '--default-character-set=utf8mb4',
            db_name,
        ]

        with open(export_path, 'w', encoding='utf-8') as export_file:
            result = subprocess.run(
                export_cmd,
                stdout=export_file,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1800,
            )

        if result.returncode != 0:
            if os.path.exists(export_path):
                os.remove(export_path)
            err_text = result.stderr or "Pas de message d'erreur"
            return jsonify({
                'success': False,
                'message': f'Erreur mysqldump (code {result.returncode}): {err_text}',
            }), 500

        export_size_mb = os.path.getsize(export_path) / (1024 * 1024)
        return jsonify({
            'success': True,
            'message': f'Export terminé avec succès ({export_size_mb:.1f}MB)',
            'download_url': f'/download_export/{export_filename}',
            'filename': export_filename,
        })

    except subprocess.TimeoutExpired:
        if os.path.exists(export_path):
            os.remove(export_path)
        return jsonify({
            'success': False,
            'message': "Timeout lors de l'export (plus de 30 minutes)",
        }), 504
    except Exception as exc:  # noqa: BLE001
        log.exception("export_database crashed for %s", project_name)
        if os.path.exists(export_path):
            os.remove(export_path)
        return jsonify({'success': False, 'message': f"Erreur lors de l'export: {exc}"}), 500
    finally:
        try:
            subprocess.run(
                ['docker', 'exec', mysql_container, 'rm', '-f', '/tmp/.mysqldump.cnf'],
                capture_output=True, timeout=10,
            )
        except Exception:  # noqa: BLE001
            log.warning("Export cleanup failed for %s", project_name)


@database_bp.route('/api/database/stop-import/<project_name>', methods=['POST'])
@admin_required
def stop_import(project_name):
    """Arrête un import de base de données en cours."""
    if project_name not in import_processes:
        return jsonify({'success': False, 'message': 'Aucun import en cours pour ce projet'}), 404

    # Python threads can't be force-killed; we drop the registry
    # entry so the fallback cleanup runs, and disable the .maintenance
    # file so the site becomes accessible again.
    import_processes.pop(project_name, None)
    try:
        fast_import_service = current_app.extensions.get('fast_import_service')
        if fast_import_service:
            fast_import_service.disable_maintenance_mode(project_name)
    except Exception:  # noqa: BLE001
        log.exception("stop_import: failed to disable maintenance for %s", project_name)

    return jsonify({'success': True, 'message': f'Import arrêté pour {project_name}'})


@database_bp.route('/download_export/<filename>')
@admin_required
def download_export(filename):
    """Télécharge un fichier d'export de base de données."""
    secure_name = secure_filename(filename)
    if not secure_name.endswith('.sql'):
        return jsonify({'success': False, 'message': 'Type de fichier non autorisé'}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(os.getcwd(), upload_folder)
    export_path = os.path.join(upload_folder, secure_name)

    if not os.path.exists(export_path):
        return jsonify({'success': False, 'message': "Fichier d'export non trouvé"}), 404

    return send_file(
        export_path,
        as_attachment=True,
        download_name=secure_name,
        mimetype='application/sql',
    )


# Silences only — internal helper for the export flow's bash heredoc.
def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


# Keep a reference to CONTAINERS_FOLDER — pre-existing call sites expect
# it importable from this module. The import itself has a side effect
# (registering path config) in some deployments.
_ = CONTAINERS_FOLDER