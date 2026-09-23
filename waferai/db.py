"""데이터베이스 엔진과 세션.

SQLite(개발·테스트)와 PostgreSQL(운영)을 같은 코드로 다룬다. SQLite 에서만
필요한 설정이 두 가지 있어 여기서 분기한다.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from waferai.models import Base


def create_db_engine(database_url: str, echo: bool = False) -> Engine:
    kwargs: dict = {'echo': echo, 'future': True}

    if database_url.startswith('sqlite'):
        # FastAPI 의 스레드풀에서 같은 연결을 쓰므로 스레드 검사를 끈다.
        kwargs['connect_args'] = {'check_same_thread': False}
        path = database_url.split('///', 1)[-1]
        if path and path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    else:
        # 운영: 끊긴 연결을 미리 걸러내고 커넥션 수를 서버 사양에 맞춰 묶는다.
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=5)

    engine = create_engine(database_url, **kwargs)

    if database_url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def _enable_foreign_keys(dbapi_connection, _record):
            # SQLite 는 외래키를 기본으로 끄고 있다. 켜지 않으면 PostgreSQL 에서만
            # 터지는 참조 무결성 버그를 개발 중에 못 잡는다.
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """개발·테스트용 스키마 생성. 운영은 Alembic 마이그레이션을 쓴다."""
    Base.metadata.create_all(engine)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """요청 하나에 세션 하나. 예외가 나면 롤백한다."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
