#!/usr/bin/env python3
"""
Utilitaires pour la gestion des fichiers
"""

import os
import zipfile
import shutil
import chardet
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'zip', 'sql', 'gz'}

def allowed_file(filename):
    """Vérifie si le fichier est autorisé"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_zip(zip_path, extract_to):
    """Extrait un fichier ZIP vers le dossier de destination"""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

def secure_project_name(name):
    """Sécurise un nom de projet"""
    return secure_filename(name.replace(' ', '-').lower())

def secure_hostname(hostname):
    """Sécurise un hostname"""
    hostname = hostname.lower().replace(' ', '-')
    if not hostname.endswith('.local') and not hostname.endswith('.dev'):
        hostname += '.local'
    return hostname

def detect_file_encoding(file_path):
    """
    Détecte l'encodage d'un fichier et retourne son contenu
    Returns: (encoding, content)
    """
    # Essayer de détecter l'encodage avec chardet
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        detected_encoding = result.get('encoding', 'utf-8')
        confidence = result.get('confidence', 0)
    
    print(f"🔍 Encodage détecté: {detected_encoding} (confiance: {confidence:.2f})")
    
    # Liste des encodages à tester par ordre de priorité
    encodings_to_try = [
        detected_encoding,
        'utf-8',
        'latin1',
        'iso-8859-1',
        'cp1252',
        'ascii'
    ]
    
    # Supprimer les doublons tout en gardant l'ordre
    encodings_to_try = list(dict.fromkeys(filter(None, encodings_to_try)))
    
    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"✅ Fichier lu avec succès en {encoding}")
                return encoding, content
        except (UnicodeDecodeError, UnicodeError) as e:
            print(f"❌ Échec lecture en {encoding}: {e}")
            continue
        except Exception as e:
            print(f"❌ Erreur lecture {encoding}: {e}")
            continue
    
    print("❌ Impossible de décoder le fichier avec les encodages supportés")
    return None, None

def get_file_size_mb(file_path):
    """Retourne la taille d'un fichier en MB"""
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    except OSError:
        return 0

def copy_directory(src, dst):
    """Copie un répertoire récursivement"""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

def remove_directory(path):
    """Supprime un répertoire récursivement"""
    if os.path.exists(path):
        shutil.rmtree(path)

def ensure_directory(path):
    """S'assure qu'un répertoire existe"""
    if not os.path.exists(path):
        os.makedirs(path)

def read_file_lines(file_path, max_lines=None):
    """Lit les premières lignes d'un fichier"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if max_lines:
                return [f.readline().strip() for _ in range(max_lines)]
            else:
                return f.readlines()
    except Exception as e:
        print(f"Erreur lecture fichier {file_path}: {e}")
        return []

def write_file(file_path, content, encoding='utf-8'):
    """Écrit du contenu dans un fichier"""
    try:
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Erreur écriture fichier {file_path}: {e}")
        return False

def file_exists(file_path):
    """Vérifie si un fichier existe"""
    return os.path.isfile(file_path)

def directory_exists(dir_path):
    """Vérifie si un répertoire existe"""
    return os.path.isdir(dir_path)

def get_file_extension(filename):
    """Retourne l'extension d'un fichier"""
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

def is_archive_file(filename):
    """Vérifie si un fichier est une archive"""
    extension = get_file_extension(filename)
    return extension in ['zip', 'tar', 'gz', '7z', 'rar']

def is_sql_file(filename):
    """Vérifie si un fichier est un fichier SQL"""
    extension = get_file_extension(filename)
    return extension in ['sql']

def sanitize_filename(filename):
    """Nettoie un nom de fichier pour éviter les problèmes"""
    # Caractères interdits dans les noms de fichiers
    forbidden_chars = '<>:"/\\|?*'
    for char in forbidden_chars:
        filename = filename.replace(char, '_')
    
    # Limiter la longueur
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename

def get_directory_size(path):
    """Calcule la taille totale d'un répertoire en bytes"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except OSError:
                    pass
    except OSError:
        pass
    return total_size

def format_file_size(size_bytes):
    """Formate une taille en bytes en format lisible"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

def cleanup_temp_files(file_paths):
    """Nettoie une liste de fichiers temporaires"""
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                print(f"🧹 Fichier temporaire supprimé: {file_path}")
        except Exception as e:
            print(f"⚠️ Erreur suppression fichier temporaire {file_path}: {e}")

def create_backup(source_path, backup_dir):
    """Crée une sauvegarde d'un fichier ou répertoire"""
    try:
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{os.path.basename(source_path)}_backup_{timestamp}"
        backup_path = os.path.join(backup_dir, backup_name)
        
        if os.path.isfile(source_path):
            shutil.copy2(source_path, backup_path)
        elif os.path.isdir(source_path):
            shutil.copytree(source_path, backup_path)
        
        print(f"💾 Sauvegarde créée: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"❌ Erreur création sauvegarde: {e}")
        return None

def find_files_by_extension(directory, extension):
    """Trouve tous les fichiers avec une extension donnée dans un répertoire"""
    files = []
    try:
        for root, dirs, filenames in os.walk(directory):
            for filename in filenames:
                if filename.lower().endswith(f'.{extension.lower()}'):
                    files.append(os.path.join(root, filename))
    except OSError as e:
        print(f"Erreur recherche fichiers: {e}")
    return files

def validate_file_path(file_path):
    """Valide qu'un chemin de fichier est sûr"""
    # Vérifier qu'il n'y a pas de traversée de répertoire
    normalized_path = os.path.normpath(file_path)
    if '..' in normalized_path or normalized_path.startswith('/'):
        return False
    return True 