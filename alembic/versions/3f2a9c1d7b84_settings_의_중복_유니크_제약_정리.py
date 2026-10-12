"""settings 의 중복 유니크 제약 정리

Revision ID: 3f2a9c1d7b84
Revises: 191435d4e798
Create Date: 2026-10-12 18:10:52.904239

초기 스키마가 settings.key 에 기본키와 유니크 제약(uq_settings_key)을 둘 다 걸었다.
기본키가 이미 유일성을 보장하므로 유니크는 중복이다. 문제는 DB 마다 결과가 달랐다는 점이다.

  SQLite      기본키(이름 없음) + 유니크 uq_settings_key — 둘 다 남는다
  PostgreSQL  CREATE TABLE 단계에서 중복 제약을 하나로 합쳐, 기본키에
              uq_settings_key 라는 이름을 붙이고 유니크는 만들지 않는다

그래서 PostgreSQL 에서는 모델(유니크 있음)과 DB(유니크 없음)가 영원히 어긋나
autogenerate 가 매번 가짜 변경을 만들었다. 더 위험하게는, 누군가 이름만 보고
"DROP CONSTRAINT uq_settings_key" 로 정리하면 PostgreSQL 에서는 기본키가 지워진다.

여기서는 이름이 아니라 실제 제약의 종류를 확인하고 정리한다.
  * 별도의 유니크 제약이 있으면(SQLite) → 지운다
  * 기본키가 uq_settings_key 라는 이름을 달고 있으면(PostgreSQL) → settings_pkey 로 이름만 바꾼다
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f2a9c1d7b84'
down_revision: Union[str, Sequence[str], None] = '191435d4e798'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'settings'
REDUNDANT = 'uq_settings_key'
CANONICAL_PK = 'settings_pkey'      # PostgreSQL 이 이름 없는 기본키에 붙이는 기본 이름


def _state():
    inspector = sa.inspect(op.get_bind())
    uniques = {constraint['name'] for constraint in inspector.get_unique_constraints(TABLE)}
    primary = inspector.get_pk_constraint(TABLE).get('name')
    return uniques, primary


def upgrade() -> None:
    uniques, primary = _state()

    if REDUNDANT in uniques:
        # SQLite 는 ALTER TABLE 로 제약을 못 지워 batch 모드가 표를 다시 만든다.
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(REDUNDANT, type_='unique')

    if primary == REDUNDANT:
        # 기본키 자체는 그대로 두고 오해를 부르는 이름만 바꾼다.
        op.execute(sa.text(f'ALTER TABLE {TABLE} RENAME CONSTRAINT {REDUNDANT} TO {CANONICAL_PK}'))


def downgrade() -> None:
    """초기 스키마를 적용했을 때 각 DB 에 생겼던 상태로 되돌린다."""
    _, primary = _state()

    if op.get_bind().dialect.name == 'postgresql':
        if primary == CANONICAL_PK:
            op.execute(sa.text(
                f'ALTER TABLE {TABLE} RENAME CONSTRAINT {CANONICAL_PK} TO {REDUNDANT}'))
        return

    with op.batch_alter_table(TABLE) as batch:
        batch.create_unique_constraint(REDUNDANT, ['key'])
