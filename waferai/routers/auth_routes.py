"""로그인·로그아웃·내 정보·비밀번호 변경."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from waferai.auth import (AuthContext, current_user, get_auth, get_session,
                          hash_password, verify_password)
from waferai.config import settings
from waferai.models import Role, User, utcnow
from waferai.schemas import LoginRequest, PasswordChange, SignupRequest, UserOut

router = APIRouter(prefix='/api/auth', tags=['auth'])

#: 존재하지 않는 사번과 틀린 비밀번호에 같은 응답 시간을 주기 위한 더미 해시.
#: 응답 시간 차이만으로 사번이 존재하는지 알아낼 수 있으면 안 된다.
_DUMMY_HASH = hash_password('not-a-real-password')


def _set_cookie(response: Response, auth: AuthContext, token: str) -> None:
    response.set_cookie(
        key=auth.cookie_name, value=token, httponly=True,
        secure=settings.cookie_secure, samesite=settings.cookie_samesite,
        max_age=auth.token_minutes * 60, path='/')


@router.post('/login', response_model=UserOut)
def login(body: LoginRequest, response: Response,
          auth: AuthContext = Depends(get_auth),
          session: Session = Depends(get_session)):
    started = time.perf_counter()
    user = session.get(User, body.employee_id)
    # 사용자가 없어도 해시 검증을 수행해 실패 경로의 비용을 맞춘다.
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)

    if not user or not ok:
        # 어느 쪽이 틀렸는지 알려주지 않는다.
        elapsed = time.perf_counter() - started
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)
        raise HTTPException(401, '사번 또는 비밀번호가 올바르지 않습니다')
    if not user.is_active:
        # 비밀번호까지 맞은 본인에게만 상태를 알려준다. 사번만으로는 계정 존재 여부를 알 수 없다.
        raise HTTPException(403, '승인 대기 중입니다. 관리자가 승인하면 로그인할 수 있습니다'
                                 if user.is_pending else '사용할 수 없는 계정입니다. 관리자에게 문의하세요')

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
    if session.get(User, body.employee_id):
        raise HTTPException(409, '이미 존재하는 사번입니다')
    if session.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(409, '이미 사용 중인 이메일입니다')
    try:
        user = User(employee_id=body.employee_id, name=body.name, email=body.email,
                    department=body.department, role=Role.ENGINEER.value,
                    password_hash=hash_password(body.password), is_active=False)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    session.add(user)
    session.flush()
    return user


@router.post('/logout')
def logout(response: Response, auth: AuthContext = Depends(get_auth)):
    response.delete_cookie(auth.cookie_name, path='/')
    return {'status': 'logged_out'}


@router.get('/me', response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post('/password', response_model=UserOut)
def change_password(body: PasswordChange, response: Response,
                    auth: AuthContext = Depends(get_auth),
                    user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, '현재 비밀번호가 올바르지 않습니다')
    if body.current_password == body.new_password:
        raise HTTPException(422, '새 비밀번호가 기존과 같습니다')

    try:
        user.password_hash = hash_password(body.new_password)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    user.password_changed_at = utcnow()
    session.add(user)
    session.flush()

    # 비밀번호가 바뀌었으니 새 토큰을 발급한다.
    _set_cookie(response, auth, auth.issue(user))
    return user
