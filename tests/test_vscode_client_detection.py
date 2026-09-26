"""Le bouton « Ouvrir dans VS Code » doit savoir si le navigateur est sur l'hôte.

Sur l'hôte : `vscode://file/...`, VS Code ouvre le dossier directement.
Ailleurs : Remote-SSH, le chemin n'existant pas sur le poste client.

Seul le bouclage était reconnu : ouvrir l'app par l'IP du LAN depuis la
machine elle-même (http://192.168.1.21:5000) la faisait passer pour distante,
et VS Code partait en SSH vers la machine sur laquelle il tournait déjà.
"""
import socket

import pytest

from app.routes.config import _is_address_of_this_machine


def _ip_sortante_de_cet_hote():
    """IP de l'interface qui porte la route par défaut (aucun paquet émis)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(('192.0.2.1', 9))  # TEST-NET-1, jamais routé réellement
        except OSError:
            pytest.skip("pas de route IPv4 sur cette machine")
        return sock.getsockname()[0]


@pytest.mark.parametrize('addr', ['127.0.0.1', '127.0.1.1', '::1', '::ffff:127.0.0.1'])
def test_le_bouclage_est_local(addr):
    assert _is_address_of_this_machine(addr)


def test_l_ip_du_lan_de_l_hote_est_locale():
    ip = _ip_sortante_de_cet_hote()
    assert _is_address_of_this_machine(ip)
    assert _is_address_of_this_machine(f'::ffff:{ip}')


@pytest.mark.parametrize('addr', [
    '192.0.2.44',       # TEST-NET-1 : n'est l'adresse d'aucune interface
    '2001:db8::44',     # plage de documentation IPv6
    '0.0.0.0',
    '',
    None,
    'localhost',        # remote_addr est toujours une IP, jamais un nom
    'pas-une-ip',
])
def test_une_autre_adresse_est_distante(addr):
    assert not _is_address_of_this_machine(addr)
