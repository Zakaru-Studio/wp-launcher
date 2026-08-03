#!/usr/bin/env python3
"""
Redémarrage du service applicatif.

Point d'entrée unique, partagé par le bouton « Redémarrer l'application »
et par la mise à jour automatique.

Historiquement le redémarrage passait par `scripts/restart_app.sh`, écrit
à l'époque où l'application tournait via `python3 run.py`. Depuis le
passage à gunicorn sous systemd, ce script ne correspondait plus au
déploiement réel : son `pkill -f "python3.*run.py"` ne trouvait plus rien,
et il relançait un serveur de développement Werkzeug sur un port déjà
occupé par gunicorn.

Trois stratégies, de la plus propre à la plus brutale :
  1. systemd — `systemctl restart` sur l'unité (déploiement standard) ;
  2. gunicorn seul — SIGHUP au maître, qui recharge ses workers avec le
     nouveau code ;
  3. dernier recours — arrêt du processus, à charge du superviseur de le
     relancer (`Restart=always`).
"""
import os
import signal
import subprocess

from app.utils.logger import wp_logger

DEFAULT_UNIT = 'wp-launcher'


def _unit_name() -> str:
    return os.environ.get('WPL_SERVICE_NAME', DEFAULT_UNIT)


def _systemd_unit_available(unit: str) -> bool:
    """
    Vrai si l'unité est réellement connue de systemd.

    On interroge `LoadState` et non `is-active` : sur une unité inexistante,
    `is-active` répond « inactive » — indiscernable d'un service simplement
    arrêté — alors que `LoadState` répond « not-found ».
    """
    try:
        proc = subprocess.run(
            ['systemctl', 'show', '-p', 'LoadState', '--value', unit],
            capture_output=True, text=True, timeout=10
        )
        return proc.stdout.strip() == 'loaded'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _gunicorn_master_pid():
    """
    PID du maître gunicorn si l'on tourne dans un worker, sinon None.

    On compare le nom de l'exécutable du parent plutôt que de chercher la
    sous-chaîne « gunicorn » dans tout son `cmdline` : n'importe quelle
    commande la mentionnant produirait un faux positif.
    """
    ppid = os.getppid()
    if ppid <= 1:
        return None
    try:
        with open(f'/proc/{ppid}/cmdline', 'rb') as fh:
            argv = [a.decode('utf-8', 'replace') for a in fh.read().split(b'\0') if a]
    except OSError:
        return None
    if not argv:
        return None
    # gunicorn est lancé soit directement, soit via `python .../bin/gunicorn`.
    candidates = argv[:2]
    if any(os.path.basename(a) == 'gunicorn' for a in candidates):
        return ppid
    return None


def restart_service() -> tuple:
    """
    Redémarre l'application. Renvoie (succès, méthode employée).

    Ne rend la main que si aucune stratégie n'a abouti : les deux premières
    tuent le processus courant.
    """
    unit = _unit_name()

    # 1. systemd — `--no-block` met le job en file et rend la main tout de
    #    suite : sans cela, systemd nous arrêterait au milieu de la commande.
    if _systemd_unit_available(unit):
        try:
            proc = subprocess.run(
                ['sudo', '-n', 'systemctl', '--no-block', 'restart', unit],
                capture_output=True, text=True, timeout=30
            )
            if proc.returncode == 0:
                wp_logger.log_system_info(f'Redémarrage demandé à systemd (unité {unit})')
                return True, f'systemctl restart {unit}'
            wp_logger.logger.warning(
                f'systemctl a échoué ({proc.returncode}) : {(proc.stderr or "").strip()}'
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            wp_logger.logger.warning(f'systemctl indisponible : {exc}')

    # 2. gunicorn sans systemd : SIGHUP recharge les workers avec le nouveau code.
    master = _gunicorn_master_pid()
    if master:
        try:
            os.kill(master, signal.SIGHUP)
            wp_logger.log_system_info(f'SIGHUP envoyé au maître gunicorn (pid {master})')
            return True, f'SIGHUP gunicorn (pid {master})'
        except OSError as exc:
            wp_logger.logger.warning(f'SIGHUP impossible : {exc}')

    # 3. Dernier recours : on sort, le superviseur relance (Restart=always).
    wp_logger.logger.warning("Arrêt du processus : le superviseur doit le relancer")
    os._exit(0)
