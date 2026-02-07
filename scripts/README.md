# Scripts WordPress Launcher

Ce dossier contient les scripts shell utilisés par l'application WordPress Launcher.

## Scripts disponibles

### 🚀 Gestion de l'application

- **`start.sh`** - Démarre l'application Flask
  - Vérifie les prérequis (Python, Docker, dépendances)
  - Active l'environnement virtuel
  - Lance l'application
  - Utilisé par : systemd service (`wp-launcher.service`)

- **`restart_app.sh`** - Redémarre l'application
  - Arrête les processus existants
  - Nettoie les caches Python
  - Relance l'application en arrière-plan
  - Utilisé par : Interface web (bouton de redémarrage)

- **`stop_app.sh`** - Arrête l'application
  - Termine proprement tous les processus Python
  - Libère le port 5000

### 💾 Backups automatiques

- **`backup_databases.sh`** - Backup automatique des bases de données
  - Sauvegarde MySQL et MongoDB
  - Compression automatique
  - Rotation des backups (7 jours de rétention)
  - Utilisé par : Cron (toutes les 4 heures) + Interface de monitoring

### 🗑️ Suppression sécurisée

- **`delete_project_folders.sh`** - Suppression sécurisée des projets
  - Supprime les dossiers projets/ et containers/
  - Gestion des permissions avec sudo
  - Protection contre les path traversal
  - Validation du nom de projet
  - Utilisé par : ProjectService lors de la suppression de projets

## Usage

### Démarrer l'application
```bash
./scripts/start.sh
```

### Redémarrer l'application
```bash
./scripts/restart_app.sh
```

### Arrêter l'application
```bash
./scripts/stop_app.sh
```

### Lancer un backup manuel
```bash
./scripts/backup_databases.sh
```

### Tester le système de backup
```bash
./scripts/backup_databases.sh test
```

## Configuration

### Cron (backups automatiques)
Les backups sont configurés pour s'exécuter automatiquement :
```cron
0 */4 * * * /home/dev-server/Sites/wp-launcher/scripts/backup_databases.sh
```

### Systemd Service
Le service systemd utilise `start.sh` :
```ini
ExecStart=/home/dev-server/Sites/wp-launcher/scripts/start.sh
```

## Notes

- Tous les scripts doivent être exécutables (`chmod +x`)
- Les scripts sont conçus pour être exécutés depuis la racine du projet
- Les logs sont disponibles dans `/home/dev-server/Sites/wp-launcher/logs/`
  - `logs/app.log` : Logs principaux de l'application (rotation automatique)
  - `logs/wp_launcher.log` : Logs structurés des opérations
  - Sous-dossiers par type d'opération (create, delete, start, stop, etc.)

## 🔄 Gestion des logs

### Configuration de la rotation automatique

Le système de logs utilise une rotation automatique pour éviter l'accumulation de fichiers volumineux :

**Logs principaux (app.log)**
- **Limite** : 10 000 lignes par fichier
- **Conservation** : 7 fichiers backup (≈ 7 jours)
- **Rotation** : Automatique via cron (tous les jours à 3h00)
- **Fichiers créés** : `app.log`, `app.log.1`, `app.log.2`, ..., `app.log.7`

**Logs structurés (wp_launcher.log et sous-dossiers)**
- **Rotation** : Par taille (1 MB par fichier)
- **Conservation** : 7 fichiers backup
- **Nettoyage** : Fichiers de plus de 7 jours automatiquement supprimés

### Scripts de gestion

**`rotate_app_log.py`**
```bash
# Exécuter manuellement la rotation
cd /home/dev-server/Sites/wp-launcher
python3 scripts/rotate_app_log.py
```

**`setup_log_rotation_cron.sh`**
```bash
# Configurer la rotation automatique via crontab
./scripts/setup_log_rotation_cron.sh
```

### Consultation des logs

```bash
# Logs en temps réel
tail -f logs/app.log

# Dernières 100 lignes
tail -n 100 logs/app.log

# Chercher une erreur
grep -i error logs/app.log

# Voir tous les fichiers de logs
ls -lh logs/
```

### Nettoyage manuel

Si besoin de nettoyer manuellement les logs :

```bash
# Supprimer les logs de plus de 7 jours
find logs/ -name "*.log*" -mtime +7 -delete

# Vider le fichier app.log actuel
> logs/app.log
```

