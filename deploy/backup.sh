#!/bin/sh
# PostgreSQL 백업. deploy/ 에서 실행한다:  ./backup.sh
# 매일 돌리려면 crontab:  0 3 * * * cd /경로/deploy && ./backup.sh >> backups/backup.log 2>&1
#
# 복원:
#   docker compose exec -T db pg_restore -U waferai -d waferai --clean --if-exists \
#       < backups/waferai-YYYYMMDD-HHMMSS.dump
set -eu
cd "$(dirname "$0")"

KEEP=14
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
target="backups/waferai-$stamp.dump"
partial="backups/.waferai-$stamp.dump.partial"

# 중간에 실패하면 반쪽짜리 파일이 정상 백업처럼 남지 않도록, 임시 이름으로 쓰고 끝나면 옮긴다.
trap 'rm -f "$partial"' EXIT
docker compose exec -T db pg_dump -U waferai -d waferai --format=custom > "$partial"
mv "$partial" "$target"

# 오래된 것부터 지워 최근 $KEEP 개만 남긴다
ls -1t backups/waferai-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f -- "$old"
done

echo "백업 완료: $target ($(du -h "$target" | cut -f1))"
