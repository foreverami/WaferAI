"""테스트 공용 헬퍼.

모델 체크포인트를 매 테스트마다 올리면 느려서, 앱을 한 번 만들어 재사용하고
DB 만 테스트마다 비운다.

기본은 임시 SQLite 다. 운영과 같은 PostgreSQL 에서 돌리려면:
    WAFERAI_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db \
        python3 -m unittest discover -s tests
그 DB 의 테이블을 비우므로 운영 DB 를 가리키면 안 된다.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from waferai.auth import hash_password
from waferai.config import Settings
from waferai.image_adapter import encode_png, render_wafer_map
from waferai.models import Base, User

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / 'models/best_coatnet_model_optimized.pth'

ADMIN = {'employee_id': 'A0001', 'password': 'admin-pass-1234'}
SENIOR = {'employee_id': 'S0001', 'password': 'senior-pass-1234'}
ENGINEER = {'employee_id': 'E0001', 'password': 'engineer-pass-1234'}


def wafer_png(size: int = 224) -> bytes:
    """학습과 같은 색으로 렌더링한 웨이퍼 맵 PNG."""
    yy, xx = np.mgrid[0:45, 0:48]
    radius = np.sqrt(((yy - 22) / 22.5) ** 2 + ((xx - 23.5) / 24) ** 2)
    wafer_map = np.where(radius <= 1.0, 1, 0).astype(np.uint8)
    wafer_map[(radius < 0.35) & (wafer_map == 1)] = 2
    return encode_png(render_wafer_map(wafer_map, size))


SYNTHETIC_MAP = b'[[0,1,0],[1,2,1],[0,1,0]]'


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class ApiTestCase(unittest.TestCase):
    """로그인된 클라이언트를 제공하는 베이스 클래스."""

    client: TestClient

    @classmethod
    def setUpClass(cls):
        cls._folder = tempfile.TemporaryDirectory()
        database_url = (os.environ.get('WAFERAI_TEST_DATABASE_URL')
                        or f'sqlite:///{Path(cls._folder.name) / "test.db"}')
        from waferai.server import create_app

        config = Settings(secret_key='test-only-secret-key-at-least-32-bytes-long', env='development',
                          database_url=database_url)
        cls.client = TestClient(create_app(config, database_url=database_url))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls._folder.cleanup()

    def setUp(self):
        self.reset_users()
        self.client.cookies.clear()

    def reset_users(self):
        """사용자와 웨이퍼 기록을 비우고 기본 계정 3개를 다시 만든다."""
        factory = self.client.app.state.session_factory
        with factory() as session:
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != 'ai_model':          # 모델 등록은 기동 시 1회뿐
                    session.execute(table.delete())
            for account, role, name in ((ADMIN, 'admin', '관리자'),
                                        (SENIOR, 'senior_engineer', '수석'),
                                        (ENGINEER, 'engineer', '엔지니어')):
                session.add(User(employee_id=account['employee_id'], name=name,
                                 email=f"{account['employee_id']}@example.com",
                                 role=role,
                                 password_hash=hash_password(account['password'])))
            session.commit()

    def login(self, account: dict) -> None:
        response = self.client.post('/api/auth/login', json={
            'employee_id': account['employee_id'], 'password': account['password']})
        assert response.status_code == 200, response.text

    def logout(self) -> None:
        self.client.post('/api/auth/logout')
        self.client.cookies.clear()

    def upload(self, name: str = 'synthetic.json', payload: bytes = SYNTHETIC_MAP,
               content_type: str = 'application/json'):
        return self.client.post('/api/predict',
                                files={'file': (name, payload, content_type)})
