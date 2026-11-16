"""감사 기록 — audit_events

Revision ID: c4e8a1b3d5f7
Revises: b7d2e4f6a8c1
Create Date: 2026-11-16 10:00:00

로그인 성공 · 실패 · 잠금, 가입 승인, 임시 비밀번호 발급 등을 관리자가 화면에서 볼 수 있게
DB 에 쌓는다. 서버 로그에는 전처럼 같은 줄이 남는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1b3d5f7'
down_revision: Union[str, Sequence[str], None] = 'b7d2e4f6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_events',
        sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('employee_id', sa.String(length=40), nullable=True),
        sa.Column('actor', sa.String(length=40), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index('ix_audit_events_at', 'audit_events', ['at'])
    op.create_index('ix_audit_events_event', 'audit_events', ['event'])
    op.create_index('ix_audit_events_employee_id', 'audit_events', ['employee_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_events_employee_id', table_name='audit_events')
    op.drop_index('ix_audit_events_event', table_name='audit_events')
    op.drop_index('ix_audit_events_at', table_name='audit_events')
    op.drop_table('audit_events')
