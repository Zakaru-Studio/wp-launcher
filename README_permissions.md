# 🔑 Gestion des Permissions - WordPress Launcher

## ✅ Problème résolu automatiquement

Depuis la mise à jour, WordPress Launcher gère automatiquement les permissions pour que **dev-server** puisse modifier tous les fichiers via SSH/Cursor.

## 🚀 Corrections automatiques

### 1. **Création de nouveaux projets**
- Les permissions sont automatiquement configurées lors de la création
- `dev-server:dev-server` propriétaire de tous les fichiers
- Permissions `755` pour les dossiers, `644` pour les fichiers

### 2. **Démarrage des projets**
- Les permissions sont automatiquement corrigées après le démarrage des conteneurs
- Empêche les problèmes causés par les fichiers créés par les conteneurs Docker

## 🛠️ Correction manuelle (si nécessaire)

Si vous rencontrez encore des problèmes de permissions, utilisez le script de correction :

```bash
cd /home/dev-server/Sites/wp-launcher
./fix_permissions.sh
```

## 🔍 Vérification des permissions

Pour vérifier les permissions d'un projet :

```bash
ls -la projets/[nom-du-projet]/
ls -la projets/[nom-du-projet]/wp-content/
```

Vous devriez voir **dev-server dev-server** comme propriétaire.

## ⚙️ Fonctionnement technique

### Problème initial
Les conteneurs Docker créent parfois des fichiers avec l'utilisateur `www-data` au lieu de `dev-server`, ce qui empêche l'édition via SSH.

### Solution automatique
1. **À la création** : Permissions définies pour `dev-server`
2. **Au démarrage** : Correction automatique après 3 secondes
3. **Script de secours** : `fix_permissions.sh` disponible

### Permissions appliquées
- **Propriétaire** : `dev-server:dev-server`
- **Dossiers** : `755` (rwxr-xr-x)
- **Fichiers** : `644` (rw-r--r--)
- **Uploads** : `775` (rwxrwxr-x) pour WordPress

## 🎯 Avantages

✅ **Édition libre** : Modifiez tous les fichiers via Cursor/SSH  
✅ **Automatique** : Plus besoin de corriger manuellement  
✅ **WordPress compatible** : Permissions optimales pour WordPress  
✅ **Sécurisé** : Permissions minimales nécessaires  

## 🆘 En cas de problème

Si vous ne pouvez toujours pas éditer un fichier après `fix_permissions.sh` :

1. Vérifiez que vous êtes connecté en tant que **dev-server**
2. Redémarrez votre session SSH
3. Contactez l'administrateur si le problème persiste

---

*WordPress Launcher - Permissions automatiques configurées* ✨ 