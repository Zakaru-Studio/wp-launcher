"""Projets Payload CMS : rendu du compose, ports, import Postgres, routes."""
import gzip
import os
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config.docker_config import DockerConfig
from app.config.ports_config import PortsConfig
from app.services import payload_service
from app.services.pg_import_service import (
    filter_foreign_roles, is_custom_dump, prepare_dump, quote_ident,
)
from app.utils import port_preflight
from app.utils.pg_target import pg_target, write_sidecar
from app.utils.project_utils import copy_docker_template_payload, get_project_type
from app.utils.security_config import apply_project_credentials

PORTS = {'payload': 8101, 'postgres': 8102, 'adminer': 8103, 'mailpit': 8104, 'smtp': 8105}
CREDS = {'{postgres_password}': 'pgpass123', '{payload_secret}': 'deadbeef'}
ROOT = Path(__file__).resolve().parent.parent


# ─── rendu du compose ──────────────────────────────────────────────────


@pytest.fixture()
def rendered(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)  # template_path relatif : 'docker-template'
    copy_docker_template_payload(str(tmp_path), 'acme-site', PORTS, CREDS)
    return (tmp_path / 'docker-compose.yml').read_text()


def test_compose_has_no_placeholder_left(rendered):
    assert not re.findall(r'\{[a-z][a-z0-9_]*\}', rendered)


def test_compose_uses_given_credentials_and_ports(rendered):
    assert 'POSTGRES_PASSWORD: "pgpass123"' in rendered
    assert 'PAYLOAD_SECRET=deadbeef' in rendered
    assert 'postgres://acme-site:pgpass123@postgres:5432/acme-site' in rendered
    assert ':8101:3000' in rendered and ':8103:8080' in rendered and ':8102:5432' in rendered
    assert f'NEXT_PUBLIC_SERVER_URL=http://{DockerConfig.LOCAL_IP}:8101' in rendered
    assert 'container_name: acme-site_payload_1' in rendered


def test_compose_copies_support_files(rendered, tmp_path):
    assert (tmp_path / 'payload-config' / 'start.sh').is_file()
    assert (tmp_path / 'adminer-config' / 'wpl-autologin.php').is_file()


