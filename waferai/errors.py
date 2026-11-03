"""입력 검증 오류를 사람이 읽을 수 있는 한국어 한 줄로 바꾼다.

FastAPI 는 pydantic 검증 오류를 `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` 로
돌려준다. 화면은 이것을 그대로 보여 주면 "value is not a valid email address: ..." 같은 영어
원문이 뜬다. 여기서 항목 이름과 원인을 한국어로 바꿔 `{"detail": "이메일 형식이 올바르지 않습니다"}`
한 줄로 만든다. 화면 쪽 코드는 detail 이 문자열이면 그대로 보여 주므로 바꿀 것이 없다.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

#: 스키마 필드명 → 화면에 보이는 이름
FIELD_LABELS = {
    'employee_id': '사번', 'name': '이름', 'email': '이메일', 'department': '부서',
    'password': '비밀번호', 'current_password': '현재 비밀번호', 'new_password': '새 비밀번호',
    'role': '권한', 'label': '라벨', 'memo': '메모', 'rank': '순위', 'note': '사유',
    'confidence': '확신도 임계값', 'low_density': '정상 강제 판정 밀도',
    'high_density': 'Near-full 강제 판정 밀도', 'file': '파일',
}


def _label(error: dict) -> str:
    # loc 은 ('body', 'email') 처럼 위치부터 온다. 마지막 필드명만 쓴다.
    names = [part for part in error.get('loc', ()) if isinstance(part, str) and part != 'body']
    return FIELD_LABELS.get(names[-1], names[-1]) if names else '입력값'


def describe(error: dict) -> str:
    """pydantic 오류 하나를 한국어 한 문장으로."""
    label, kind, ctx = _label(error), error.get('type', ''), error.get('ctx') or {}
    if kind == 'missing':
        return f'{label}을(를) 입력하세요'
    if kind == 'string_too_short':
        return f'{label}은(는) {ctx.get("min_length")}자 이상이어야 합니다'
    if kind == 'string_too_long':
        return f'{label}은(는) {ctx.get("max_length")}자 이하여야 합니다'
    if kind == 'value_error' and 'email' in error.get('msg', '').lower():
        return f'{label} 형식이 올바르지 않습니다'
    if kind in ('greater_than_equal', 'less_than_equal', 'greater_than', 'less_than'):
        return f'{label} 값이 허용 범위를 벗어났습니다'
    if kind in ('enum', 'literal_error'):
        return f'{label} 값이 허용된 선택지가 아닙니다'
    if kind.endswith('_type') or kind.endswith('_parsing'):
        return f'{label} 형식이 올바르지 않습니다'
    return f'{label}: {error.get("msg", "올바르지 않습니다")}'


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        messages = []
        for error in exc.errors():
            message = describe(error)
            if message not in messages:
                messages.append(message)
        return JSONResponse(status_code=422, content={'detail': ' · '.join(messages)})
