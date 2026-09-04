"""Écriture de wp-config.php.

Deux propriétés à ne jamais perdre, chacune correspondant à une panne réelle :

  — l'INODE est préservé. Le fichier est bind-monté à l'inode dans le
    conteneur ; le remplacer laisse WordPress sur l'ancien contenu, et le
    réglage semble pris en compte alors qu'il ne l'est pas.

  — un refus de droits est RATTRAPÉ, pas propagé. « Permission denied » sur
    wp-config.php était la panne du gestionnaire WP Debug : le fichier
    appartient à www-data, et un chmod 644 sur un fichier porteur d'ACL rabat
    le masque à r--, ce qui retire l'écriture au groupe.
"""
import os

import pytest

from app.utils import root_helpers, wp_config_writer
from app.utils.wp_config_writer import (WpConfigWriteError, read_wp_config,
                                        write_wp_config)


@pytest.fixture
def wp_config(tmp_path):
    path = tmp_path / 'wp-config.php'
    path.write_text("<?php\ndefine( 'WP_DEBUG', false );\n")
    return str(path)


# ─── écriture nominale ───────────────────────────────────────────────────

def test_ecriture_preserve_l_inode(wp_config):
    """Un rename casserait le bind mount fichier du conteneur."""
    avant = os.stat(wp_config).st_ino
    write_wp_config(wp_config, "<?php\ndefine( 'WP_DEBUG', true );\n")
    assert os.stat(wp_config).st_ino == avant


def test_ecriture_plus_courte_tronque(wp_config):
    """Sans troncature, la queue de l'ancien contenu resterait collée."""
    write_wp_config(wp_config, '<?php\n')
    assert open(wp_config).read() == '<?php\n'


def test_ecriture_preserve_le_mode(wp_config):
    """copy2 recopiait le mode 0600 du temporaire et verrouillait le fichier."""
    os.chmod(wp_config, 0o664)
    write_wp_config(wp_config, '<?php\n// x\n')
    assert os.stat(wp_config).st_mode & 0o777 == 0o664


def test_fichier_absent_leve_une_erreur_parlante(tmp_path):
    with pytest.raises(WpConfigWriteError, match='introuvable'):
        write_wp_config(str(tmp_path / 'absent.php'), '<?php\n')


# ─── reprise des droits ──────────────────────────────────────────────────

def _refuser_puis_reparer(monkeypatch, wp_config, mode_repare=0o664):
    """Simule un fichier illisible que seul le helper racine peut rouvrir."""
    appels = []

    def faux_fix_perms(path, profile, timeout=None):
        appels.append((path, profile))
        os.chmod(path, mode_repare)
        return 'ok'

    monkeypatch.setattr(root_helpers, 'available', lambda: True)
    monkeypatch.setattr(root_helpers, 'fix_perms', faux_fix_perms)
    os.chmod(wp_config, 0o000)
    return appels


def test_ecriture_reprend_les_droits_puis_reussit(monkeypatch, wp_config):
    appels = _refuser_puis_reparer(monkeypatch, wp_config)
    write_wp_config(wp_config, "<?php\ndefine( 'WP_DEBUG', true );\n")
    assert appels == [(wp_config, 'wp-config-dev')]
    assert 'true' in open(wp_config).read()


def test_lecture_reprend_les_droits(monkeypatch, wp_config):
    """Un wp-config.php en 600 www-data n'est même plus lisible par l'app."""
    appels = _refuser_puis_reparer(monkeypatch, wp_config)
    assert 'WP_DEBUG' in read_wp_config(wp_config)
    assert appels == [(wp_config, 'wp-config-dev')]


def test_lecture_nominale_n_appelle_pas_le_helper(monkeypatch, wp_config):
    def interdit(*a, **k):
        raise AssertionError('le helper racine ne doit pas être sollicité')

    monkeypatch.setattr(root_helpers, 'fix_perms', interdit)
    assert 'WP_DEBUG' in read_wp_config(wp_config)


def test_sans_helpers_l_erreur_dit_quoi_faire(monkeypatch, wp_config):
    monkeypatch.setattr(root_helpers, 'available', lambda: False)
    os.chmod(wp_config, 0o000)
    with pytest.raises(WpConfigWriteError, match='install.sh'):
        write_wp_config(wp_config, '<?php\n')


def test_helper_impuissant_ne_ment_pas(monkeypatch, wp_config):
    """Si la reprise échoue, l'appelant doit le savoir — pas de succès muet."""
    _refuser_puis_reparer(monkeypatch, wp_config, mode_repare=0o000)
    with pytest.raises(WpConfigWriteError, match='wp-config-dev'):
        write_wp_config(wp_config, '<?php\n')


def test_echec_du_helper_est_remonte(monkeypatch, wp_config):
    def echoue(path, profile, timeout=None):
        raise root_helpers.RootHelperError('profil inconnu')

    monkeypatch.setattr(root_helpers, 'available', lambda: True)
    monkeypatch.setattr(root_helpers, 'fix_perms', echoue)
    os.chmod(wp_config, 0o000)
    with pytest.raises(WpConfigWriteError, match='profil inconnu'):
        write_wp_config(wp_config, '<?php\n')


# ─── ensure_writable ─────────────────────────────────────────────────────

def test_ensure_writable_ne_fait_rien_si_deja_inscriptible(wp_config):
    assert wp_config_writer.ensure_writable(wp_config) is None
