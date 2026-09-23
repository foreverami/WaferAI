"""계정 관리(admin)와 판정 임계값(senior 이상)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waferai.auth import get_session, hash_password, require_admin, require_senior
from waferai.decision import Thresholds
from waferai.models import Setting, THRESHOLDS_KEY, User, utcnow
from waferai.routers.wafer_routes import load_thresholds
from waferai.schemas import ThresholdsIn, ThresholdsOut, UserCreate, UserOut

router = APIRouter(prefix='/api', tags=['admin'])


@router.get('/users', response_model=list[UserOut])
def list_users(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    return list(session.execute(select(User).order_by(User.employee_id)).scalars())


@router.post('/users', response_model=UserOut, status_code=201)
def create_user(body: UserCreate, session: Session = Depends(get_session),
                _: User = Depends(require_admin)):
    if session.get(User, body.employee_id):
        raise HTTPException(409, '이미 존재하는 사번입니다')
    try:
        user = User(employee_id=body.employee_id, name=body.name, email=body.email,
                    department=body.department, role=body.role,
                    password_hash=hash_password(body.password))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, '이미 사용 중인 이메일입니다') from error
    return user


@router.post('/users/{employee_id}/deactivate', response_model=UserOut)
def deactivate_user(employee_id: str, session: Session = Depends(get_session),
                    admin: User = Depends(require_admin)):
    if employee_id == admin.employee_id:
        # 마지막 관리자가 자기 계정을 잠그면 아무도 복구할 수 없다.
        raise HTTPException(422, '자기 계정은 비활성화할 수 없습니다')
    user = session.get(User, employee_id)
    if user is None:
        raise HTTPException(404, '계정이 없습니다')
    user.is_active = False
    session.add(user)
    session.flush()
    return user


@router.get('/settings/thresholds', response_model=ThresholdsOut)
def get_thresholds(session: Session = Depends(get_session),
                   _: User = Depends(require_senior)):
    row = session.get(Setting, THRESHOLDS_KEY)
    thresholds = load_thresholds(session)
    return ThresholdsOut(**thresholds.as_dict(),
                         updated_at=row.updated_at if row else None,
                         updated_by=row.updated_by if row else None)


@router.put('/settings/thresholds', response_model=ThresholdsOut)
def put_thresholds(body: ThresholdsIn, session: Session = Depends(get_session),
                   user: User = Depends(require_senior)):
    try:
        thresholds = Thresholds(low_density=body.low_density,
                                high_density=body.high_density,
                                confidence=body.confidence)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    row = session.get(Setting, THRESHOLDS_KEY)
    if row is None:
        row = Setting(key=THRESHOLDS_KEY, value=thresholds.as_dict())
    else:
        row.value = thresholds.as_dict()
    row.updated_at = utcnow()
    row.updated_by = user.employee_id
    session.add(row)
    session.flush()
    return ThresholdsOut(**thresholds.as_dict(), updated_at=row.updated_at,
                         updated_by=row.updated_by)
