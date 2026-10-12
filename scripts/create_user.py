"""계정 생성 CLI — 첫 관리자를 만들 때 쓴다.

    python3 -m scripts.create_user --employee-id 202104346 --name 조원곤 \
        --email me@example.com --role admin

비밀번호는 인자로 받지 않는다. 명령행 인자는 셸 히스토리와 프로세스 목록(ps)에
그대로 남기 때문이다. 대신 실행 중에 직접 입력받는다(화면에 표시되지 않음).
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.engine import make_url

from waferai.auth import hash_password
from waferai.config import settings
from waferai.db import create_all, create_db_engine, create_session_factory
from waferai.models import Role, User

MIN_LENGTH = 8


def prompt_password() -> str:
    """두 번 입력받아 대조한다. 값은 어디에도 기록하지 않는다."""
    for _ in range(3):
        first = getpass.getpass('비밀번호: ')
        if len(first) < MIN_LENGTH:
            print(f'  {MIN_LENGTH}자 이상이어야 합니다.', file=sys.stderr)
            continue
        if first != getpass.getpass('비밀번호 확인: '):
            print('  두 입력이 다릅니다.', file=sys.stderr)
            continue
        return first
    raise SystemExit('비밀번호를 설정하지 못했습니다.')


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 계정 생성')
    parser.add_argument('--employee-id', required=True, help='사번 (PK, 변경 불가)')
    parser.add_argument('--name', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--department', default=None)
    parser.add_argument('--role', default=Role.ENGINEER.value,
                        choices=[role.value for role in Role])
    parser.add_argument('--database-url', default=settings.database_url)
    args = parser.parse_args()

    engine = create_db_engine(args.database_url)
    create_all(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        if session.get(User, args.employee_id):
            raise SystemExit(f'이미 존재하는 사번입니다: {args.employee_id}')
        if session.execute(select(User).where(User.email == args.email)).scalar_one_or_none():
            raise SystemExit(f'이미 사용 중인 이메일입니다: {args.email}')

        password = prompt_password()
        session.add(User(employee_id=args.employee_id, name=args.name, email=args.email,
                         department=args.department, role=args.role,
                         password_hash=hash_password(password)))
        session.commit()

    print(f'\n생성 완료: {args.employee_id} ({args.name}, {args.role})')
    # 운영 접속 주소에는 DB 비밀번호가 들어 있다. 그대로 찍으면 터미널 기록과 로그에 남는다.
    print(f'  DB: {make_url(args.database_url).render_as_string(hide_password=True)}')


if __name__ == '__main__':
    main()
