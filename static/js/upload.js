/**
 * Gestion de l'upload de fichiers avec drag & drop
 * Zone d'upload améliorée avec feedback visuel
 */

// Variables globales pour l'upload
let uploadZone = null;
let fileInput = null;
let currentFile = null;

/**
 * Initialisation de la zone d'upload
 */
document.addEventListener('DOMContentLoaded', function() {
    uploadZone = document.getElementById('upload-zone');
    fileInput = document.getElementById('wp_migrate_archive');
    
    if (uploadZone && fileInput) {
        setupUploadZone();
    }
});

/**
 * Configuration de la zone d'upload
 */
function setupUploadZone() {
    // Événements de la zone d'upload
    uploadZone.addEventListener('click', () => fileInput.click());
    uploadZone.addEventListener('dragover', handleDragOver);
    uploadZone.addEventListener('dragleave', handleDragLeave);
    uploadZone.addEventListener('drop', handleDrop);
    
    // Événements de l'input file
    fileInput.addEventListener('change', handleFileSelect);
    
    // Empêcher les comportements par défaut du navigateur
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.addEventListener(eventName, preventDefaults, false);
    });
}

/**
 * Empêche les comportements par défaut
 * @param {Event} e - Événement
 */
function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

/**
 * Gère l'événement dragover
 * @param {Event} e - Événement
 */
function handleDragOver(e) {
    e.preventDefault();
    uploadZone.classList.add('dragover');
    
    // Vérifier le type de fichier pendant le drag
    const items = e.dataTransfer.items;
    if (items && items.length > 0) {
        const file = items[0];
        if (!isValidFileType(file.type)) {
            e.dataTransfer.dropEffect = 'none';
            showUploadError('Type de fichier non supporté');
        } else {
            e.dataTransfer.dropEffect = 'copy';
            clearUploadError();
        }
    }
}

/**
 * Gère l'événement dragleave
 * @param {Event} e - Événement
 */
function handleDragLeave(e) {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    clearUploadError();
}

/**
 * Gère l'événement drop
 * @param {Event} e - Événement
 */
function handleDrop(e) {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
        handleFileSelection(files[0]);
    }
}

/**
 * Gère la sélection de fichier via l'input
 * @param {Event} e - Événement
 */
function handleFileSelect(e) {
    const files = e.target.files;
    if (files && files.length > 0) {
        handleFileSelection(files[0]);
    }
}

/**
 * Traite la sélection d'un fichier
 * @param {File} file - Fichier sélectionné
 */
function handleFileSelection(file) {
    // Validation du fichier
    if (!validateFile(file)) {
        return;
    }
    
    // Stocker le fichier courant
    currentFile = file;
    
    // Afficher les informations du fichier
    displayFileInfo(file);
    
    // Simuler un upload pour le feedback visuel
    simulateUpload();
}

/**
 * Valide un fichier
 * @param {File} file - Fichier à valider
 * @returns {boolean} - Validité du fichier
 */
function validateFile(file) {
    // Vérifier le type
    if (!isValidFileType(file.type, file.name)) {
        showUploadError('Type de fichier non supporté. Utilisez ZIP, SQL ou GZ.');
        return false;
    }
    
    // Vérifier la taille (5GB max)
    const maxSize = 5 * 1024 * 1024 * 1024; // 5GB
    if (file.size > maxSize) {
        showUploadError('Fichier trop volumineux. Maximum 5GB.');
        return false;
    }
    
    clearUploadError();
    return true;
}

/**
 * Vérifie si le type de fichier est valide
 * @param {string} type - Type MIME
 * @param {string} name - Nom du fichier
 * @returns {boolean} - Validité du type
 */
function isValidFileType(type, name = '') {
    const validTypes = [
        'application/zip',
        'application/x-zip-compressed',
        'application/sql',
        'application/x-sql',
        'text/sql',
        'application/gzip',
        'application/x-gzip'
    ];
    
    const validExtensions = ['.zip', '.sql', '.gz'];
    
    // Vérifier le type MIME
    if (validTypes.includes(type)) {
        return true;
    }
    
    // Vérifier l'extension si le type MIME n'est pas reconnu
    if (name) {
        const extension = '.' + name.split('.').pop().toLowerCase();
        return validExtensions.includes(extension);
    }
    
    return false;
}

/**
 * Affiche les informations du fichier sélectionné
 * @param {File} file - Fichier sélectionné
 */
function displayFileInfo(file) {
    const uploadContent = uploadZone.querySelector('.upload-content');
    const fileInfo = uploadZone.querySelector('.upload-file-info');
    const fileName = fileInfo.querySelector('.file-name');
    
    if (uploadContent && fileInfo && fileName) {
        // Cacher le contenu de base et afficher les infos du fichier
        uploadContent.classList.add('d-none');
        fileInfo.classList.remove('d-none');
        
        // Afficher le nom et la taille du fichier
        fileName.innerHTML = `
            <strong>${escapeHtml(file.name)}</strong><br>
            <small class="text-light">${formatFileSize(file.size)}</small>
        `;
        
        // Changer l'apparence de la zone d'upload
        uploadZone.classList.add('file-selected');
    }
}

/**
 * Simule un upload pour le feedback visuel
 */
function simulateUpload() {
    uploadZone.classList.add('uploading');
    
    // Retirer l'animation après 2 secondes
    setTimeout(() => {
        uploadZone.classList.remove('uploading');
        uploadZone.classList.add('upload-complete');
    }, 2000);
}

