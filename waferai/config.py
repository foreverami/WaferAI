"""환경 설정.

값은 환경변수나 `.env` 로 주입한다. 운영에서 반드시 넣어야 하는 것:

    WAFERAI_SECRET_KEY    JWT 서명 키 — 없으면 운영 모드에서 기동을 거부한다
    WAFERAI_DATABASE_URL  postgresql+psycopg://... (미지정 시 로컬 SQLite)
    WAFERAI_ENV           production 이면 안전 점검을 강제한다
"""
from __future__ import annotations

import secrets
import warnings
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

#: HMAC-SHA256 서명 키의 최소 길이. RFC 7518 §3.2 권장값이며, PyJWT 도 이보다
#: 짧으면 경고한다. 짧은 키는 무차별 대입에 약해 토큰 위조로 이어진다.
MIN_SECRET_KEY_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='WAFERAI_', env_file='.env',
                                      env_file_encoding='utf-8', extra='ignore')

    env: str = 'development'

    # SQLite 는 개발·테스트 전용. 운영은 PostgreSQL 을 쓴다.
    database_url: str = f'sqlite:///{ROOT / "data/waferai.db"}'

    secret_key: str = ''
    access_token_minutes: int = 60 * 8          # 한 교대 근무
    cookie_name: str = 'waferai_session'
    cookie_secure: bool = False                 # HTTPS 뒤에서는 True
    cookie_samesite: str = 'lax'

    checkpoint_path: str = 'models/best_coatnet_model_optimized.pth'
    onnx_path: str = 'models/coatnet_wafer.onnx'
    backend: str = 'auto'
    device: str = 'cpu'                         # 배포 서버에 GPU 가 없다

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ('production', 'prod')

    def resolved_secret_key(self) -> str:
        """서명 키. 운영에서 비어 있으면 기동을 거부한다.

        개발 편의를 위해 임시 키를 만들어 쓰되, 그 키는 프로세스가 죽으면 사라지므로
        재시작 시 모든 세션이 무효가 된다. 운영에서 이런 키를 쓰면 배포할 때마다
        전원이 로그아웃되고, 더 나쁘게는 키가 소스에 박힐 위험이 있다.
        """
        if self.secret_key:
            if len(self.secret_key.encode()) < MIN_SECRET_KEY_BYTES:
                message = (f'WAFERAI_SECRET_KEY 가 너무 짧습니다 '
                           f'({len(self.secret_key.encode())}바이트, '
                           f'최소 {MIN_SECRET_KEY_BYTES}바이트).')
                if self.is_production:
                    raise RuntimeError(message)
                warnings.warn(message, stacklevel=2)
            return self.secret_key
        if self.is_production:
            raise RuntimeError(
                'WAFERAI_SECRET_KEY 가 설정되지 않았습니다. 운영에서는 필수입니다.\n'
                '  생성: python3 -c "import secrets; print(secrets.token_urlsafe(48))"')
        warnings.warn('WAFERAI_SECRET_KEY 가 없어 임시 키를 만들어 씁니다. '
                      '재시작하면 모든 세션이 무효가 됩니다.', stacklevel=2)
        return secrets.token_urlsafe(48)

    def check_production_safety(self) -> list[str]:
        """운영 기동 전 점검. 문제를 문자열 목록으로 돌려준다."""
        problems = []
        if not self.is_production:
            return problems
        if not self.secret_key:
            problems.append('WAFERAI_SECRET_KEY 가 비어 있습니다')
        elif len(self.secret_key.encode()) < MIN_SECRET_KEY_BYTES:
            problems.append(f'WAFERAI_SECRET_KEY 가 {MIN_SECRET_KEY_BYTES}바이트 미만입니다')
        if self.database_url.startswith('sqlite'):
            problems.append('운영에서 SQLite 를 쓰고 있습니다. PostgreSQL 로 바꾸세요')
        if not self.cookie_secure:
            problems.append('WAFERAI_COOKIE_SECURE 가 꺼져 있습니다. HTTPS 뒤에서는 켜세요')
        return problems


settings = Settings()
