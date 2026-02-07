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
                alert(`Instance créée avec succès!\nURL: ${getProjectUrl(data.instance.port)}`);
                this.loadUserInstances();
            } else {
                alert(`Erreur: ${data.error}`);
            }
        } catch (error) {
            alert(`Erreur: ${error.message}`);
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
                alert('Instance supprimée avec succès');
                this.loadUserInstances();
            }
        } catch (error) {
            alert(`Erreur: ${error.message}`);
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






