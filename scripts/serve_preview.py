"""화면 확인용 백엔드 — 임시 DB 에 테스트 계정 3개를 심고 127.0.0.1:8000 에 띄운다.

    python3 -m scripts.serve_preview             # 백엔드 (8000)
    npm --prefix frontend run dev                # 프론트엔드 (5173, /api 를 8000 으로 프록시)

화면 확인과 스크린샷(scripts/capture_screens.py)에 쓴다. 계정과 비밀번호는 tests/conftest.py
의 테스트 고정값이라 로컬 밖에서는 쓰면 안 된다. DB 와 히트맵은 임시 폴더에 두므로 서버를
끄면 사라지고, 개발 DB(data/)는 건드리지 않는다. 모델은 models/ 의 운영 모델을 그대로 쓴다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import uvicorn

from tests.conftest import ADMIN, ENGINEER, SENIOR
from waferai.auth import hash_password
from waferai.config import Settings
from waferai.db import create_all, create_db_engine, create_session_factory
from waferai.models import User
from waferai.server import create_app

HOST, PORT = '127.0.0.1', 8000
ACCOUNTS = ((ADMIN, 'admin', '관리자'), (SENIOR, 'senior_engineer', '수석'),
            (ENGINEER, 'engineer', '엔지니어'))


def seed(database_url: str) -> None:
    engine = create_db_engine(database_url)
    create_all(engine)
    with create_session_factory(engine)() as session:
        for account, role, name in ACCOUNTS:
            session.add(User(employee_id=account['employee_id'], name=name,
                             email=f"{account['employee_id']}@example.com", role=role,
                             password_hash=hash_password(account['password'])))
        session.commit()
    engine.dispose()


def main() -> None:
    folder = tempfile.TemporaryDirectory(prefix='waferai-preview-')
    database_url = f'sqlite:///{Path(folder.name) / "preview.db"}'
    seed(database_url)
    config = Settings(env='development', database_url=database_url,
                      secret_key='preview-only-secret-key-at-least-32-bytes-long',
                      heatmap_dir=str(Path(folder.name) / 'heatmaps'))
    print(f'미리보기 서버 http://{HOST}:{PORT} · 임시 DB {folder.name}')
    print('계정: ' + ', '.join(f"{account['employee_id']} ({role})" for account, role, _ in ACCOUNTS)
          + ' — 비밀번호는 tests/conftest.py')
    try:
        uvicorn.run(create_app(config, database_url=database_url), host=HOST, port=PORT,
                    log_level='warning')
    finally:
        folder.cleanup()


if __name__ == '__main__':
    main()
