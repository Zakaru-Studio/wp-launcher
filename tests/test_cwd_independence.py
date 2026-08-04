"""Aucune opération ne doit dépendre du répertoire courant.

L'application tourne dans un unique worker eventlet où plusieurs opérations se
chevauchent, et le répertoire courant est une propriété du PROCESSUS : quand
une tâche faisait `os.chdir` dans le dossier d'un projet, toutes les autres se
retrouvaient dedans, et le `finally` de la première les ramenait ailleurs en
plein milieu de leur travail.

Concrètement, ça donnait trois pannes distinctes que ces tests verrouillent :
la bascule de version PHP échouant sur « Can't find a suitable configuration
file », la suppression de projet mourant sur « No such file or directory:
'logs' » — elle avait supprimé son propre répertoire courant — et le projet
restant affiché dans la liste faute d'avoir pu terminer.
"""
import os

import pytest


@pytest.fixture
def ailleurs(tmp_path):
    """Place le processus dans un répertoire sans rapport, puis restaure."""
    origine = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(origine)


def test_le_logger_ecrit_toujours_dans_le_depot(ailleurs):
    from app.utils.logger import WPLauncherLogger

    logger = WPLauncherLogger()
    assert logger.logs_dir.is_absolute()
    assert logger.logs_dir.exists()
    # et pas dans le répertoire courant du moment
    assert not (ailleurs / 'logs').exists()


def test_operation_logger_survit_a_un_repertoire_courant_deplace(ailleurs):
    """C'est le crash exact de la suppression : mkdir('logs/delete')."""
    from app.utils.logger import get_operation_logger

    op_logger = get_operation_logger('delete', 'projet-de-test')
    op_logger.step('TEST', 'ne doit pas lever')
    assert op_logger.log_file.is_absolute()
    assert op_logger.log_file.exists()


def test_le_logger_survit_a_un_repertoire_courant_supprime(tmp_path):
    """Le cas réel : la suppression efface le dossier où elle se trouvait."""
    from app.utils.logger import get_operation_logger

    condamne = tmp_path / 'condamne'
    condamne.mkdir()
    origine = os.getcwd()
    os.chdir(condamne)
    try:
        condamne.rmdir()  # le répertoire courant n'existe plus
        op_logger = get_operation_logger('delete', 'projet-de-test')
        op_logger.step('TEST', 'ne doit pas lever')
        assert op_logger.log_file.exists()
    finally:
        os.chdir(origine)


def test_les_racines_de_projets_sont_absolues():
    from app.config.docker_config import DockerConfig

    assert os.path.isabs(DockerConfig.PROJECTS_FOLDER)
    assert os.path.isabs(DockerConfig.CONTAINERS_FOLDER)


def test_aucun_os_chdir_dans_le_code_applicatif():
    """Garde-fou : un seul os.chdir suffit à faire revenir les trois pannes.

    Analyse de l'AST et non du texte : commentaires et docstrings mentionnent
    os.chdir pour expliquer pourquoi on ne s'en sert plus, et un simple grep
    les prendrait pour des appels.
    """
    import ast

    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_dir = os.path.join(racine, 'app')

    coupables = []
    for dossier, _, fichiers in os.walk(app_dir):
        for nom in fichiers:
            if not nom.endswith('.py'):
                continue
            chemin = os.path.join(dossier, nom)
            with open(chemin, encoding='utf-8') as f:
                arbre = ast.parse(f.read(), filename=chemin)
            for noeud in ast.walk(arbre):
                if (isinstance(noeud, ast.Call)
                        and isinstance(noeud.func, ast.Attribute)
                        and noeud.func.attr == 'chdir'):
                    coupables.append(
                        f"{os.path.relpath(chemin, racine)}:{noeud.lineno}"
                    )

    assert not coupables, (
        "os.chdir réintroduit — passer cwd= au subprocess : " + ", ".join(coupables)
    )


def test_docker_service_passe_le_cwd_a_compose():
    """_compose doit viser le dossier du projet sans déplacer le processus."""
    from unittest.mock import patch

    from app.services.docker_service import DockerService

    service = DockerService.__new__(DockerService)
    avant = os.getcwd()
    with patch('app.services.docker_service.subprocess.run') as run:
        service._compose('/un/chemin/de/projet', 'up', '-d', timeout=42)

    args, kwargs = run.call_args
    assert args[0] == ['docker-compose', 'up', '-d']
    assert kwargs['cwd'] == '/un/chemin/de/projet'
    assert kwargs['timeout'] == 42
    assert os.getcwd() == avant
