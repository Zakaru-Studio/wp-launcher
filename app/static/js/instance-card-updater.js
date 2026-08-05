/**
 * Instance Card Updater
 * Fonctions pour mettre à jour le project-item avec les données d'une instance
 */

// Mettre à jour le project-item pour afficher une instance dev (fonction globale)
window.updateProjectCardForInstance = function(projectName, instance, status) {
    const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
    if (!projectCard) {
        console.error(`Project card not found for ${projectName}`);
        return;
    }
    
    console.log(`Mise à jour de l'UI pour l'instance ${instance.name}, statut: ${status}, port: ${instance.port}`);
    
    // Marquer l'instance active
    projectCard.dataset.currentInstance = instance.name;
    projectCard.dataset.isDevInstance = 'true';
    
    // 1. Mettre à jour le port dans le header du project-item
    const projectHeader = projectCard.querySelector('.project-header');
    if (projectHeader) {
        const portLink = projectHeader.querySelector('.project-ip-port a');
        if (portLink) {
            portLink.href = getProjectUrl(instance.port);
            const iconEl = document.createElement('i');
            iconEl.className = 'fas fa-external-link-alt me-1';
            portLink.replaceChildren(
                iconEl,
                document.createTextNode(' ' + window.APP_CONFIG.host + ':' + instance.port)
            );
            console.log(`Port mis à jour dans le header: ${instance.port}`);
        }
    }
    
    // 1b. Mettre à jour UNIQUEMENT le port du service WordPress (pas phpMyAdmin ni Mailpit)
    const serviceCards = projectCard.querySelectorAll('.service-card');
    serviceCards.forEach(card => {
        const serviceLink = card.querySelector('.service-link');
        const servicePort = card.querySelector('.service-port');
        const serviceName = card.querySelector('.service-name');
        
        if (serviceLink && servicePort && serviceName) {
            const name = serviceName.textContent.trim();
            // UNIQUEMENT pour WordPress
            if (name === 'WordPress') {
                serviceLink.href = getProjectUrl(instance.port);
                servicePort.textContent = `:${instance.port}`;
                console.log(`Port WordPress service mis à jour: ${instance.port}`);
            }
            // Ne PAS toucher à phpMyAdmin et Mailpit - ils gardent leurs ports originaux
        }
    });
    
    // 2. Mettre à jour le bouton Running/Stopped (identique à l'instance principale)
    const statusBtn = projectCard.querySelector('.btn-running, .btn-start, .btn-stopped');
    if (statusBtn) {
        if (status === 'running') {
            statusBtn.className = 'btn-modern btn-running';
            statusBtn.innerHTML = 'Running\n                            <i class="fas fa-stop me-1"></i>';
            statusBtn.setAttribute('onclick', `stopProject('${instance.name}')`);
            statusBtn.setAttribute('title', 'Arrêter le projet');
        } else {
            statusBtn.className = 'btn-modern btn-start';
            statusBtn.innerHTML = 'Start\n                            <i class="fas fa-play me-1"></i>';
            statusBtn.setAttribute('onclick', `startProject('${instance.name}')`);
            statusBtn.setAttribute('title', 'Démarrer le projet');
        }
    }
    
    // 3. phpMyAdmin et Mailpit gardent leurs ports originaux du parent
    // Les instances partagent le même MySQL et Mailpit que le parent
    // Le code de la section 1b a déjà géré la mise à jour du port WordPress uniquement
    console.log('phpMyAdmin et Mailpit conservent leurs ports originaux du parent');
    
    // 4. Désactiver les boutons de configuration PHP/MySQL (instance dev ne peut pas modifier ces configs)
    const configButtons = projectCard.querySelectorAll('.btn-config');
    configButtons.forEach(btn => {
        const onclick = btn.getAttribute('onclick');
        if (onclick && (onclick.includes('openPhpConfigModal') || onclick.includes('openMysqlConfigModal'))) {
            btn.style.opacity = '0.3';
            btn.style.pointerEvents = 'none';
            btn.style.cursor = 'not-allowed';
            btn.setAttribute('data-original-title', btn.getAttribute('title'));
            btn.setAttribute('title', 'Configuration disponible uniquement pour l\'instance principale');
            console.log('Bouton de configuration désactivé:', onclick);
        }
    });
    
    // 5. Mettre à jour toutes les commandes pour utiliser le nom de l'instance
    window.updateCommandsMenu(projectCard, instance.name, true);
    
    // 6. Signaler l'instance active sur la ligne du site.
    // Le sélecteur est passé dans le menu « … » ; sans cette pastille, plus
    // rien n'indiquerait que les ports affichés sont ceux d'une instance dev.
    const chip = projectCard.querySelector('.instance-chip');
    if (chip) {
        const isOwnInstance = instance.owner_username === window.instancesUIManager.currentUser;
        chip.textContent = isOwnInstance ? 'Mon instance dev' : `Instance de ${instance.owner_username}`;
        chip.hidden = false;
    }
}

