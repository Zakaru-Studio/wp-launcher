/**
 * Dev Instances Manager
 * Gestion des instances de développement
 */

class DevInstancesManager {
    constructor() {
        this.currentUser = document.body.dataset.currentUser || '';
        this.currentRole = document.body.dataset.currentRole || '';
        this.init();
    }
    
    init() {
        console.log('DevInstancesManager initialized');
        // Auto-load instances on page load
        if (this.currentUser) {
            this.loadUserInstances();
        }
    }
    
    async loadUserInstances() {
        try {
            const response = await fetch('/api/dev-instances/list');
            const data = await response.json();
            if (data.success) {
                this.instances = data.instances;
                this.updateInstancesUI();
            }
        } catch (error) {
            console.error('Error loading instances:', error);
        }
    }
    
    async loadProjectInstances(projectName) {
        try {
            const response = await fetch(`/api/dev-instances/by-project/${projectName}`);
            const data = await response.json();
            if (data.success) {
                return data.instances;
            }
        } catch (error) {
            console.error('Error loading project instances:', error);
        }
        return [];
    }
    
    async createInstance(parentProject) {
        if (!confirm(`Créer une instance de développement de "${parentProject}" ?`)) {
            return;
        }
        
        try {
            const response = await fetch('/api/dev-instances/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ parent_project: parentProject })
            });
            
            const data = await response.json();
            if (data.success) {
                // La progression et le succès s'affichent dans le toaster
                // (événements socket task_start / task_complete).
                this.loadUserInstances();
            } else {
                this._toast('error', `Création de l'instance : ${data.error}`);
            }
        } catch (error) {
            this._toast('error', `Création de l'instance : ${error.message}`);
        }
    }

    async deleteInstance(instanceName) {
        if (!confirm(`Supprimer l'instance "${instanceName}" ?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/dev-instances/${instanceName}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.loadUserInstances();
            } else {
                const data = await response.json().catch(() => ({}));
                this._toast('error', `Suppression de l'instance : ${data.error || 'Erreur inconnue'}`);
            }
        } catch (error) {
            this._toast('error', `Suppression de l'instance : ${error.message}`);
        }
    }

    _toast(type, message) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            alert(message);
        }
    }
    
    switchToInstance(instanceName, port) {
        window.open(getProjectUrl(port), '_blank');
    }
    
    updateInstancesUI() {
        // This would update the UI with instance badges/dropdowns
        console.log('Updating instances UI:', this.instances);
    }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    if (document.body.dataset.currentUser) {
        window.devInstancesManager = new DevInstancesManager();
    }
});






