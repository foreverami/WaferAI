"""Alembic 환경.

접속 주소는 alembic.ini 가 아니라 애플리케이션 설정(WAFERAI_DATABASE_URL)에서
가져온다. 두 곳에 적어두면 한쪽만 고쳐 엉뚱한 DB 에 마이그레이션이 적용된다.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from waferai.config import settings
from waferai.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    """마이그레이션 대상 DB.

    호출자가 Config 에 URL 을 넣었으면 그것을 쓴다(테스트, 스테이징 지정 등).
    비어 있을 때만 애플리케이션 설정에서 가져온다. 여기서 무조건 덮어쓰면
    `--x` 나 프로그램적 호출로 대상을 바꿀 수 없다.
    """
    configured = config.get_main_option('sqlalchemy.url', None)
    return configured or settings.database_url


config.set_main_option('sqlalchemy.url', database_url())
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={'paramstyle': 'named'},
        # SQLite 는 ALTER 지원이 좁아 배치 모드가 필요하다. Postgres 에서는 무해하다.
        render_as_batch=database_url().startswith('sqlite'),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.', poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=database_url().startswith('sqlite'),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
