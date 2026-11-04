"""비밀번호 해싱, JWT 발급·검증, 권한 확인.

토큰은 httpOnly 쿠키에 담는다. localStorage 에 두면 XSS 한 번에 탈취되는데,
httpOnly 쿠키는 자바스크립트가 읽지 못한다. 대신 CSRF 를 SameSite 로 막는다.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from waferai.models import RevokedToken, Role, User, utcnow

ALGORITHM = 'HS256'
MIN_PASSWORD_LENGTH = 8
#: 이 길이부터는 문자 종류를 따지지 않는다. 긴 문장형 비밀번호가 짧고 복잡한 것보다 낫다.
LONG_PASSWORD_LENGTH = 12
#: 임시 비밀번호로 로그인한 뒤 비밀번호를 바꾸기 전까지 허용되는 경로.
ALLOWED_BEFORE_PASSWORD_CHANGE = frozenset({'/api/auth/me', '/api/auth/password', '/api/auth/logout'})

_COMMON = {'password', 'passw0rd', 'qwertyui', 'qwerty123', '12345678', '123456789', '1234567890',
           'iloveyou', 'abcd1234', 'wafer123', 'waferai1', 'admin123', 'letmein1'}


def check_password_policy(password: str, employee_id: str | None = None) -> None:
    """비밀번호 규칙. 어기면 ValueError(한국어 메시지).

    8자 이상. 12자 미만이면 문자 종류(영문 · 숫자 · 한글 · 특수문자)가 둘 이상 섞여야 한다.
    사번과 같거나 사번을 품으면 안 되고, 흔한 비밀번호와 한 글자 반복은 거부한다.
    복잡도 규칙을 세게 걸면 사람은 'Password1!' 처럼 예측 가능한 패턴으로 도망간다. 그래서 길이를
    우선하고, 짧을 때만 섞임을 요구한다.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다')
    lowered = password.lower()
    if lowered in _COMMON or len(set(password)) == 1:
        raise ValueError('너무 흔하거나 단순한 비밀번호입니다')
    if employee_id and len(employee_id) >= 4 and employee_id.lower() in lowered:
        raise ValueError('비밀번호에 사번을 넣을 수 없습니다')
    if len(password) < LONG_PASSWORD_LENGTH:
        kinds = sum((any(c.isascii() and c.isalpha() for c in password),
                     any(c.isdigit() for c in password),
                     any(not c.isascii() and c.isalpha() for c in password),
                     any(not c.isalnum() for c in password)))
        if kinds < 2:
            raise ValueError(f'{LONG_PASSWORD_LENGTH}자 미만이면 영문 · 숫자 · 한글 · 특수문자 중 두 종류 이상을 섞으세요')


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


def create_access_token(employee_id: str, secret_key: str, minutes: int, version: int = 0) -> str:
    """jti 는 로그아웃 때 그 토큰만 끊기 위한 식별자, ver 는 사용자의 토큰 세대다."""
    now = datetime.now(timezone.utc)
    payload = {'sub': employee_id, 'iat': now, 'exp': now + timedelta(minutes=minutes),
               'jti': secrets.token_urlsafe(16), 'ver': version}
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_token_payload(token: str, secret_key: str) -> dict | None:
    """서명·만료가 유효하면 payload, 아니면 None. 알고리즘은 서버가 고정한다(헤더의 alg 를 믿지 않는다)."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if isinstance(payload.get('sub'), str) else None


def decode_access_token(token: str, secret_key: str) -> str | None:
    """유효하면 사번, 아니면 None. 만료·위조를 구분해 알려주지 않는다."""
    payload = decode_token_payload(token, secret_key)
    return payload['sub'] if payload else None


class AuthContext:
    """앱 기동 시 한 번 만들어 의존성으로 쓴다."""

    def __init__(self, secret_key: str, cookie_name: str, token_minutes: int):
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.token_minutes = token_minutes

    def issue(self, user: User) -> str:
        return create_access_token(user.employee_id, self.secret_key, self.token_minutes,
                                   user.token_version or 0)

    def revoke(self, token: str, session: Session) -> None:
        """이 토큰을 만료 때까지 거부 목록에 둔다. 지난 행은 이때 같이 치운다."""
        payload = decode_token_payload(token, self.secret_key)
        if not payload or 'jti' not in payload:
            return
        expires_at = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)
        session.merge(RevokedToken(jti=payload['jti'], expires_at=expires_at))
        session.query(RevokedToken).filter(RevokedToken.expires_at < utcnow()).delete()


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
    payload = decode_token_payload(token, auth.secret_key)
    if not payload:
        raise HTTPException(401, '세션이 만료되었거나 유효하지 않습니다')
    user = session.get(User, payload['sub'])
    if user is None or not user.is_active:
        raise HTTPException(401, '사용할 수 없는 계정입니다')
    # 비밀번호 변경·초기화 전에 발급된 토큰(세대가 다름)과 로그아웃한 토큰은 거부한다.
    if payload.get('ver', 0) != (user.token_version or 0):
        raise HTTPException(401, '비밀번호가 바뀌어 다시 로그인해야 합니다')
    if 'jti' in payload and session.get(RevokedToken, payload['jti']) is not None:
        raise HTTPException(401, '로그아웃된 세션입니다')
    if user.must_change_password and request.url.path not in ALLOWED_BEFORE_PASSWORD_CHANGE:
        raise HTTPException(403, '임시 비밀번호로 로그인했습니다. 계정 탭에서 비밀번호를 먼저 바꾸세요')
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
