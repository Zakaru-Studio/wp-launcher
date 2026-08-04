"""Validation des helpers exécutés en root.

Ces scripts sont la frontière de sécurité de l'application : ils tournent en
root et reçoivent leurs arguments d'un processus qu'on suppose compromis. Ce
qui est testé ici, c'est donc uniquement leur couche de REFUS — elle s'exécute
avant toute opération privilégiée, ce qui permet de la vérifier sans root.

Les scripts sont lus depuis le dépôt, pas depuis /opt : on teste la source,
et install.sh est chargé de garder les deux identiques.
"""
import os
import subprocess

import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'root'
)
COMMON = os.path.join(SCRIPTS_DIR, 'wpl-common.sh')


def _bash(snippet, base_dir):
    """Exécute un fragment après avoir sourcé wpl-common.sh."""
    return subprocess.run(
        ['bash', '-c', f'. "{COMMON}"\n{snippet}'],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, 'WPL_BASE_DIR': str(base_dir)},
    )


@pytest.fixture
def base(tmp_path):
    """Une arborescence minimale projets/ + containers/."""
    (tmp_path / 'projets' / 'demo').mkdir(parents=True)
    (tmp_path / 'containers' / 'demo').mkdir(parents=True)
    return tmp_path


# ─── valid_subpath ───────────────────────────────────────────────────────

@pytest.mark.parametrize('subpath', [
    'wp-content/uploads',
    'themes',
    '.dev-instances/geoffrey',            # le point initial doit passer :
    '.dev-instances/geoffrey/wp-content',  # sinon les instances de dev sont
])                                         # irréparables
def test_valid_subpath_accepte(subpath, base):
    assert _bash(f'valid_subpath "{subpath}"', base).returncode == 0


@pytest.mark.parametrize('subpath', [
    '.', '..', '../etc', '.dev-instances/../../etc', 'wp-content/../../../etc',
    '/etc/passwd',      # absolu
    '..hidden',         # le « .. » est refusé où qu'il soit
    '', 'a b', 'a;id', '$(id)', '-rf',
])
def test_valid_subpath_refuse(subpath, base):
    assert _bash(f'valid_subpath "{subpath}"', base).returncode != 0


@pytest.mark.parametrize('name', ['', '.', '..', '.cache', '-rf', 'a/b', 'a;id'])
def test_valid_name_refuse(name, base):
    """Un nom vide faisait porter le rm -rf sur le dossier parent entier."""
    assert _bash(f'valid_name "{name}"', base).returncode != 0


# ─── resolve_under ───────────────────────────────────────────────────────

def test_resolve_under_accepte_un_chemin_normal(base):
    cible = base / 'projets' / 'demo' / 'wp-content'
    cible.mkdir()
    out = _bash(f'resolve_under "{cible}" "$PROJECTS_DIR"', base)
    assert out.returncode == 0
    assert out.stdout.strip() == str(cible)


def test_resolve_under_refuse_une_cible_hors_racine(base):
    dehors = base / 'dehors'
    dehors.mkdir()
    lien = base / 'projets' / 'demo' / 'wp-content'
    lien.symlink_to(dehors)
    assert _bash(f'resolve_under "{lien}" "$PROJECTS_DIR"', base).returncode != 0


def test_resolve_under_refuse_une_racine_derivee_detournee(base):
    """Régression : la racine elle-même n'était jamais validée.

    Plusieurs appelants passent une racine dérivée (« …/.dev-instances »,
    « …/wp-content »), c'est-à-dire un chemin que l'application peut remplacer
    par un lien symbolique. realpath résolvait alors la racine ET la cible à
    travers ce lien, donc la comparaison de préfixe réussissait toujours. Un
    « .dev-instances -> /etc » suivi de la suppression d'une instance nommée
    « ssl » donnait un rm -rf /etc/ssl exécuté par root.
    """
    dehors = base / 'dehors'
    (dehors / 'ssl').mkdir(parents=True)
    racine = base / 'projets' / 'demo' / '.dev-instances'
    racine.symlink_to(dehors)

    resultat = _bash(f'resolve_under "{racine}/ssl" "{racine}"', base)
    assert resultat.returncode != 0
    assert 'racine non autorisée' in resultat.stderr


def test_resolve_under_accepte_les_deux_racines_constantes(base):
    """containers/ est une racine légitime, au même titre que projets/."""
    for var in ('PROJECTS_DIR', 'CONTAINERS_DIR'):
        out = _bash(f'resolve_under "${var}/demo" "${var}"', base)
        assert out.returncode == 0, out.stderr


# ─── refus au niveau des scripts eux-mêmes ───────────────────────────────

def _run_script(name, args, base):
    return subprocess.run(
        [os.path.join(SCRIPTS_DIR, name), *args],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, 'WPL_BASE_DIR': str(base)},
    )


def test_fix_perms_refuse_un_profil_inconnu(base):
    resultat = _run_script('wpl-fix-perms.sh', ['demo', 'profil-inexistant'], base)
    assert resultat.returncode != 0
    assert 'profil inconnu' in resultat.stderr


def test_fix_perms_refuse_un_projet_hors_racine(base):
    assert _run_script('wpl-fix-perms.sh', ['../../etc', 'shared'], base).returncode != 0


def test_copy_wp_content_refuse_une_destination_liee(base):
    """Régression : --no-links ne protège que la SOURCE.

    Une destination remplacée par un lien faisait écrire rsync à travers ce
    lien, en root — de quoi écraser les helpers eux-mêmes.
    """
    projet = base / 'projets' / 'demo'
    (projet / 'wp-content' / 'plugins').mkdir(parents=True)
    dest = projet / '.dev-instances' / 'inst' / 'wp-content'
    dest.mkdir(parents=True)
    dehors = base / 'dehors'
    dehors.mkdir()
    (dest / 'plugins').symlink_to(dehors)

    resultat = _run_script('wpl-copy-wp-content.sh', ['demo', 'inst', 'plugins'], base)
    assert resultat.returncode != 0
    assert 'destination liée' in resultat.stderr
    assert not list(dehors.iterdir())


def test_write_wp_config_refuse_un_contenu_vide(base):
    resultat = subprocess.run(
        [os.path.join(SCRIPTS_DIR, 'wpl-write-wp-config.sh'), 'demo'],
        input='', capture_output=True, text=True, timeout=30,
        env={**os.environ, 'WPL_BASE_DIR': str(base)},
    )
    assert resultat.returncode != 0
