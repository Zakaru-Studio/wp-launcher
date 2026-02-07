#!/usr/bin/env python3
"""
Script de rotation des logs app.log
- Limite: 10 000 lignes par fichier
- Garde les 7 derniers fichiers (7 jours)
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

def rotate_app_log(log_file_path, max_lines=10000, backup_count=7):
    """
    Rotate le fichier app.log si nécessaire
    
    Args:
        log_file_path: Chemin vers app.log
        max_lines: Nombre maximum de lignes avant rotation
        backup_count: Nombre de fichiers backup à garder
    """
    log_file = Path(log_file_path)
    
    if not log_file.exists():
        print(f"⚠️  Fichier {log_file} non trouvé")
        return
    
    # Compter les lignes
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            line_count = sum(1 for _ in f)
    except Exception as e:
        print(f"❌ Erreur lors de la lecture du fichier: {e}")
        return
    
    print(f"📊 {log_file.name} contient {line_count} lignes")
    
    # Rotation si nécessaire
    if line_count >= max_lines:
        print(f"🔄 Rotation nécessaire (>= {max_lines} lignes)")
        
        # Supprimer le plus ancien backup si nécessaire
        oldest_backup = log_file.parent / f"{log_file.name}.{backup_count}"
        if oldest_backup.exists():
            oldest_backup.unlink()
            print(f"🗑️  Supprimé: {oldest_backup.name}")
        
        # Renommer les backups existants (de n-1 vers n)
        for i in range(backup_count - 1, 0, -1):
            old_backup = log_file.parent / f"{log_file.name}.{i}"
            new_backup = log_file.parent / f"{log_file.name}.{i+1}"
            if old_backup.exists():
                old_backup.rename(new_backup)
                print(f"📦 Renommé: {old_backup.name} → {new_backup.name}")
        
        # Créer le nouveau backup .1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = log_file.parent / f"{log_file.name}.1"
        log_file.rename(backup_name)
        print(f"💾 Sauvegardé: {log_file.name} → {backup_name.name}")
        
        # Créer un nouveau fichier vide
        log_file.touch()
        print(f"✅ Nouveau fichier créé: {log_file.name}")
    else:
        print(f"✅ Pas de rotation nécessaire (< {max_lines} lignes)")

def cleanup_old_backups(log_dir, days_to_keep=7):
    """
    Nettoie les anciens fichiers de backup
    
    Args:
        log_dir: Dossier des logs
        days_to_keep: Nombre de jours à conserver
    """
    from datetime import datetime, timedelta
    
    log_dir = Path(log_dir)
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    cutoff_timestamp = cutoff_date.timestamp()
    
    cleaned = []
    
    # Supprimer les fichiers .log.N plus vieux que X jours
    for backup_file in log_dir.glob('app.log.*'):
        try:
            if backup_file.stat().st_mtime < cutoff_timestamp:
                backup_file.unlink()
                cleaned.append(backup_file.name)
        except Exception as e:
            print(f"⚠️  Erreur lors de la suppression de {backup_file.name}: {e}")
    
    if cleaned:
        print(f"🗑️  Supprimé {len(cleaned)} fichier(s) de backup de plus de {days_to_keep} jours")
        for filename in cleaned:
            print(f"   - {filename}")
    else:
        print(f"✅ Pas de fichiers à nettoyer (< {days_to_keep} jours)")

if __name__ == '__main__':
    # Chemin vers le fichier app.log
    log_file = Path(__file__).parent.parent / 'logs' / 'app.log'
    log_dir = log_file.parent
    
    print("=" * 60)
    print("🔄 Rotation des logs app.log")
    print("=" * 60)
    
    # Rotation basée sur le nombre de lignes
    rotate_app_log(log_file, max_lines=10000, backup_count=7)
    
    print("\n" + "=" * 60)
    print("🧹 Nettoyage des anciens backups")
    print("=" * 60)
    
    # Nettoyage des anciens backups
    cleanup_old_backups(log_dir, days_to_keep=7)
    
    print("\n✅ Terminé")

