/**
 * Dropdown custom réutilisable — amélioration progressive des <select>.
 *
 * Principe : le <select> natif RESTE dans le DOM et reste la source de
 * vérité. Il est simplement rendu invisible, et une interface custom se
 * synchronise sur lui. Conséquence : tout le code existant continue de
 * fonctionner sans la moindre modification —
 *   • lecture   : `document.getElementById('x').value`
 *   • écriture  : `el.value = '…'` / `el.selectedIndex = n`
 *   • handlers  : `onchange="…"` (un vrai événement `change` est émis)
 *   • injection : `sel.innerHTML = '<option>…'` (observé et répercuté)
 *
 * Le natif est conservé (et non `display:none`) pour que la validation
 * HTML5 `required` des formulaires continue de pointer sur le champ.
 *
 * Opt-out : `data-no-custom-select` sur le <select>.
 */
(function () {
    'use strict';

    var SKIP = 'data-no-custom-select';
    var openInstance = null;

    /**
     * Où monter le menu.
     *
     * Dans une modale, on vise `.modal` et non `<body>` : Bootstrap y piège
     * le focus et renverrait le focus clavier hors d'un menu posé sur body.
     * `.modal` convient car il ne porte ni transform ni filtre — il ne crée
     * donc pas de bloc conteneur pour `position: fixed` (contrairement à
     * `.modal-content`), et son `overflow` ne rogne pas un enfant fixe.
     */
    function portalHost(el) {
        return el.closest('.modal') || document.body;
    }

    /** Purge les menus dont le déclencheur a disparu du DOM. */
    function dropOrphanMenus() {
        Array.prototype.forEach.call(
            document.querySelectorAll('.cs-menu[data-cs-portal="1"]'),
            function (m) {
                var owner = m.__csOwner;
                if (!owner || !owner.trigger.isConnected) m.remove();
            }
        );
    }

    /** Le <select> est-il éligible à l'amélioration ? */
    function eligible(sel) {
        if (!(sel instanceof HTMLSelectElement)) return false;
        if (sel.dataset.csReady === '1') return false;
        if (sel.hasAttribute(SKIP)) return false;
        if (sel.multiple) return false;
        if (sel.size > 1) return false;
        // Selects pilotés autrement et volontairement masqués
        if (sel.classList.contains('d-none') || sel.hidden) return false;
        return true;
    }

    function CustomSelect(sel) {
        this.sel = sel;
        this.build();
        this.patchValueSetters();
        this.observeOptions();
        this.bind();
        this.syncFromNative();
    }

    CustomSelect.prototype.build = function () {
        var sel = this.sel;

        var root = document.createElement('div');
        root.className = 'cs';
        // Les selects de formulaire occupent toute la largeur ; les selects
        // « inline » (pilule de rôle, nb de lignes) gardent leur largeur auto.
        if (sel.classList.contains('form-control') || sel.classList.contains('form-select')
            || sel.hasAttribute('data-cs-block')) {
            root.classList.add('cs-block');
        }
        if (sel.disabled) root.classList.add('cs-disabled');

        var trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'cs-trigger';
        // On reporte les classes du natif pour conserver le style de la page
        // (.form-control, .role-pill, .lines-selector…).
        sel.classList.forEach(function (c) { trigger.classList.add(c); });
        trigger.setAttribute('role', 'combobox');
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');
        if (sel.getAttribute('aria-label')) {
            trigger.setAttribute('aria-label', sel.getAttribute('aria-label'));
        }
        if (sel.id) trigger.setAttribute('aria-controls', sel.id + '-cs-menu');
        if (sel.disabled) trigger.disabled = true;

        var label = document.createElement('span');
        label.className = 'cs-label';

        var caret = document.createElement('span');
        caret.className = 'material-symbols-outlined cs-caret';
        caret.setAttribute('aria-hidden', 'true');
        caret.textContent = 'expand_more';

        trigger.appendChild(label);
        trigger.appendChild(caret);

        var menu = document.createElement('div');
        menu.className = 'cs-menu';
        menu.setAttribute('role', 'listbox');
        if (sel.id) menu.id = sel.id + '-cs-menu';
        menu.hidden = true;

        sel.parentNode.insertBefore(root, sel);
        root.appendChild(sel);
        root.appendChild(trigger);

        // Le menu est sorti de .cs (portail) : `.modal-content` porte un
        // `backdrop-filter`, qui crée un bloc conteneur pour les descendants
        // `position: fixed`. Laissé à l'intérieur, le menu voyait ses
        // coordonnées viewport réinterprétées relativement à la modale et
        // s'affichait décalé.
        menu.__csOwner = this;
        menu.dataset.csPortal = '1';
        portalHost(trigger).appendChild(menu);

        // Le natif reste soumis et validable, mais sort du flux visuel
        // et du parcours clavier (c'est le trigger qui le porte).
        sel.classList.add('cs-native');
        sel.setAttribute('tabindex', '-1');
        sel.setAttribute('aria-hidden', 'true');
        sel.dataset.csReady = '1';

        this.root = root;
        this.trigger = trigger;
        this.labelEl = label;
        this.menu = menu;
    };

    /** Reconstruit les entrées du menu depuis les <option> du natif. */
    CustomSelect.prototype.buildOptions = function () {
        var self = this;
        this.menu.textContent = '';

        Array.prototype.forEach.call(this.sel.options, function (opt, i) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'cs-option';
            item.setAttribute('role', 'option');
            item.dataset.index = String(i);
            item.textContent = opt.textContent;
            if (opt.disabled) {
                item.disabled = true;
                item.classList.add('cs-option-disabled');
            }
            item.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (opt.disabled) return;
                self.choose(i);
            });
            self.menu.appendChild(item);
        });
    };

    /** Aligne l'affichage custom sur l'état du <select> natif. */
    CustomSelect.prototype.syncFromNative = function () {
        if (this.menu.childElementCount !== this.sel.options.length) {
            this.buildOptions();
        }
        var opt = this.sel.options[this.sel.selectedIndex];
        var text = opt ? opt.textContent.trim() : '';
        this.labelEl.textContent = text;
        this.root.classList.toggle('cs-empty', !text);

        var idx = this.sel.selectedIndex;
        Array.prototype.forEach.call(this.menu.children, function (item, i) {
            var on = i === idx;
            item.classList.toggle('is-selected', on);
            item.setAttribute('aria-selected', on ? 'true' : 'false');
        });

        this.trigger.disabled = this.sel.disabled;
        this.root.classList.toggle('cs-disabled', this.sel.disabled);
    };

    /** Sélectionne l'option `i` et notifie l'application. */
    CustomSelect.prototype.choose = function (i) {
        if (this.sel.selectedIndex !== i) {
            this.sel.selectedIndex = i;
            // Événement réel : les `onchange="…"` inline et les listeners
            // existants se déclenchent normalement.
            this.sel.dispatchEvent(new Event('input', { bubbles: true }));
            this.sel.dispatchEvent(new Event('change', { bubbles: true }));
        }
        this.syncFromNative();
        this.close();
        this.trigger.focus();
    };

    /**
     * `el.value = …` et `el.selectedIndex = …` n'émettent aucun événement
     * et ne modifient aucun attribut : sans interception, l'affichage
     * custom resterait figé. On enveloppe donc les accesseurs natifs.
     */
    CustomSelect.prototype.patchValueSetters = function () {
        var self = this;
        ['value', 'selectedIndex'].forEach(function (prop) {
            var proto = Object.getPrototypeOf(self.sel);
            var desc = Object.getOwnPropertyDescriptor(proto, prop)
                || Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
            if (!desc || !desc.set) return;
            Object.defineProperty(self.sel, prop, {
                configurable: true,
                enumerable: desc.enumerable,
                get: function () { return desc.get.call(this); },
                set: function (v) {
                    desc.set.call(this, v);
                    self.syncFromNative();
                }
            });
        });
    };

    /** Les <option> injectées dynamiquement doivent apparaître dans le menu. */
    CustomSelect.prototype.observeOptions = function () {
        var self = this;
        var mo = new MutationObserver(function () {
            self.buildOptions();
            self.syncFromNative();
        });
        mo.observe(this.sel, { childList: true, subtree: true });
        this._observer = mo;
    };

    CustomSelect.prototype.bind = function () {
        var self = this;

        this.trigger.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            self.toggle();
        });

        this.trigger.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                self.open();
                self.focusOption(self.sel.selectedIndex >= 0 ? self.sel.selectedIndex : 0);
            }
        });

        this.menu.addEventListener('keydown', function (e) {
            var items = Array.prototype.filter.call(self.menu.children, function (i) {
                return !i.disabled;
            });
            var pos = items.indexOf(document.activeElement);

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                self.focusItem(items[Math.min(pos + 1, items.length - 1)]);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                self.focusItem(items[Math.max(pos - 1, 0)]);
            } else if (e.key === 'Home') {
                e.preventDefault(); self.focusItem(items[0]);
            } else if (e.key === 'End') {
                e.preventDefault(); self.focusItem(items[items.length - 1]);
            } else if (e.key === 'Escape') {
                e.preventDefault(); self.close(); self.trigger.focus();
            } else if (e.key === 'Tab') {
                self.close();
            }
        });

        // Le natif peut changer par une autre voie (reset de formulaire…).
        this.sel.addEventListener('change', function () { self.syncFromNative(); });
    };

    CustomSelect.prototype.focusOption = function (i) {
        this.focusItem(this.menu.children[i]);
    };

    CustomSelect.prototype.focusItem = function (item) {
        if (item) item.focus();
    };

    /**
     * Menu en `position: fixed` : il échappe ainsi à tout ancêtre
     * `overflow:auto/hidden` (tableau des utilisateurs, corps de modale).
     */
    CustomSelect.prototype.position = function () {
        var r = this.trigger.getBoundingClientRect();
        var menu = this.menu;
        var GAP = 6;
        var MARGIN = 12;

        menu.style.minWidth = r.width + 'px';
        menu.style.left = Math.round(r.left) + 'px';

        var below = window.innerHeight - r.bottom - GAP - MARGIN;
        var above = r.top - GAP - MARGIN;
        var needed = menu.scrollHeight;

        if (below >= Math.min(needed, 160) || below >= above) {
            menu.style.top = Math.round(r.bottom + GAP) + 'px';
            menu.style.bottom = 'auto';
            menu.style.maxHeight = Math.max(120, Math.round(below)) + 'px';
        } else {
            menu.style.top = 'auto';
            menu.style.bottom = Math.round(window.innerHeight - r.top + GAP) + 'px';
            menu.style.maxHeight = Math.max(120, Math.round(above)) + 'px';
        }
    };

    CustomSelect.prototype.open = function () {
        if (this.sel.disabled) return;
        if (openInstance && openInstance !== this) openInstance.close();
        dropOrphanMenus();
        // Le menu a pu partir avec un fragment re-rendu : on le remonte.
        if (!this.menu.isConnected) portalHost(this.trigger).appendChild(this.menu);

        this.syncFromNative();
        this.menu.hidden = false;
        this.root.classList.add('cs-open');
        this.trigger.setAttribute('aria-expanded', 'true');
        this.position();
        openInstance = this;

        var self = this;
        this._reflow = function () { if (openInstance === self) self.position(); };
        window.addEventListener('resize', this._reflow);
        window.addEventListener('scroll', this._reflow, true);
    };

    CustomSelect.prototype.close = function () {
        this.menu.hidden = true;
        this.root.classList.remove('cs-open');
        this.trigger.setAttribute('aria-expanded', 'false');
        if (this._reflow) {
            window.removeEventListener('resize', this._reflow);
            window.removeEventListener('scroll', this._reflow, true);
            this._reflow = null;
        }
        if (openInstance === this) openInstance = null;
    };

    CustomSelect.prototype.toggle = function () {
        if (this.menu.hidden) this.open(); else this.close();
    };

    /** Améliore tous les <select> éligibles sous `root`. */
    function enhance(root) {
        var scope = root || document;
        Array.prototype.forEach.call(scope.querySelectorAll('select'), function (sel) {
            if (!eligible(sel)) return;
            try {
                new CustomSelect(sel);
            } catch (err) {
                // En cas d'échec, le <select> natif reste pleinement utilisable.
                console.error('custom-select: enhancement failed', err);
                sel.classList.remove('cs-native');
                sel.removeAttribute('tabindex');
                sel.removeAttribute('aria-hidden');
            }
        });
    }

    document.addEventListener('click', function (e) {
        if (!openInstance) return;
        // Le menu est monté sur <body> : il ne fait plus partie de .cs,
        // il faut donc le tester séparément.
        if (openInstance.root.contains(e.target)) return;
        if (openInstance.menu.contains(e.target)) return;
        openInstance.close();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && openInstance) openInstance.close();
    });

    document.addEventListener('DOMContentLoaded', function () {
        enhance(document);
        // Modales et fragments injectés après coup.
        new MutationObserver(function (muts) {
            for (var i = 0; i < muts.length; i++) {
                for (var j = 0; j < muts[i].addedNodes.length; j++) {
                    var n = muts[i].addedNodes[j];
                    if (n.nodeType !== 1) continue;
                    if (n.tagName === 'SELECT') { enhance(n.parentNode); }
                    else if (n.querySelector && n.querySelector('select')) { enhance(n); }
                }
            }
        }).observe(document.body, { childList: true, subtree: true });
    });

    window.CustomSelect = { enhance: enhance };
})();