def test_compose_refuses_missing_port(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    ports = dict(PORTS)
    del ports['adminer']
    with pytest.raises(Exception, match='adminer_port'):
        copy_docker_template_payload(str(tmp_path), 'acme', ports, CREDS)


def test_credentials_generated_when_not_overridden():
    out = apply_project_credentials('a={postgres_password} b={postgres_password} s={payload_secret}')
    password = re.search(r'a=(\S+)', out).group(1)
    assert f'b={password}' in out  # même valeur partout
    assert re.search(r's=[0-9a-f]{64}$', out)


# ─── ports ─────────────────────────────────────────────────────────────


def test_used_ports_include_every_sidecar(tmp_path, monkeypatch):
    from app.utils import port_utils

    project = tmp_path / 'containers' / 'acme'
    project.mkdir(parents=True)
    (project / '.payload_port').write_text('8201')
    (project / '.api_port').write_text('8202')
    (project / '.adminer_port').write_text('8203')
    monkeypatch.setattr(DockerConfig, 'CONTAINERS_FOLDER', str(tmp_path / 'containers'))
    monkeypatch.setattr(port_utils, 'PROJECTS_FOLDER', str(tmp_path / 'projets'))
    with patch('subprocess.run', return_value=SimpleNamespace(stdout='')):
        used = port_utils.get_used_ports()
    assert {8201, 8202, 8203} <= set(used)


def test_preflight_classifies_payload_services(rendered):
    kinds = {}
    for m in port_preflight._PORT_LINE_RE.finditer(rendered):
        kinds[int(m.group('host'))] = port_preflight._classify_binding(
            rendered, m.start(), int(m.group('container')))
    assert kinds == {8101: 'payload', 8102: 'postgres', 8103: 'adminer',
                     8104: 'mailpit', 8105: 'smtp'}
    for kind in ('payload', 'postgres', 'adminer'):
        assert port_preflight._sidecar_file('/x', kind) == f'/x/{PortsConfig.PORT_FILES[kind]}'


def test_preflight_remap_rewrites_public_url(rendered):
    out = port_preflight._replace_port_in_compose(rendered, 8101, 8301)
    assert f'NEXT_PUBLIC_SERVER_URL=http://{DockerConfig.LOCAL_IP}:8301' in out
    assert ':8301:3000' in out


# ─── type de projet, .env, pg_target ───────────────────────────────────


def test_project_type_detected_from_payload_config(tmp_path):
    (tmp_path / 'app' / 'src').mkdir(parents=True)
    (tmp_path / 'app' / 'src' / 'payload.config.ts').write_text('')
    assert get_project_type(str(tmp_path)) == 'payload'
    (tmp_path / '.project_type').write_text('payload\n')
    assert get_project_type(str(tmp_path)) == 'payload'


def test_write_env_updates_managed_keys_only(tmp_path):
    app_dir = tmp_path / 'acme' / 'app'
    app_dir.mkdir(parents=True)
    (app_dir / '.env').write_text(
        'DATABASE_URL=postgres://old\nPAYLOAD_SECRET=old\nCRON_SECRET=YOUR_CRON_SECRET_HERE\nOTHER=keep\n')
    payload_service.write_env('acme', 'postgres://new', 'newsecret', 8101, str(tmp_path))
    env = (app_dir / '.env').read_text()
    assert 'DATABASE_URL=postgres://new' in env and 'DATABASE_URI=postgres://new' in env
    assert 'PAYLOAD_SECRET=newsecret' in env and 'OTHER=keep' in env
    assert 'NEXT_PUBLIC_SERVER_URL=http://' in env and ':8101' in env
    assert 'YOUR_CRON_SECRET_HERE' not in env
    assert env.count('DATABASE_URL=') == 1


def test_pg_target_reads_sidecar(tmp_path):
    (tmp_path / 'acme').mkdir()
    write_sidecar('acme', 'acme', 'acme', 's3cret', str(tmp_path))
    target = pg_target('acme', str(tmp_path))
    assert (target.container, target.database, target.user, target.password) == \
        ('acme_postgres_1', 'acme', 'acme', 's3cret')
    assert target.psql_cmd('-c', 'SELECT 1', database='postgres')[:4] == \
        ['docker', 'exec', 'acme_postgres_1', 'psql']
    assert 'PGPASSWORD' not in ' '.join(target.pg_dump_cmd())


def test_run_command_rejects_unknown_command():
    ok, message = payload_service.run_command('acme', 'rm -rf /')
    assert not ok and 'non autorisée' in message


# ─── import Postgres ───────────────────────────────────────────────────


def test_filter_foreign_roles():
    lines = [
        b'SET statement_timeout = 0;\n',
        b'SET transaction_timeout = 0;\n',
        b'CREATE TABLE public.users (id integer);\n',
        b'ALTER TABLE public.users OWNER TO postgres;\n',
        b'GRANT ALL ON SCHEMA public TO app;\n',
        b'REVOKE USAGE ON SCHEMA public FROM PUBLIC;\n',
        b'ALTER DEFAULT PRIVILEGES FOR ROLE x GRANT SELECT ON TABLES TO y;\n',
        b"INSERT INTO public.users VALUES (1); -- GRANT in data is fine\n",
    ]
    kept = list(filter_foreign_roles(iter(lines)))
    assert kept == [lines[0], lines[2], lines[7]]


def test_custom_dump_detection(tmp_path):
    custom = tmp_path / 'a.dump'
    custom.write_bytes(b'PGDMP\x01\x0e\x00')
    plain = tmp_path / 'a.sql'
    plain.write_text('SELECT 1;')
    assert is_custom_dump(str(custom)) and not is_custom_dump(str(plain))


def test_prepare_dump_handles_archives(tmp_path):
    gz = tmp_path / 'db.sql.gz'
    with gzip.open(gz, 'wb') as fh:
        fh.write(b'SELECT 1;')
    path, cleanup = prepare_dump(str(gz))
    assert Path(path).read_bytes() == b'SELECT 1;'
    os.remove(cleanup)

    zipped = tmp_path / 'db.zip'
    with zipfile.ZipFile(zipped, 'w') as zf:
        zf.writestr('export/site.dump', b'PGDMP')
    path, cleanup = prepare_dump(str(zipped))
    assert path.endswith('site.dump') and is_custom_dump(path)

    raw = tmp_path / 'db.dump'
    raw.write_bytes(b'PGDMP')
    assert prepare_dump(str(raw)) == (str(raw), None)


def test_quote_ident_handles_hyphens():
    assert quote_ident('acme-site') == '"acme-site"'
    assert quote_ident('a"b') == '"a""b"'


# ─── routes ────────────────────────────────────────────────────────────


@pytest.fixture()
def logged_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
    user_service = app.extensions['user_service']
    with patch.object(user_service, 'get_user_by_id',
                      return_value=SimpleNamespace(id=1, role='admin', is_admin=True)):
        yield client


@pytest.fixture()
def payload_project(tmp_path, monkeypatch):
    projects = tmp_path / 'projets'
    (projects / 'acme').mkdir(parents=True)
    (projects / 'acme' / '.project_type').write_text('payload')
    monkeypatch.setattr(DockerConfig, 'PROJECTS_FOLDER', str(projects))
    return 'acme'


def test_create_project_rejects_unknown_type(logged_client):
    res = logged_client.post('/create_project', data={'project_name': 'x', 'project_type': 'drupal'})
    assert res.status_code == 400
    assert 'inconnu' in res.get_json()['message']


def test_create_project_rejects_unknown_payload_template(logged_client):
    res = logged_client.post('/create_project', data={
        'project_name': 'x', 'project_type': 'payload', 'payload_template': 'nope'})
    assert res.status_code == 400


def test_wordpress_only_routes_refuse_payload(logged_client, payload_project):
    res = logged_client.get(f'/wpcli/plugins/{payload_project}')
    assert res.status_code == 400
    assert 'Payload' in res.get_json()['message']


def test_wordpress_only_guard_needs_a_session(app, payload_project):
    res = app.test_client().get(f'/wpcli/plugins/{payload_project}')
    assert res.status_code == 302  # login_required redirige, rien n'est révélé


def test_payload_command_route(logged_client, payload_project):
    with patch.object(payload_service, 'run_command', return_value=(True, 'types ok')) as run:
        res = logged_client.post(f'/payload/{payload_project}/cmd/generate:types')
    assert res.get_json()['success'] and res.get_json()['output'] == 'types ok'
    run.assert_called_once_with(payload_project, 'generate:types')

    res = logged_client.post(f'/payload/{payload_project}/cmd/evil')
    assert res.status_code == 400


def test_logs_route_limits_services(logged_client, payload_project, app):
    docker = MagicMock()
    docker.get_container_logs.return_value = 'ready on :3000'
    with patch.dict(app.extensions, {'docker': docker}):
        res = logged_client.get(f'/api/projects/{payload_project}/logs')
        assert res.get_json()['logs'] == 'ready on :3000'
        docker.get_container_logs.assert_called_once_with(payload_project, 'payload', 500)

        res = logged_client.get(f'/api/projects/{payload_project}/logs?service=wordpress')
        assert res.status_code == 400


def test_ports_allocated_as_contiguous_block():
    from app.routes import project_lifecycle
    # 8080 isolé (trou laissé par un projet supprimé), 8081-8083 pris :
    # le bloc doit sauter le trou au lieu d'y loger l'app seule.
    with patch.object(project_lifecycle, 'get_used_ports', return_value=[8081, 8082, 8083, 8086]), \
         patch('app.utils.port_preflight.is_host_port_free', side_effect=lambda p: p != 8088):
        ports = project_lifecycle._allocate_ports(('payload', 'postgres', 'adminer'))
    assert ports == {'payload': 8089, 'postgres': 8090, 'adminer': 8091}


def _scaffold_like(tmp_path, admin_block='  admin: {\n    user: Users.slug,\n  },\n'):
    app_dir = tmp_path / 'acme' / 'app'
    (app_dir / 'src').mkdir(parents=True)
    (app_dir / 'next.config.ts').write_text(
        "const nextConfig: NextConfig = {\n  reactStrictMode: true,\n}\n")
    (app_dir / 'src' / 'payload.config.ts').write_text(
        "const x = { admin: { nope: 1 } }\nexport default buildConfig({\n" + admin_block + "})\n")
    return app_dir


def test_patch_app_config_inserts_launcher_settings(tmp_path):
    app_dir = _scaffold_like(tmp_path)
    assert payload_service.patch_app_config('acme', str(tmp_path)) == []
    nxt = (app_dir / 'next.config.ts').read_text()
    cfg = (app_dir / 'src' / 'payload.config.ts').read_text()
    assert "allowedDevOrigins: (process.env.WPL_DEV_ORIGINS" in nxt
    assert "cookiePrefix: process.env.WPL_COOKIE_PREFIX" in cfg
    # autoLogin va dans le `admin` de buildConfig, pas dans un objet antérieur
    assert cfg.index('autoLogin') > cfg.index('export default buildConfig')
    assert 'admin: { nope: 1 }' in cfg

    # idempotent
    assert payload_service.patch_app_config('acme', str(tmp_path)) == []
    assert (app_dir / 'src' / 'payload.config.ts').read_text() == cfg


def test_patch_app_config_reports_missing_anchor(tmp_path):
    _scaffold_like(tmp_path, admin_block='')
    assert payload_service.patch_app_config('acme', str(tmp_path)) == ['src/payload.config.ts (autoLogin)']


def test_compose_passes_launcher_env(rendered):
    assert f'WPL_DEV_ORIGINS={DockerConfig.LOCAL_IP},localhost,127.0.0.1' in rendered
    assert 'WPL_COOKIE_PREFIX=acme-site' in rendered
    assert f'WPL_AUTOLOGIN_EMAIL={DockerConfig.WP_ADMIN_EMAIL}' in rendered
