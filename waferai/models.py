"""데이터베이스 모델.

ERD 문서의 7테이블 중 Vision 파이프라인에 해당하는 것만 만든다. Sensor AI 쪽
(equipment, sensor_alert, unified_report)과 retrain_job 은 이번 학기 범위 밖이라
뺐다. 나중에 붙일 때는 Alembic 마이그레이션으로 추가한다.

ERD 에 없던 `users` 를 추가했다. UIUX 문서 화면 8 이 사번·부서·권한을 요구하는데
ERD 에는 사용자 테이블이 없었고, review_result.reviewer 가 자유 문자열이라 누가
검토했는지 추적할 수 없었다. 여기서는 FK 로 묶는다.

SQLite(개발·테스트)와 PostgreSQL(운영) 양쪽에서 같은 스키마가 돌아가야 하므로
JSONB 같은 Postgres 전용 타입은 쓰지 않는다.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    """UIUX 문서 화면 8 의 권한 등급."""

    ENGINEER = 'engineer'                # 조회 + 검토
    SENIOR_ENGINEER = 'senior_engineer'  # + 임계값 변경
    ADMIN = 'admin'                      # + 계정 관리, 모델 배포

    @property
    def rank(self) -> int:
        return {'engineer': 0, 'senior_engineer': 1, 'admin': 2}[self.value]

    def covers(self, required: 'Role') -> bool:
        return self.rank >= required.rank


class User(Base):
    __tablename__ = 'users'

    # 사번이 PK. UIUX 문서의 "사번은 변경할 수 없습니다" 를 스키마 차원에서 굳힌다.
    employee_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(120), unique=True)
    department: Mapped[str | None] = mapped_column(String(50), default=None)
    role: Mapped[str] = mapped_column(String(20), default=Role.ENGINEER.value)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                          default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reviews: Mapped[list['ReviewResult']] = relationship(back_populates='reviewer')

    @property
    def role_enum(self) -> Role:
        return Role(self.role)


class AiModel(Base):
    """배포된 모델 버전. 어느 가중치가 어떤 예측을 냈는지 추적한다."""

    __tablename__ = 'ai_model'

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(20))
    # 모델 파일의 SHA-256. 같은 파일이 두 번 등록되지 않게 막는다.
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    backend: Mapped[str] = mapped_column(String(20))
    val_accuracy: Mapped[float | None] = mapped_column(Float, default=None)
    epoch: Mapped[int | None] = mapped_column(Integer, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    results: Mapped[list['WaferResult']] = relationship(back_populates='model')


class WaferResult(Base):
    """웨이퍼 한 장의 추론 결과. 원래 예측은 절대 덮어쓰지 않는다.

    엔지니어가 라벨을 고쳐도 여기 값은 그대로 두고 review_result 에 따로 쌓는다.
    나중에 모델 성능을 되짚으려면 AI 가 원래 뭐라고 했는지가 남아 있어야 한다.
    """

    __tablename__ = 'wafer_result'

    wafer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    filename: Mapped[str | None] = mapped_column(Text, default=None)
    input_type: Mapped[str] = mapped_column(String(10))          # array | image
    input_info: Mapped[dict | None] = mapped_column(JSON, default=None)
    wafer_map: Mapped[list] = mapped_column(JSON)                # 0/1/2 맵
    probabilities: Mapped[dict] = mapped_column(JSON)

    final_class: Mapped[str] = mapped_column(String(20))
    decision_path: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[float] = mapped_column(Float)
    defect_ratio: Mapped[float] = mapped_column(Float)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)

    model_id: Mapped[int] = mapped_column(ForeignKey('ai_model.model_id'))
    uploaded_by: Mapped[str | None] = mapped_column(
        ForeignKey('users.employee_id'), default=None)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Phase 3 에서 Grad-CAM 을 붙일 자리. 지연 생성이라 처음엔 비어 있다.
    heatmap_path: Mapped[str | None] = mapped_column(Text, default=None)

    model: Mapped[AiModel] = relationship(back_populates='results')
    reviews: Mapped[list['ReviewResult']] = relationship(
        back_populates='wafer', cascade='all, delete-orphan',
        order_by='ReviewResult.review_id.desc()')

    @property
    def latest_review(self) -> 'ReviewResult | None':
        return self.reviews[0] if self.reviews else None


class ReviewResult(Base):
    """엔지니어 검토 이력. 같은 웨이퍼를 여러 번 검토할 수 있다."""

    __tablename__ = 'review_result'

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wafer_id: Mapped[str] = mapped_column(ForeignKey('wafer_result.wafer_id'))
    final_class: Mapped[str] = mapped_column(String(20))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.employee_id'))
    review_memo: Mapped[str] = mapped_column(Text, default='')
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    wafer: Mapped[WaferResult] = relationship(back_populates='reviews')
    reviewer: Mapped[User] = relationship(back_populates='reviews')


class Setting(Base):
    """운영 중 바뀌는 설정값. 판정 임계값이 여기 들어간다.

    UIUX 문서 화면 6·7 의 슬라이더가 이 테이블을 고친다. 코드에 박아두면 그 화면을
    만들 수 없다.
    """

    __tablename__ = 'settings'
    __table_args__ = (UniqueConstraint('key', name='uq_settings_key'),)

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey('users.employee_id'), default=None)


THRESHOLDS_KEY = 'decision_thresholds'
