# 🔍 **Diagnostic : Problème de redirection vers le port 8080**

## 📋 **Problème rapporté**

> "Lorsque je clique sur les liens des sites (ex. http://192.168.1.21:8087) ou sur le bouton 'Site', je suis redirigé vers http://192.168.1.21:8080/"

---

## ✅ **Vérifications effectuées**

### 1. **API Backend** ✅ **CORRECT**
```bash
# Test : curl -s http://localhost:5000/projects_with_status
{
  "projects": [
    {
      "name": "nonasolution",
      "port": 8087,    ← BON PORT
      "pma_port": 8090,
      "status": "active"
    },
    {
      "name": "eurasiapeace",
      "port": 8080,    ← BON PORT
      "pma_port": 8082,
      "status": "active"
    }
  ]
}
```

### 2. **Configuration des ports** ✅ **CORRECT**
```bash
# Fichiers de configuration des ports :
containers/eurasiapeace/.port = 8080     ✅
containers/nonasolution/.port = 8087     ✅ 
containers/eurasiapeace/.pma_port = 8082 ✅
containers/nonasolution/.pma_port = 8090 ✅
```

### 3. **Code JavaScript frontend** ✅ **CORRECT**
```javascript
// Génération des liens dynamiques :
action: `window.open('http://192.168.1.21:${project.port}', '_blank')`
url: `http://192.168.1.21:${project.port}`

// Pour nonasolution : project.port = 8087 ✅
// Pour eurasiapeace : project.port = 8080 ✅
```

### 4. **Configuration WordPress** ✅ **CORRECT**
```sql
-- Base de données nonasolution :
SELECT option_name, option_value FROM wp_options 
WHERE option_name IN ('home', 'siteurl');
+-------------+---------------------------+
| option_name | option_value              |
+-------------+---------------------------+
| home        | http://192.168.1.21:8087  |
| siteurl     | http://192.168.1.21:8087  |
+-------------+---------------------------+
```

### 5. **wp-config.php** ✅ **CORRECT**
```php
// projets/nonasolution/wp-config.php :
define('WP_HOME', 'http://192.168.1.21:8087');
define('WP_SITEURL', 'http://192.168.1.21:8087');
```

### 6. **Réponse serveur** ✅ **CORRECT**
```bash
# Test direct du port :
curl -s -I http://192.168.1.21:8087 | head -5
HTTP/1.1 200 OK                               ✅
Server: Apache/2.4.62 (Debian)
X-Powered-By: PHP/8.2.29
Link: <http://192.168.1.21:8087/wp-json/>;    ✅ Bon port dans les headers
```

---

## 🤔 **Causes possibles**

### 1. **Cache navigateur** 🔍 **PROBABLE**
- Anciennes redirections mises en cache
- **Solution** : Ctrl+F5 ou navigation privée

### 2. **Extensions navigateur** 🔍 **POSSIBLE**
- Proxy ou redirecteur automatique
- **Solution** : Désactiver extensions temporairement

### 3. **Configuration réseau** 🔍 **POSSIBLE**
- Proxy local ou entreprise
- Règles iptables/firewall
- **Solution** : Vérifier configuration réseau

### 4. **WordPress interne** 🔍 **RARE**
- Redirection via .htaccess ou plugin
- Canonical URL forcée par thème
- **Solution** : Vérifier .htaccess et plugins

---

## 🛠️ **Solutions de dépannage**

### **Test 1 : Page de diagnostic**
```bash
# Accéder à :
http://192.168.1.21:5000/debug

# Cette page teste :
- API /projects_with_status en direct
- Génération des liens JavaScript
- Tests window.open() individuels
```

### **Test 2 : Navigation privée**
```
1. Ouvrir une fenêtre de navigation privée
2. Aller sur http://192.168.1.21:5000
3. Tester les liens des projets
4. Voir si le problème persiste
```

### **Test 3 : Console développeur**
```
F12 → Console → Voir les logs JavaScript
1. Clic sur bouton "Site" de nonasolution
2. Vérifier l'URL générée dans les logs
3. Voir si redirection apparaît dans Network
```

### **Test 4 : Accès direct**
```bash
# Tester directement dans la barre d'adresse :
http://192.168.1.21:8087  # nonasolution
http://192.168.1.21:8080  # eurasiapeace
http://192.168.1.21:8085  # eurasiapeace Next.js
```

### **Test 5 : Différents navigateurs**
```
1. Tester avec Firefox
2. Tester avec Chrome/Chromium  
3. Tester avec mobile (même réseau WiFi)
```

---

## ⚡ **Actions immédiates**

### 1. **Vider cache navigateur**
```
Ctrl + Shift + Suppr (Chrome/Firefox)
- Cocher "Images et fichiers en cache"
- Cocher "Cookies et données de sites"
- Choisir "Dernière heure" ou "Tout"
```

### 2. **Test navigation privée**
```
Ctrl + Shift + N (Chrome)
Ctrl + Shift + P (Firefox)
```

### 3. **Tester page debug**
```bash
# URL directe : http://192.168.1.21:5000/debug
# Tests automatiques des liens et APIs
# Comparaison avec interface normale
```

---

## 📊 **État actuel du système**

### **Sites configurés :**
```
✅ nonasolution   : WordPress 8087, phpMyAdmin 8090
✅ eurasiapeace   : WordPress 8080, Next.js 8085, phpMyAdmin 8082
✅ Configuration  : Tous les ports corrects
✅ API Backend    : Données exactes transmises
✅ Code Frontend  : Génération dynamique des liens
```

### **Scripts de test disponibles :**
```bash
./show_sites.sh              # Affiche tous les sites et ports
http://IP:5000/debug          # Page de diagnostic web
curl /projects_with_status    # Test API direct
```

---

## 🎯 **Hypothèse principale**

Le problème est très probablement lié au **cache du navigateur** qui garde en mémoire d'anciennes redirections de l'époque où nginx était configuré avec des domaines.

**Solution recommandée :**
1. ✅ Vider complètement le cache navigateur
2. ✅ Tester en navigation privée
3. ✅ Utiliser la page de debug : http://192.168.1.21:5000/debug

---

**Le système est techniquement correct - le problème est probablement côté client/navigateur ! 🚀** 