// Restaurer l'instance principale (fonction globale)
window.restoreMainInstanceCard = function(projectName) {
    const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
    if (!projectCard) return;
    
    // Réinitialiser les data attributes
    projectCard.dataset.currentInstance = '';
    projectCard.dataset.isDevInstance = 'false';
    
    // Récupérer les ports originaux
    const originalPorts = {
        wordpress: projectCard.dataset.portWordpress,
        phpmyadmin: projectCard.dataset.portPhpmyadmin,
        mailpit: projectCard.dataset.portMailpit
    };
    
    // Restaurer le port dans le header
    const portLink = projectCard.querySelector('.project-ip-port a');
    if (portLink) {
        portLink.href = getProjectUrl(originalPorts.wordpress);
        const iconEl = document.createElement('i');
        iconEl.className = 'fas fa-external-link-alt me-1';
        portLink.replaceChildren(
            iconEl,
            document.createTextNode(' ' + window.APP_CONFIG.host + ':' + originalPorts.wordpress)
        );
    }

    // Restaurer le lien WordPress
    const wpLink = projectCard.querySelector('.btn-primary[title*="WordPress"]');
    if (wpLink) {
        wpLink.href = getProjectUrl(originalPorts.wordpress);
    }

    // Réactiver phpMyAdmin et Mailpit
    const pmaLink = projectCard.querySelector('.btn-info[title*="phpMyAdmin"]');
    if (pmaLink) {
        pmaLink.href = getProjectUrl(originalPorts.phpmyadmin);
        pmaLink.style.opacity = '1';
        pmaLink.style.pointerEvents = 'auto';
        pmaLink.title = 'Ouvrir phpMyAdmin';
    }
    
    const mailpitLink = projectCard.querySelector('.btn-warning[title*="Mailpit"]');
    if (mailpitLink) {
        mailpitLink.href = getProjectUrl(originalPorts.mailpit);
        mailpitLink.style.opacity = '1';
        mailpitLink.style.pointerEvents = 'auto';
        mailpitLink.title = 'Ouvrir Mailpit';
    }
    
    // Réactiver les boutons de configuration PHP/MySQL
    const configButtons = projectCard.querySelectorAll('.btn-config');
    configButtons.forEach(btn => {
        const onclick = btn.getAttribute('onclick');
        if (onclick && (onclick.includes('openPhpConfigModal') || onclick.includes('openMysqlConfigModal'))) {
            btn.style.opacity = '';
            btn.style.pointerEvents = '';
            btn.style.cursor = '';
            const originalTitle = btn.getAttribute('data-original-title');
            if (originalTitle) {
                btn.setAttribute('title', originalTitle);
                btn.removeAttribute('data-original-title');
            }
            console.log('Bouton de configuration réactivé:', onclick);
        }
    });
    
    // Restaurer les commandes pour utiliser le nom du projet
    updateCommandsMenu(projectCard, projectName, false);
    
    // Retour à l'instance principale : la pastille n'a plus lieu d'être.
    // (Pas de libellé « Instance principale » : c'est le cas nominal, et une
    // pastille permanente sur chaque ligne serait du bruit.)
    const chip = projectCard.querySelector('.instance-chip');
    if (chip) {
        chip.hidden = true;
        chip.textContent = '';
    }
    
    // Restaurer le port dans les services
    const serviceCards = projectCard.querySelectorAll('.service-card');
    serviceCards.forEach(card => {
        const serviceLink = card.querySelector('.service-link');
        const servicePort = card.querySelector('.service-port');
        
        if (serviceLink && servicePort) {
            // WordPress service - restaurer le port original
            if (!serviceLink.href.includes('phpmyadmin') && !serviceLink.href.includes('mailpit')) {
                const originalPort = originalPorts.wordpress;
                serviceLink.href = getProjectUrl(originalPort);
                servicePort.textContent = `:${originalPort}`;
            }
        }
    });
}

