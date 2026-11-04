"""보안 감사 로그 — 로그인 성공·실패, 잠금, 임시 비밀번호 발급, 승인·비활성화.

별도 테이블 대신 서버 로그(표준 출력)에 한 줄씩 남긴다. Docker 에서는 `docker compose logs api`
로 보고, 로그 수집기가 있으면 그대로 넘기면 된다. 비밀번호·토큰은 절대 적지 않는다.

형식: `audit <event> key=value ...` 한 줄. 예:
    audit login.locked employee_id=E0001 ip=10.0.0.5 seconds=60
"""
from __future__ import annotations

import logging
import sys

from fastapi import Request

logger = logging.getLogger('waferai.audit')


def install() -> None:
    """감사 로거에 핸들러를 단다. uvicorn 은 자기 로거만 설정하므로 우리 것은 직접 단다."""
    if logger.handlers:
        return
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
    parts = [event, f'ip={client_ip(request)}']
    parts += [f'{key}={value}' for key, value in fields.items() if value is not None]
    logger.info(' '.join(parts))
