"""현재 모델 정의를 PostgreSQL 스키마 SQL 문서로 내보낸다.

    python3 -m scripts.export_schema_sql        # → docs/WaferAI_DB_schema_postgresql.sql

산출물 문서용이다. 운영 서버는 이 파일이 아니라 Alembic 마이그레이션으로 스키마를 만든다.
마이그레이션 결과와 모델 정의가 같다는 것은 tests/test_migrations.py 가 검사하므로, 모델에서
뽑은 이 파일은 `alembic upgrade head` 로 만든 DB 와 같은 스키마다. alembic_version 도 head 로
적어, 빈 DB 에 실행한 뒤 이후 마이그레이션을 그대로 이어 적용할 수 있다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from waferai.models import Base

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs/WaferAI_DB_schema_postgresql.sql'


def main() -> None:
    head = ScriptDirectory.from_config(Config(str(ROOT / 'alembic.ini'))).get_current_head()
    dialect = postgresql.dialect()
    tables = Base.metadata.sorted_tables
    lines = [
        '-- WaferAI 데이터베이스 스키마 (PostgreSQL 16)',
        f'-- 마이그레이션 head {head} 기준 최종 스키마 · {date.today().isoformat()} 생성 · 테이블 {len(tables)}개',
        '--',
        '-- 빈 DB 에 이 파일을 실행하면 `alembic upgrade head` 로 만든 DB 와 같은 스키마가 되고,',
        '-- alembic_version 도 head 로 기록되어 이후 마이그레이션을 그대로 이어 적용할 수 있다.',
        '--     psql -v ON_ERROR_STOP=1 -d <DB> -f WaferAI_DB_schema_postgresql.sql',
        '-- 운영 서버는 이 파일이 아니라 마이그레이션으로 스키마를 만든다 (deploy/entrypoint.sh).',
        '-- 다시 만들기: python3 -m scripts.export_schema_sql',
        '',
        'BEGIN;',
        '',
        'CREATE TABLE alembic_version (',
        '    version_num VARCHAR(32) NOT NULL,',
        '    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)',
        ');',
        '',
    ]
    for table in tables:
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip().replace('\t', '    ')
        lines += [ddl + ';', '']
        for index in sorted(table.indexes, key=lambda i: i.name):
            lines += [str(CreateIndex(index).compile(dialect=dialect)).strip() + ';', '']
    lines += [f"INSERT INTO alembic_version (version_num) VALUES ('{head}');", '', 'COMMIT;']
    OUT.write_text('\n'.join(line.rstrip() for part in lines for line in part.split('\n')) + '\n')
    print(f'{OUT.relative_to(ROOT)} — head {head} · 테이블 {len(tables)}개')


if __name__ == '__main__':
    main()