/**
 * Efface le fichier sélectionné
 */
function clearFile() {
    const uploadContent = uploadZone.querySelector('.upload-content');
    const fileInfo = uploadZone.querySelector('.upload-file-info');
    
    // Réinitialiser l'input
    fileInput.value = '';
    currentFile = null;
    
    // Réinitialiser l'affichage
    if (uploadContent && fileInfo) {
        uploadContent.classList.remove('d-none');
        fileInfo.classList.add('d-none');
    }
    
    // Réinitialiser les classes de la zone
    uploadZone.classList.remove('file-selected', 'uploading', 'upload-complete');
    
    clearUploadError();
}

/**
 * Affiche une erreur d'upload
 * @param {string} message - Message d'erreur
 */
function showUploadError(message) {
    let errorElement = uploadZone.querySelector('.upload-error');
    
    if (!errorElement) {
        errorElement = document.createElement('div');
        errorElement.className = 'upload-error alert alert-danger mt-2 mb-0';
        uploadZone.appendChild(errorElement);
    }
    
    errorElement.innerHTML = `
        <i class="fas fa-exclamation-triangle me-2"></i>
        ${escapeHtml(message)}
    `;
    errorElement.style.display = 'block';
    
    // Ajouter une classe d'erreur à la zone
    uploadZone.classList.add('upload-error-state');
}

/**
 * Efface les erreurs d'upload
 */
function clearUploadError() {
    const errorElement = uploadZone.querySelector('.upload-error');
    if (errorElement) {
        errorElement.style.display = 'none';
    }
    
    uploadZone.classList.remove('upload-error-state');
}

/**
 * Réinitialise complètement la zone d'upload
 */
function resetUploadZone() {
    clearFile();
    clearUploadError();
    uploadZone.classList.remove('dragover', 'file-selected', 'uploading', 'upload-complete', 'upload-error-state');
}

/**
 * Gère l'upload de fichier avec progress (pour les futures implémentations)
 * @param {File} file - Fichier à uploader
 * @param {Function} onProgress - Callback de progression
 * @param {Function} onComplete - Callback de completion
 * @param {Function} onError - Callback d'erreur
 */
function uploadFileWithProgress(file, onProgress, onComplete, onError) {
    const formData = new FormData();
    formData.append('file', file);
    
    const xhr = new XMLHttpRequest();
    
    // Gestion de la progression
    xhr.upload.addEventListener('progress', function(e) {
        if (e.lengthComputable) {
            const percentComplete = (e.loaded / e.total) * 100;
            if (onProgress) onProgress(percentComplete);
        }
    });
    
    // Gestion de la completion
    xhr.addEventListener('load', function() {
        if (xhr.status === 200) {
            if (onComplete) onComplete(xhr.responseText);
        } else {
            if (onError) onError(`Erreur HTTP: ${xhr.status}`);
        }
    });
    
    // Gestion des erreurs
    xhr.addEventListener('error', function() {
        if (onError) onError('Erreur réseau lors de l\'upload');
    });
    
    // Lancer l'upload
    xhr.open('POST', '/upload_endpoint'); // À adapter selon le endpoint
    xhr.send(formData);
}

/**
 * Prévisualise un fichier SQL (si c'est un fichier texte)
 * @param {File} file - Fichier à prévisualiser
 */
function previewSqlFile(file) {
    if (!file.name.toLowerCase().endsWith('.sql')) {
        return;
    }
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const content = e.target.result;
        const lines = content.split('\n').slice(0, 10); // Premières 10 lignes
        
        // Créer un élément de prévisualisation
        const preview = document.createElement('div');
        preview.className = 'sql-preview mt-2 p-2 bg-dark border rounded';
        preview.innerHTML = `
            <small class="text-muted d-block mb-1">Aperçu du fichier SQL:</small>
            <pre class="mb-0"><code>${escapeHtml(lines.join('\n'))}</code></pre>
            ${content.split('\n').length > 10 ? '<small class="text-muted">...</small>' : ''}
        `;
        
        // Ajouter à la zone d'upload
        const existingPreview = uploadZone.querySelector('.sql-preview');
        if (existingPreview) {
            existingPreview.remove();
        }
        uploadZone.appendChild(preview);
    };
    
    // Lire seulement les premiers KB pour la prévisualisation
    const blob = file.slice(0, 2048);
    reader.readAsText(blob);
}

// Styles CSS additionnels injectés dynamiquement
const uploadStyles = `
<style>
.upload-zone.file-selected {
    border-color: #28a745;
    background-color: #e7f3ff;
}

.upload-zone.upload-complete {
    border-color: #28a745;
    border-style: solid;
    background-color: #d4edda;
}

.upload-zone.upload-error-state {
    border-color: #dc3545;
    border-style: solid;
    background-color: #f8d7da;
}

.upload-error {
    margin-top: 1rem;
    margin-bottom: 0;
    font-size: 0.875rem;
}

.sql-preview {
    max-height: 150px;
    overflow-y: auto;
    font-size: 0.75rem;
    line-height: 1.2;
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
}

.sql-preview code {
    color: #495057;
    background: none;
}

@media (max-width: 576px) {
    .upload-zone {
        padding: 1rem;
    }
    
    .upload-file-info {
        flex-direction: column;
        text-align: center;
    }
    
    .upload-file-info .file-name {
        margin-bottom: 0.5rem;
    }
}
</style>
`;

// Injecter les styles
document.head.insertAdjacentHTML('beforeend', uploadStyles); 