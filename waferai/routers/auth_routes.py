"""로그인·로그아웃·내 정보·비밀번호 변경."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from waferai.auth import (AuthContext, current_user, get_auth, get_session,
                          hash_password, verify_password)
from waferai.config import settings
from waferai.models import User, utcnow
from waferai.schemas import LoginRequest, PasswordChange, UserOut

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

    if not user or not ok or not user.is_active:
        # 어느 쪽이 틀렸는지 알려주지 않는다.
        elapsed = time.perf_counter() - started
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)
        raise HTTPException(401, '사번 또는 비밀번호가 올바르지 않습니다')

    _set_cookie(response, auth, auth.issue(user))
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
