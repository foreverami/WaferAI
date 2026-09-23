"""마이그레이션이 모델과 어긋나지 않는지 검증한다.

모델만 고치고 마이그레이션을 만들지 않으면, 개발에서는 create_all 이 알아서
만들어줘서 멀쩡해 보이지만 운영에서는 컬럼이 없어 터진다. 이 테스트가 그 간극을
배포 전에 잡는다.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from waferai.models import Base

ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = ROOT / 'alembic.ini'

EXPECTED_TABLES = {'users', 'ai_model', 'wafer_result', 'review_result', 'settings'}


def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option('script_location', str(ROOT / 'alembic'))
    config.set_main_option('sqlalchemy.url', database_url)
    return config


@unittest.skipUnless(ALEMBIC_INI.is_file(), 'alembic.ini 가 없습니다')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.database_url = f'sqlite:///{Path(self._folder.name) / "migrate.db"}'
        self.config = alembic_config(self.database_url)

    def test_upgrade_creates_every_table(self):
        command.upgrade(self.config, 'head')
        tables = set(inspect(create_engine(self.database_url)).get_table_names())
        self.assertTrue(EXPECTED_TABLES.issubset(tables),
                        f'누락된 테이블: {EXPECTED_TABLES - tables}')

    def test_migration_matches_models(self):
        """마이그레이션을 올린 스키마와 모델 정의가 일치해야 한다.

        차이가 나오면 모델을 고치고 마이그레이션을 만들지 않았다는 뜻이다:
            python3 -m alembic revision --autogenerate -m "설명"
        """
        command.upgrade(self.config, 'head')
        engine = create_engine(self.database_url)
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={'compare_type': True})
            differences = compare_metadata(context, Base.metadata)

        self.assertEqual(differences, [],
                         '모델과 마이그레이션이 어긋납니다. 새 마이그레이션을 생성하세요:\n'
                         f'  {differences}')

    def test_downgrade_removes_every_table(self):
        """되돌릴 수 없는 마이그레이션은 사고가 났을 때 손을 못 쓴다."""
        command.upgrade(self.config, 'head')
        command.downgrade(self.config, 'base')
        tables = set(inspect(create_engine(self.database_url)).get_table_names())
        self.assertEqual(tables & EXPECTED_TABLES, set())


if __name__ == '__main__':
    unittest.main()
