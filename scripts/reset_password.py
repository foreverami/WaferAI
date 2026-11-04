"""비밀번호 초기화 CLI — 관리자 본인이 잊었을 때 서버에서 쓴다.

    python3 -m scripts.reset_password --employee-id 202104346

다른 사용자의 비밀번호는 관리자가 화면(계정 탭)에서 초기화한다. 이 명령은 그 관리자마저
비밀번호를 잊었을 때의 마지막 수단이다. 서버에 접속할 수 있는 사람만 쓸 수 있다.
새 비밀번호는 실행 중에 직접 입력한다(화면에 표시되지 않음). 인자로 받지 않는다 —
명령행 인자는 셸 히스토리와 ps 에 남는다.
"""
from __future__ import annotations

import argparse

from sqlalchemy.engine import make_url

from waferai.auth import hash_password
from waferai.config import settings
from waferai.db import create_db_engine, create_session_factory
from waferai.models import User, utcnow

from scripts.create_user import prompt_password


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 비밀번호 초기화')
    parser.add_argument('--employee-id', required=True)
    parser.add_argument('--database-url', default=settings.database_url)
    args = parser.parse_args()

    engine = create_db_engine(args.database_url)
    with create_session_factory(engine)() as session:
        user = session.get(User, args.employee_id)
        if user is None:
            raise SystemExit(f'계정이 없습니다: {args.employee_id}')
        print(f'{user.employee_id} ({user.name}, {user.role}) 의 새 비밀번호를 입력하세요.')
        user.password_hash = hash_password(prompt_password())
        user.password_changed_at = utcnow()
        user.token_version = (user.token_version or 0) + 1     # 살아 있는 세션은 모두 끊는다
        user.failed_logins = 0
        user.locked_until = None
        user.must_change_password = False                      # 본인이 직접 정한 비밀번호다
        session.add(user)
        session.commit()

    print(f'\n초기화 완료: {args.employee_id}')
    print(f'  DB: {make_url(args.database_url).render_as_string(hide_password=True)}')


if __name__ == '__main__':
    main()
