"""로그인·로그아웃·내 정보·비밀번호 변경."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from waferai import audit
from waferai.auth import (AuthContext, check_password_policy, current_user, decode_token_payload,
                          get_auth, get_session, hash_password, verify_password)
from waferai.config import settings
from datetime import timedelta

from waferai.models import Role, User, utcnow
from waferai.schemas import LoginRequest, PasswordChange, SignupRequest, UserOut

router = APIRouter(prefix='/api/auth', tags=['auth'])

#: 존재하지 않는 사번과 틀린 비밀번호에 같은 응답 시간을 주기 위한 더미 해시.
#: 응답 시간 차이만으로 사번이 존재하는지 알아낼 수 있으면 안 된다.
_DUMMY_HASH = hash_password('not-a-real-password')

#: 연속 실패 잠금. 5회째부터 60초, 이후 실패마다 두 배로 늘어 최대 15분. 성공하면 0 으로 돌아간다.
#: 영구 잠금은 두지 않는다 — 공격자가 남의 사번을 일부러 잠가 업무를 막을 수 있기 때문이다.
#: IP 단위 제한은 Nginx(limit_req)가 따로 한다.
LOCK_AFTER_FAILURES = 5
LOCK_BASE_SECONDS = 60
LOCK_MAX_SECONDS = 15 * 60


def lock_seconds(failures: int) -> int:
    """failures 회째 실패 뒤 잠글 시간(초). 임계 미만이면 0."""
    if failures < LOCK_AFTER_FAILURES:
        return 0
    return min(LOCK_BASE_SECONDS * 2 ** (failures - LOCK_AFTER_FAILURES), LOCK_MAX_SECONDS)


def _set_cookie(response: Response, auth: AuthContext, token: str) -> None:
    response.set_cookie(
        key=auth.cookie_name, value=token, httponly=True,
        secure=settings.cookie_secure, samesite=settings.cookie_samesite,
        max_age=auth.token_minutes * 60, path='/')


@router.post('/login', response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response,
          auth: AuthContext = Depends(get_auth),
          session: Session = Depends(get_session)):
    started = time.perf_counter()
    user = session.get(User, body.employee_id)
    if user is not None and user.is_locked:
        # 잠긴 동안은 비밀번호가 맞아도 들이지 않고, 실패 횟수도 더 세지 않는다.
        audit.log('login.locked', request, employee_id=user.employee_id, seconds=user.lock_seconds_left)
        raise HTTPException(429, f'로그인 시도가 너무 많습니다. {user.lock_seconds_left}초 뒤에 다시 시도하세요')
    # 사용자가 없어도 해시 검증을 수행해 실패 경로의 비용을 맞춘다.
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)

    if not user or not ok:
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            seconds = lock_seconds(user.failed_logins)
            if seconds:
                user.locked_until = utcnow() + timedelta(seconds=seconds)
                audit.log('login.lock', request, employee_id=user.employee_id,
                          failures=user.failed_logins, seconds=seconds)
            session.add(user)
            session.commit()          # 예외로 끝나면 롤백되므로 실패 횟수는 여기서 확정한다
        audit.log('login.fail', request, employee_id=body.employee_id)
        # 어느 쪽이 틀렸는지 알려주지 않는다.
        elapsed = time.perf_counter() - started
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)
        raise HTTPException(401, '사번 또는 비밀번호가 올바르지 않습니다')
    if not user.is_active:
        # 비밀번호까지 맞은 본인에게만 상태를 알려준다. 사번만으로는 계정 존재 여부를 알 수 없다.
        audit.log('login.inactive', request, employee_id=user.employee_id)
        raise HTTPException(403, '승인 대기 중입니다. 관리자가 승인하면 로그인할 수 있습니다'
                                 if user.is_pending else '사용할 수 없는 계정입니다. 관리자에게 문의하세요')

    user.failed_logins = 0
    user.locked_until = None
    session.add(user)
    session.flush()
    audit.log('login.ok', request, employee_id=user.employee_id,
              must_change_password=user.must_change_password or None)
    _set_cookie(response, auth, auth.issue(user))
    return user


@router.post('/register', response_model=UserOut, status_code=201)
def register(body: SignupRequest, request: Request, session: Session = Depends(get_session)):
    """가입 신청. 비활성 계정으로 만들어지고, 관리자가 승인(activate)해야 로그인할 수 있다.

    권한은 engineer 로 고정이다. 승격은 관리자만 한다. 사번 · 이메일 중복은 409 로 알린다 —
    같은 사번으로 다시 신청하는 사람에게 '이미 신청됐다' 를 알려줘야 하므로 감추지 않는다.
    """
    if not getattr(request.app.state, 'allow_signup', True):
        raise HTTPException(403, '가입 신청을 받지 않습니다. 관리자에게 계정을 요청하세요')
    existing = session.get(User, body.employee_id)
    if existing is not None:
        raise HTTPException(409, '이미 신청된 사번입니다. 관리자의 승인을 기다리는 중이니 다시 신청하지 않아도 됩니다'
                                 if existing.is_pending else '이미 존재하는 사번입니다. 비밀번호를 잊었으면 관리자에게 문의하세요')
    if session.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(409, '이미 사용 중인 이메일입니다')
    try:
        check_password_policy(body.password, body.employee_id)
        user = User(employee_id=body.employee_id, name=body.name, email=body.email,
                    department=body.department, role=Role.ENGINEER.value,
                    password_hash=hash_password(body.password), is_active=False)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    session.add(user)
    session.flush()
    audit.log('signup', request, employee_id=user.employee_id)
    return user


@router.post('/logout')
def logout(request: Request, response: Response, auth: AuthContext = Depends(get_auth),
           session: Session = Depends(get_session)):
    """쿠키를 지우고, 그 토큰을 만료 때까지 거부 목록에 둔다. 복사해 둔 쿠키도 더는 못 쓴다."""
    token = request.cookies.get(auth.cookie_name)
    if token:
        auth.revoke(token, session)
        payload = decode_token_payload(token, auth.secret_key)
        audit.log('logout', request, employee_id=payload['sub'] if payload else None)
    response.delete_cookie(auth.cookie_name, path='/')
    return {'status': 'logged_out'}


@router.get('/me', response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post('/password', response_model=UserOut)
def change_password(body: PasswordChange, request: Request, response: Response,
                    auth: AuthContext = Depends(get_auth),
                    user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        audit.log('password.change_fail', request, employee_id=user.employee_id)
        raise HTTPException(401, '현재 비밀번호가 올바르지 않습니다')
    if body.current_password == body.new_password:
        raise HTTPException(422, '새 비밀번호가 기존과 같습니다')

    try:
        check_password_policy(body.new_password, user.employee_id)
        user.password_hash = hash_password(body.new_password)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    user.password_changed_at = utcnow()
    user.must_change_password = False
    # 토큰 세대를 올려 다른 기기 · 복사된 쿠키의 세션을 모두 끊는다. 이 기기는 아래서 새 토큰을 받는다.
    user.token_version = (user.token_version or 0) + 1
    session.add(user)
    session.flush()
    audit.log('password.changed', request, employee_id=user.employee_id)

    _set_cookie(response, auth, auth.issue(user))
    return user
