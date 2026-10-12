#!/bin/sh
# API 컨테이너 진입점. 스키마를 최신으로 맞춘 뒤 본 명령을 실행한다.
#
# alembic upgrade head 는 이미 최신이면 아무것도 하지 않으므로 매번 돌려도 된다.
# 배포 절차에 "마이그레이션 실행"을 따로 두면 빠뜨리기 쉽다.
set -eu

echo "[entrypoint] 스키마 확인 (alembic upgrade head)"
alembic upgrade head

echo "[entrypoint] 서버 시작: $*"
exec "$@"
