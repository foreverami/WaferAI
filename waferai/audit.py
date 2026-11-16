"""보안 감사 로그 — 로그인 성공·실패, 잠금, 임시 비밀번호 발급, 승인·비활성화.

서버 로그(표준 출력)에 한 줄씩 남기고, audit_events 테이블에도 쌓아 관리자가 계정 화면에서
본다. DB 기록은 요청이 끝난 뒤(미들웨어에서) 따로 연 짧은 세션으로 쓴다. 요청의 세션에 넣으면
로그인 실패처럼 예외로 끝나 롤백되는 요청의 기록이 사라지고, 요청 도중 다른 세션으로 쓰면
SQLite 는 요청의 쓰기 잠금에 막힌다. 기록에 실패해도 요청은 막지 않는다.
비밀번호·토큰은 절대 적지 않는다.

형식: `audit <event> key=value ...` 한 줄. 예:
    audit login.locked employee_id=E0001 ip=10.0.0.5 seconds=60
"""
from __future__ import annotations

import logging
import sys

from fastapi import Request

logger = logging.getLogger('waferai.audit')


def install(app=None) -> None:
    """감사 로거에 핸들러를 단다. DB 기록은 auth.get_session 이 요청 끝에 쓴다(flush_pending).

    미들웨어로 쓰지 않는 이유: FastAPI 0.118 부터 yield 의존성의 정리 코드가 응답을 보낸 뒤에
    돈다. 미들웨어 시점에는 요청 세션이 아직 열려 있어 SQLite 가 잠금으로 막는다.
    """
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s audit %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def client_ip(request: Request | None) -> str:
    if request is None:
        return '-'
    # Nginx 가 X-Real-IP 를 넣어 준다. 직접 접속이면 소켓 주소.
    return request.headers.get('x-real-ip') or (request.client.host if request.client else '-')


def log(event: str, request: Request | None = None, **fields) -> None:
    ip = client_ip(request)
    parts = [event, f'ip={ip}']
    parts += [f'{key}={value}' for key, value in fields.items() if value is not None]
    logger.info(' '.join(parts))
    if request is not None:
        extra = {k: v for k, v in fields.items() if k not in ('employee_id', 'by') and v is not None}
        pending = getattr(request.state, 'audit_pending', None)
        if pending is None:
            pending = request.state.audit_pending = []
        pending.append({'event': event, 'employee_id': fields.get('employee_id'),
                        'actor': fields.get('by'), 'ip': ip, 'detail': extra or None})


def flush_pending(request: Request, session) -> None:
    """요청 세션의 커밋/롤백 뒤에 부른다 (auth.get_session). 쌓인 기록을 쓰고 비운다."""
    pending = getattr(request.state, 'audit_pending', None)
    if not pending:
        return
    from waferai.models import AuditEvent

    request.state.audit_pending = []
    try:
        session.add_all([AuditEvent(**item) for item in pending])
        session.commit()
    except Exception as error:                      # 감사 기록 실패가 요청을 막으면 안 된다
        session.rollback()
        logger.warning('audit.store_failed %s', error)

