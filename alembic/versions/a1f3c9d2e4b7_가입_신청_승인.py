"""가입 신청 승인 — users.approved_at

Revision ID: a1f3c9d2e4b7
Revises: 8c41e07d2a95
Create Date: 2026-11-03 14:30:00

관리자가 승인(또는 직접 생성)한 시각. 비어 있고 비활성이면 가입 신청 뒤 승인 대기 상태다.
기존 계정은 모두 관리자가 만든 것이므로 created_at 으로 채운다. 그래야 이미 비활성화된
기존 계정이 '승인 대기' 로 보이지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d2e4b7'
down_revision: Union[str, Sequence[str], None] = '8c41e07d2a95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text('UPDATE users SET approved_at = created_at'))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('approved_at')
