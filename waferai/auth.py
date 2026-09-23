"""비밀번호 해싱, JWT 발급·검증, 권한 확인.

토큰은 httpOnly 쿠키에 담는다. localStorage 에 두면 XSS 한 번에 탈취되는데,
httpOnly 쿠키는 자바스크립트가 읽지 못한다. 대신 CSRF 를 SameSite 로 막는다.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from waferai.models import Role, User

ALGORITHM = 'HS256'
MIN_PASSWORD_LENGTH = 8


def _prehash(password: str) -> bytes:
    """bcrypt 는 72바이트에서 잘린다. SHA-256 으로 길이를 고정한 뒤 넘긴다.

    한글 비밀번호는 한 글자가 3바이트라 24자면 한도에 닿는다. 자르고 넘기면 그
    뒤는 검증에 쓰이지 않아 사실상 비밀번호가 짧아진다.
    """
    digest = hashlib.sha256(password.encode('utf-8')).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다')
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode('ascii')


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode('ascii'))
    except (ValueError, TypeError):
        return False


def create_access_token(employee_id: str, secret_key: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {'sub': employee_id, 'iat': now, 'exp': now + timedelta(minutes=minutes)}
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> str | None:
    """유효하면 사번, 아니면 None. 만료·위조를 구분해 알려주지 않는다."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get('sub')
    return subject if isinstance(subject, str) else None


class AuthContext:
    """앱 기동 시 한 번 만들어 의존성으로 쓴다."""

    def __init__(self, secret_key: str, cookie_name: str, token_minutes: int):
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.token_minutes = token_minutes

    def issue(self, user: User) -> str:
        return create_access_token(user.employee_id, self.secret_key, self.token_minutes)


def get_auth(request: Request) -> AuthContext:
    return request.app.state.auth


def get_session(request: Request):
    from waferai.db import session_scope

    yield from session_scope(request.app.state.session_factory)


def current_user(request: Request, auth: AuthContext = Depends(get_auth),
                 session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(auth.cookie_name)
    if not token:
        raise HTTPException(401, '로그인이 필요합니다')
    employee_id = decode_access_token(token, auth.secret_key)
    if not employee_id:
        raise HTTPException(401, '세션이 만료되었거나 유효하지 않습니다')
    user = session.get(User, employee_id)
    if user is None or not user.is_active:
        raise HTTPException(401, '사용할 수 없는 계정입니다')
    return user


def require_role(required: Role):
    """이 등급 이상만 통과시킨다.

    UI 에서 버튼을 감추는 것은 방어가 아니다. 개발자도구로 그냥 우회되므로
    서버에서도 반드시 막아야 한다.
    """
    def dependency(user: User = Depends(current_user)) -> User:
        if not user.role_enum.covers(required):
            raise HTTPException(403, f'권한이 부족합니다 (필요 등급: {required.value})')
        return user

    return dependency


require_engineer = require_role(Role.ENGINEER)
require_senior = require_role(Role.SENIOR_ENGINEER)
require_admin = require_role(Role.ADMIN)
