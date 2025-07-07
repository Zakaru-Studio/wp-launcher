# 🌐 Configuration Domaine Externe - WordPress Launcher

## ✅ Configuration déjà effectuée

✅ **nginx configuré** : Reverse proxy actif pour `eurasiapeace.akdigital.fr` → `192.168.1.21:8080`  
✅ **Test local réussi** : `curl -H 'Host: eurasiapeace.akdigital.fr' http://localhost` fonctionne  
✅ **Bouton domaine ajouté** : Interface WordPress Launcher mise à jour

---

## 📋 Étapes suivantes pour finaliser

### 1. 📡 Configuration DNS
**Chez votre registrar de domaine (où vous avez acheté akdigital.fr) :**

```dns
Type: A
Nom: eurasiapeace
Valeur: VOTRE_IP_PUBLIQUE
TTL: 300 (5 minutes)
```

**Pour trouver votre IP publique :**
```bash
curl -s ifconfig.me
# ou
curl -s ipinfo.io/ip
```

### 2. 🏠 Configuration Box Internet
**Dans l'interface de votre box :**

- **NAT/PAT** → **Redirection de ports**
- **Service** : Web Server (HTTP)
- **Port externe** : 80
- **IP interne** : 192.168.1.21
- **Port interne** : 80
- **Protocole** : TCP
- **Interface** : Toutes

### 3. 🧪 Tests de validation

**Test 1 - DNS propagé :**
```bash
nslookup eurasiapeace.akdigital.fr
# Doit retourner votre IP publique
```

**Test 2 - Accès externe :**
```bash
curl -I http://eurasiapeace.akdigital.fr
# Doit retourner HTTP/1.1 200 OK
```

**Test 3 - WordPress fonctionne :**
Ouvrir `http://eurasiapeace.akdigital.fr` dans un navigateur

---

## 🔐 Configuration HTTPS (optionnel mais recommandé)

**Une fois les étapes précédentes validées :**

```bash
./setup_https.sh eurasiapeace.akdigital.fr contact@akdigital.fr
```

**Cela va :**
- ✅ Installer Let's Encrypt
- ✅ Obtenir un certificat SSL gratuit
- ✅ Configurer le renouvellement automatique
- ✅ Rediriger HTTP → HTTPS

---

## 🛠️ Scripts disponibles

| Script | Usage | Description |
|--------|-------|-------------|
| `setup_domain.sh` | `./setup_domain.sh <domain> <project>` | Configure nginx |
| `setup_https.sh` | `./setup_https.sh <domain> <email>` | Configure SSL |

---

## 🔍 Dépannage

### Problème : "Site inaccessible"
1. Vérifier IP publique : `curl ifconfig.me`
2. Vérifier DNS : `nslookup eurasiapeace.akdigital.fr`
3. Vérifier redirection box : Panneau admin box
4. Vérifier nginx : `sudo nginx -t && sudo systemctl status nginx`

### Problème : "Erreur SSL"
1. Attendre propagation DNS (5-15 minutes)
2. Relancer : `./setup_https.sh eurasiapeace.akdigital.fr contact@akdigital.fr`

### Problème : "Page WordPress cassée"
1. Vérifier conteneur : `docker ps | grep eurasiapeace`
2. Vérifier logs : `docker logs eurasiapeace_wordpress_1`

---

## 📱 Interface WordPress Launcher

**Nouveau bouton "Domaine" dans chaque projet WordPress :**
- Configure automatiquement un domaine externe
- Génère les instructions de configuration
- Sauvegarde la configuration dans `.external_domain`

---

## 🎯 Configuration actuelle

| Paramètre | Valeur |
|-----------|--------|
| **Domaine** | eurasiapeace.akdigital.fr |
| **Projet** | eurasiapeace |
| **Port WordPress** | 8080 |
| **IP Docker** | 192.168.1.21 |
| **Config nginx** | `/etc/nginx/sites-available/eurasiapeace.akdigital.fr` |

---

## ⚡ Actions immédiates

1. **Configurer DNS** : Pointer `eurasiapeace.akdigital.fr` vers votre IP publique
2. **Vérifier box** : Redirection port 80 → 192.168.1.21:80
3. **Tester** : Ouvrir http://eurasiapeace.akdigital.fr
4. **Optionnel** : Configurer HTTPS avec `./setup_https.sh`

**Une fois ces étapes effectuées, votre site WordPress sera accessible depuis Internet via eurasiapeace.akdigital.fr ! 🚀** 