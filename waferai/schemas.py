"""API 요청·응답 스키마.

모두 모듈 최상위에 둔다. `from __future__ import annotations` 로 애노테이션이
문자열이 되기 때문에, FastAPI 가 모듈 전역에서 이름을 찾을 수 있어야 한다.
함수 안에 정의하면 해석에 실패해 본문이 쿼리 파라미터로 취급된다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from waferai.backends import CLASSES

ClassName = Literal[tuple(CLASSES)]      # type: ignore[valid-type]
RoleName = Literal['engineer', 'senior_engineer', 'admin']


class LoginRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserCreate(BaseModel):
    employee_id: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    department: str | None = Field(default=None, max_length=50)
    role: RoleName = 'engineer'
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: str
    name: str
    email: str
    department: str | None
    role: str
    is_active: bool
    password_changed_at: datetime


class ReviewRequest(BaseModel):
    label: ClassName
    memo: str = Field(default='', max_length=2000)


class ApproveRequest(BaseModel):
    """AI 순위를 그대로 확정한다. rank=1 은 1순위 승인, rank=2 는 2순위 수정."""

    rank: int = Field(default=1, ge=1, le=9)
    memo: str = Field(default='', max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: int
    final_class: str
    reviewer_id: str
    review_memo: str
    reviewed_at: datetime


class WaferSummary(BaseModel):
    """목록용. 맵 전체는 무거우니 빼고 보낸다."""

    model_config = ConfigDict(from_attributes=True)

    wafer_id: str
    filename: str | None
    input_type: str
    final_class: str
    decision_path: str
    confidence: float
    defect_ratio: float
    requires_human_review: bool
    processed_at: datetime
    uploaded_by: str | None
    latest_review: ReviewOut | None = None


class WaferDetail(WaferSummary):
    wafer_map: list
    probabilities: dict
    input_info: dict | None
    reviews: list[ReviewOut] = Field(default_factory=list)
    model_version: str | None = None
    heatmap_path: str | None = None


class ThresholdsIn(BaseModel):
    """None 은 해당 규칙을 끈다는 뜻이다."""

    low_density: float | None = Field(default=None, ge=0.0, le=1.0)
    high_density: float | None = Field(default=0.80, ge=0.0, le=1.0)
    confidence: float = Field(default=0.80, ge=0.0, le=1.0)


class ThresholdsOut(ThresholdsIn):
    updated_at: datetime | None = None
    updated_by: str | None = None
