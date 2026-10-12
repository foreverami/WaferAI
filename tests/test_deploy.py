"""배포 설정 검증 — Docker 없이 돌아간다.

실제 컨테이너를 띄우지 않고도 잡을 수 있는 실수를 여기서 막는다. 하나하나가 실제로
배포 후에야 드러나는 종류다:

  * 의존성 누락 — 로컬에는 깔려 있어 멀쩡하다가 이미지에서만 ImportError
  * .env · 가중치가 이미지에 섞여 들어감 — 비밀값이 레이어에 영구히 남는다
  * Nginx add_header 상속 — location 에서 하나만 추가해도 보안 헤더가 조용히 사라진다
  * 업로드 상한 불일치 — Nginx 가 먼저 HTML 413 을 내 화면이 오류를 못 읽는다
  * SPA 새로고침 404, 컨테이너 재시작 후 502 (Nginx 가 옛 IP 를 붙잡고 있음)

crossplane(Nginx 파서)과 docker(빌드 컨텍스트 계산)가 없으면 해당 검사만 건너뛴다.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / 'deploy'
NGINX = DEPLOY / 'nginx'
SITE_CONFIGS = [NGINX / 'default.conf', NGINX / 'https.conf.example']

#: 이미지에 들어가 서버에서 실행되는 파이썬 코드. 이것들의 import 가 런타임 의존성이다.
IMAGE_PYTHON = [*sorted((ROOT / 'waferai').rglob('*.py')),
                ROOT / 'scripts/create_user.py', ROOT / 'scripts/benchmark.py']

#: import 이름과 배포 패키지 이름이 다른 경우
DIST_NAME = {
    'cv2': 'opencv-python-headless', 'jwt': 'pyjwt', 'sqlalchemy': 'sqlalchemy',
    'pydantic_settings': 'pydantic-settings', 'psycopg': 'psycopg',
    'yaml': 'pyyaml', 'sklearn': 'scikit-learn',
}

#: 코드에서 직접 import 하지 않지만 런타임에 반드시 필요한 것
IMPLICIT_RUNTIME = {
    'uvicorn': 'CMD 가 실행한다',
    'alembic': '진입점이 기동 시 마이그레이션을 돌린다',
    'python-multipart': 'FastAPI UploadFile 파싱',
    'email-validator': 'pydantic EmailStr',
    'torchvision': 'timm 이 요구한다',
}

#: 배포 이미지에 들어가면 안 되는 개발 도구
DEV_ONLY = {'httpx', 'onnx', 'onnxscript', 'pandas', 'scikit-learn', 'reportlab',
            'playwright', 'crossplane', 'docker'}


def requirement_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        name = re.split(r'[\[<>=!~ ;]', line, maxsplit=1)[0]
        names.add(name.lower().replace('_', '-'))
    return names


def third_party_imports(paths) -> set[str]:
    stdlib = set(sys.stdlib_module_names)
    found = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split('.')[0])
    return {name for name in found if name not in stdlib and name not in ('waferai', 'scripts')}


def load_compose(name: str = 'compose.yaml') -> dict:
    return yaml.safe_load((DEPLOY / name).read_text())


# ── 의존성 ─────────────────────────────────────────────────────────────────────

class RequirementsTests(unittest.TestCase):
    """requirements.txt 가 이미지에 들어가는 코드를 빠짐없이 덮는가.

    Phase 2 에서 SQLAlchemy·PyJWT 등 7개를 설치만 하고 파일에 적지 않은 적이 있다.
    로컬에는 이미 깔려 있어 아무 테스트도 실패하지 않았다. 이 검사가 그것을 잡는다.
    """

    runtime = requirement_names(ROOT / 'requirements.txt')

    def test_every_runtime_import_is_listed(self):
        missing = []
        for module in sorted(third_party_imports(IMAGE_PYTHON)):
            dist = DIST_NAME.get(module, module).lower().replace('_', '-')
            if dist not in self.runtime:
                missing.append(f'{module} → {dist}')
        self.assertEqual(missing, [], f'requirements.txt 에 없는 런타임 의존성: {missing}')

    def test_implicit_runtime_dependencies_are_listed(self):
        missing = {name: why for name, why in IMPLICIT_RUNTIME.items() if name not in self.runtime}
        self.assertEqual(missing, {}, f'코드에서 import 하지 않지만 필요한 패키지가 빠짐: {missing}')

    def test_dev_tools_stay_out_of_the_image(self):
        leaked = sorted(DEV_ONLY & self.runtime)
        self.assertEqual(leaked, [], f'개발 도구가 배포 의존성에 섞임: {leaked}')

    def test_dev_requirements_include_runtime(self):
        text = (ROOT / 'requirements-dev.txt').read_text()
        self.assertIn('-r requirements.txt', text)


# ── API 이미지 ─────────────────────────────────────────────────────────────────

class DockerfileTests(unittest.TestCase):
    text = (ROOT / 'Dockerfile').read_text()

    def copy_sources(self) -> list[str]:
        sources = []
        for line in re.findall(r'^COPY\s+(.+)$', self.text, flags=re.M):
            if '--from=' in line:
                continue
            parts = [part for part in line.split() if not part.startswith('--')]
            sources.extend(parts[:-1])
        return sources

    def test_copy_sources_exist(self):
        missing = [source for source in self.copy_sources() if not (ROOT / source).exists()]
        self.assertEqual(missing, [], f'Dockerfile 이 없는 파일을 COPY 합니다: {missing}')

    def test_base_images_are_pinned(self):
        for image in re.findall(r'^FROM\s+(\S+)', self.text, flags=re.M):
            self.assertNotIn(':latest', image)
            self.assertIn(':', image, f'태그 없는 베이스 이미지: {image}')

    def test_runs_as_non_root(self):
        users = re.findall(r'^USER\s+(\S+)', self.text, flags=re.M)
        self.assertTrue(users and users[-1] not in ('root', '0'))

    def test_cpu_torch_is_installed_before_requirements(self):
        """순서가 바뀌면 리눅스에서 CUDA 휠(수 GB)이 먼저 깔린다."""
        cpu = self.text.find('download.pytorch.org/whl/cpu')
        reqs = self.text.find('pip install -r')
        self.assertGreater(cpu, 0)
        self.assertLess(cpu, reqs)

    def test_imports_are_smoke_tested_at_build_time(self):
        self.assertRegex(self.text, r'RUN python .*import .*waferai\.server')


#: 빌드 컨텍스트에 절대 들어가면 안 되는 파일. 지금 디스크에 없더라도 규칙이 막아야 한다.
FORBIDDEN_IN_CONTEXT = [
    '.env', 'deploy/.env', '.git/HEAD', 'models/best_coatnet_model_optimized.pth',
    'models/coatnet_wafer.onnx', 'data/waferai.db', 'data/heatmaps/x.png',
    'frontend/node_modules/x/index.js', 'docs/report.pdf', 'tests/conftest.py',
    'deploy/backups/waferai.dump', 'deploy/certbot/conf/live/x/privkey.pem',
    'waferai/__pycache__/server.cpython-313.pyc',
]


class BuildContextTests(unittest.TestCase):
    """.dockerignore 를 실제 규칙대로 적용해 이미지에 들어가는 파일을 계산한다.

    현재 디스크를 그대로 검사하면 안 된다. 처음에 그렇게 했더니, .env 가 아직 없는
    저장소에서는 .dockerignore 가 .env 를 허용해도 테스트가 통과했다(없는 파일은 당연히
    컨텍스트에 없다). 그래서 금지 파일이 모두 존재하는 가상 저장소를 만들어 규칙을 시험한다.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from docker.utils.build import exclude_paths
        except ImportError:
            raise unittest.SkipTest('docker 패키지가 없습니다 (requirements-dev.txt)')

        cls._tree = tempfile.TemporaryDirectory()
        tree = Path(cls._tree.name)
        real_files = [path.relative_to(ROOT) for path in ROOT.rglob('*')
                      if path.is_file() and not any(part in ('node_modules', '.git')
                                                    for part in path.relative_to(ROOT).parts)]
        for relative in [*map(str, real_files), *FORBIDDEN_IN_CONTEXT]:
            target = tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        shutil.copy(ROOT / '.dockerignore', tree / '.dockerignore')

        patterns = [line.strip() for line in (ROOT / '.dockerignore').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        # 이름과 달리 이 함수는 "제외되지 않는", 즉 컨텍스트에 들어가는 경로를 돌려준다.
        cls.context = exclude_paths(str(tree), patterns, dockerfile='Dockerfile')

    @classmethod
    def tearDownClass(cls):
        cls._tree.cleanup()

    def test_secrets_and_bulk_data_are_excluded(self):
        leaked = [path for path in FORBIDDEN_IN_CONTEXT if path in self.context]
        self.assertEqual(leaked, [], f'빌드 컨텍스트에 들어가면 안 됩니다: {leaked}')

    def test_everything_the_dockerfile_copies_is_in_context(self):
        for source in DockerfileTests().copy_sources():
            source = source.rstrip('/')
            self.assertTrue(any(path == source or path.startswith(source + '/')
                                for path in self.context),
                            f'.dockerignore 가 COPY 대상을 막습니다: {source}')

    def test_no_bytecode_caches(self):
        caches = [path for path in self.context if '__pycache__' in path or path.endswith('.pyc')]
        self.assertEqual(caches, [])


# ── compose ────────────────────────────────────────────────────────────────────

class ComposeTests(unittest.TestCase):
    compose = load_compose()

    def test_only_the_web_service_is_reachable_from_outside(self):
        """DB 와 API 는 내부 네트워크로만. 밖에서는 Nginx 하나로만 들어온다."""
        exposed = {name for name, service in self.compose['services'].items()
                   if service.get('ports')}
        self.assertEqual(exposed, {'web'})

    def test_healthy_dependencies_have_healthchecks(self):
        services = self.compose['services']
        for name, service in services.items():
            for target, rule in (service.get('depends_on') or {}).items():
                if rule.get('condition') == 'service_healthy':
                    self.assertIn('healthcheck', services[target],
                                  f'{name} 가 기다리는 {target} 에 healthcheck 가 없습니다')

    def test_named_volumes_are_declared(self):
        declared = set(self.compose.get('volumes') or {})
        for name, service in self.compose['services'].items():
            for volume in service.get('volumes', []):
                source = volume.split(':')[0]
                if not source.startswith(('.', '/')):
                    self.assertIn(source, declared, f'{name}: 선언되지 않은 볼륨 {source}')

    def test_every_variable_is_documented_in_env_example(self):
        documented = set(re.findall(r'^([A-Z_][A-Z0-9_]*)=', (DEPLOY / '.env.example').read_text(),
                                    flags=re.M))
        for name in ('compose.yaml', 'compose.https.yaml'):
            used = set(re.findall(r'\$\{([A-Z_][A-Z0-9_]*)', (DEPLOY / name).read_text()))
            self.assertEqual(used - documented, set(),
                             f'{name} 이 쓰는 변수가 .env.example 에 없습니다')

    def test_secrets_are_required_not_defaulted(self):
        """비밀값에 기본값이 있으면 .env 를 깜빡해도 조용히 약한 값으로 뜬다."""
        text = (DEPLOY / 'compose.yaml').read_text()
        for secret in ('POSTGRES_PASSWORD', 'WAFERAI_SECRET_KEY'):
            self.assertRegex(text, r'\$\{' + secret + r':\?', f'{secret} 는 필수(:?)여야 합니다')

    def test_api_runs_in_production_mode(self):
        env = self.compose['services']['api']['environment']
        self.assertEqual(env['WAFERAI_ENV'], 'production')
        self.assertTrue(env['WAFERAI_DATABASE_URL'].startswith('postgresql+psycopg://'))

    def test_bind_mounted_nginx_files_exist(self):
        for volume in self.compose['services']['web']['volumes']:
            source = volume.split(':')[0]
            if source.startswith('./nginx/'):
                self.assertTrue((DEPLOY / source).is_file(), f'없는 파일을 붙입니다: {source}')

    def test_https_override_only_adds(self):
        override = load_compose('compose.https.yaml')
        self.assertEqual(set(override['services']), {'web'})
        self.assertEqual(override['services']['web']['ports'], ['${WEB_TLS_PORT:-443}:443'])


# ── Nginx ──────────────────────────────────────────────────────────────────────

def parse_like_image(site_conf: Path) -> dict:
    """공식 nginx 이미지와 같은 문맥(nginx.conf 의 http{} 안에서 conf.d 를 include)에서 파싱한다.

    파일 하나만 최상위로 읽으면 server 가 "허용되지 않는 위치"로 잡혀 의미 없는 오류가 난다.
    """
    import crossplane

    tmp = Path(tempfile.mkdtemp())
    etc = tmp / 'etc/nginx'
    (etc / 'conf.d').mkdir(parents=True)
    (etc / 'snippets').mkdir()
    relocate = lambda text: text.replace('/etc/nginx/', f'{etc}/')
    (etc / 'conf.d/default.conf').write_text(relocate(site_conf.read_text()))
    shutil.copy(NGINX / 'security-headers.conf', etc / 'snippets/security-headers.conf')
    (etc / 'nginx.conf').write_text(
        f'events {{}}\nhttp {{\n    include {etc}/conf.d/default.conf;\n}}\n')
    return crossplane.parse(str(etc / 'nginx.conf'), check_ctx=True, check_args=True)


def servers(payload: dict) -> list[dict]:
    site = next(config for config in payload['config']
                if config['file'].endswith('conf.d/default.conf'))
    return [directive for directive in site['parsed'] if directive['directive'] == 'server']


def header_names(block: list[dict], payload: dict) -> set[str]:
    """블록에 직접 적힌 add_header 와, include 로 끌어온 add_header 의 이름들."""
    names = set()
    for directive in block:
        if directive['directive'] == 'add_header':
            names.add(directive['args'][0].lower())
        elif directive['directive'] == 'include':
            for index in directive.get('includes', []):
                names |= header_names(payload['config'][index]['parsed'], payload)
    return names


def find(block: list[dict], name: str) -> list[dict]:
    return [directive for directive in block if directive['directive'] == name]


class NginxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import crossplane  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('crossplane 이 없습니다 (requirements-dev.txt)')
        cls.payloads = {conf.name: parse_like_image(conf) for conf in SITE_CONFIGS}

    def test_configs_parse_without_errors(self):
        for name, payload in self.payloads.items():
            errors = [error['error'] for config in payload['config'] for error in config['errors']]
            self.assertEqual(payload['status'], 'ok', f'{name}: {errors}')

    def test_locations_keep_security_headers(self):
        """location 에 add_header 가 하나라도 있으면 server 의 헤더를 물려받지 않는다."""
        for name, payload in self.payloads.items():
            for server in servers(payload):
                inherited = header_names(server['block'], payload)
                for location in find(server['block'], 'location'):
                    own = header_names(location['block'], payload)
                    if not own:
                        continue      # 자기 add_header 가 없으면 상속받는다
                    lost = inherited - own
                    self.assertEqual(lost, set(),
                                     f'{name} location {location["args"]}: 사라지는 헤더 {lost}')

    def test_security_headers_reach_the_app(self):
        for name, payload in self.payloads.items():
            app_servers = [s for s in servers(payload) if find(s['block'], 'root')]
            for server in app_servers:
                headers = header_names(server['block'], payload)
                for required in ('content-security-policy', 'x-content-type-options',
                                 'x-frame-options'):
                    self.assertIn(required, headers, f'{name}: {required} 없음')

    def test_upload_limit_exceeds_the_application_limit(self):
        from waferai.routers.wafer_routes import MAX_UPLOAD_BYTES

        units = {'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}
        for name, payload in self.payloads.items():
            for server in servers(payload):
                limit = find(server['block'], 'client_max_body_size')
                if not find(server['block'], 'root'):
                    continue      # 리다이렉트 전용 server
                value = limit[0]['args'][0].lower()
                size = int(value[:-1]) * units[value[-1]] if value[-1] in units else int(value)
                self.assertGreater(size, MAX_UPLOAD_BYTES,
                                   f'{name}: Nginx 상한 {value} 가 앱 상한보다 작거나 같습니다')

    def test_spa_routes_fall_back_to_index(self):
        for name, payload in self.payloads.items():
            for server in servers(payload):
                for location in find(server['block'], 'location'):
                    if location['args'] == ['/']:
                        try_files = find(location['block'], 'try_files')
                        if try_files:
                            self.assertEqual(try_files[0]['args'][-1], '/index.html', name)

    def test_upstream_is_resolved_per_request(self):
        """proxy_pass 에 상수 주소를 쓰면 api 가 재시작해 IP 가 바뀐 뒤 502 가 계속 난다."""
        for name, payload in self.payloads.items():
            for server in servers(payload):
                for location in find(server['block'], 'location'):
                    for proxy in find(location['block'], 'proxy_pass'):
                        self.assertTrue(proxy['args'][0].startswith('$'),
                                        f'{name}: proxy_pass 가 변수가 아닙니다')
                        self.assertTrue(find(server['block'], 'resolver'),
                                        f'{name}: 변수 proxy_pass 에는 resolver 가 필요합니다')


# ── 화면 · 스크립트 ────────────────────────────────────────────────────────────

class FrontendBuildTests(unittest.TestCase):
    def test_built_page_has_no_inline_scripts(self):
        """CSP 가 script-src 'self' 라 인라인 스크립트가 생기면 화면이 빈 채로 멈춘다."""
        index = ROOT / 'frontend/dist/index.html'
        if not index.is_file():
            self.skipTest('frontend/dist 가 없습니다 (npm --prefix frontend run build)')
        html = index.read_text()
        inline = [body for attrs, body in re.findall(r'<script([^>]*)>(.*?)</script>', html, re.S)
                  if 'src=' not in attrs and body.strip()]
        self.assertEqual(inline, [])


class SecretLeakTests(unittest.TestCase):
    def test_scripts_never_print_the_raw_database_url(self):
        """운영 접속 주소에는 DB 비밀번호가 들어 있다. 출력하려면 반드시 가려야 한다."""
        for script in sorted((ROOT / 'scripts').glob('*.py')):
            for number, line in enumerate(script.read_text().splitlines(), 1):
                if 'print(' in line and 'database_url' in line:
                    self.assertIn('hide_password=True', line,
                                  f'{script.name}:{number} 가 접속 주소를 그대로 출력합니다')


class ShellScriptTests(unittest.TestCase):
    def test_scripts_parse(self):
        for script in (DEPLOY / 'entrypoint.sh', DEPLOY / 'backup.sh'):
            result = subprocess.run(['sh', '-n', str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f'{script.name}: {result.stderr}')

    def test_scripts_are_executable(self):
        for script in (DEPLOY / 'entrypoint.sh', DEPLOY / 'backup.sh'):
            self.assertTrue(script.stat().st_mode & 0o111, f'{script.name} 에 실행 권한이 없습니다')


if __name__ == '__main__':
    unittest.main()
