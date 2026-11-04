"""로그인 보호 — 토큰 세대, 연속 실패 잠금, 임시 비밀번호 강제 변경, 로그아웃 토큰 거부 목록

Revision ID: b7d2e4f6a8c1
Revises: a1f3c9d2e4b7
Create Date: 2026-11-04 10:00:00

users.token_version   비밀번호 변경·초기화 때 올려 이전 토큰을 전부 무효화한다.
users.failed_logins   연속 로그인 실패 횟수. 5회부터 잠근다.
users.locked_until    잠금 해제 시각.
users.must_change_password  임시 비밀번호로 로그인한 상태. 바꾸기 전엔 다른 API 를 못 쓴다.
revoked_tokens        로그아웃한 토큰(jti). 만료 때까지만 들고 있다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f6a8c1'
down_revision: Union[str, Sequence[str], None] = 'a1f3c9d2e4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('failed_logins', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    op.create_table(
        'revoked_tokens',
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('jti'),
    )
    op.create_index('ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_revoked_tokens_expires_at', table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('must_change_password')
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_logins')
        batch_op.drop_column('token_version')
