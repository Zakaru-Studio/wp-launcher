/**
 * ========================================
 * SONNER — montage du toaster
 * ========================================
 *
 * Sonner est une librairie React ; l'app est en JS vanille. On monte donc un
 * unique <Toaster /> dans un nœud dédié, et on expose l'API impérative
 * `toast()` sur `window.sonnerToast` — c'est le seul point de contact avec le
 * reste du code, qui n'a pas à savoir que du React tourne en dessous.
 *
 * React, ReactDOM et Sonner sont vendorisés dans static/vendor/sonner/ plutôt
 * que tirés d'un CDN : les notifications sont le canal qui annonce l'échec
 * d'une opération, il ne doit pas dépendre d'un réseau qui peut justement
 * être ce qui est cassé.
 *
 * Consommation : toast-notifications.js. Ne pas appeler window.sonnerToast
 * directement ailleurs — showToast/showSuccess/... gèrent la déduplication
 * et la répartition avec le centre de notifications.
 */

import React from '../vendor/sonner/react.mjs';
import { createRoot } from '../vendor/sonner/react-dom-client.mjs';
import { Toaster, toast } from '../vendor/sonner/sonner.mjs';

const host = document.createElement('div');
host.id = 'sonner-host';
document.body.appendChild(host);

const root = createRoot(host);

/** Le thème vit sur <html data-theme>, posé avant le rendu par base.html. */
function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

let announced = false;

/**
 * Signale que le toaster est opérationnel.
 *
 * Monté dans un effet et non juste après `root.render()` : le rendu de React
 * 18 est asynchrone, et sonner perd tout `toast()` émis avant que le Toaster
 * ne se soit abonné à son store. Les effets des enfants étant vidés avant
 * ceux du parent, cet effet-ci garantit que l'abonnement a bien eu lieu.
 */
function ToasterReady(props) {
    React.useEffect(() => {
        if (announced) return;
        announced = true;
        window.sonnerToast = toast;
        document.dispatchEvent(new CustomEvent('sonner:ready'));
    }, []);
    return React.createElement(Toaster, props);
}

function render() {
    root.render(React.createElement(ToasterReady, {
        theme: currentTheme(),
        position: 'bottom-right',
        richColors: true,
        closeButton: true,
        visibleToasts: 4,
        // Remonté au-dessus de la barre de navigation mobile, qui occupe
        // le bas de l'écran sur petit écran.
        mobileOffset: { bottom: '84px', left: '16px', right: '16px' },
        toastOptions: { duration: 5000 },
    }));
}

render();

// Le sélecteur de thème réécrit l'attribut à chaud : on resuit, sinon les
// toasts restent dans l'ancienne palette jusqu'au rechargement.
new MutationObserver(render).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
});
