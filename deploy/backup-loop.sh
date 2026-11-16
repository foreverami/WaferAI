#!/bin/sh
# compose 의 backup 서비스가 돌리는 자동 백업. 서버에 cron 을 걸지 않아도 된다.
#   BACKUP_INTERVAL_HOURS 마다(기본 24) DB 를 덤프하고, 최근 BACKUP_KEEP 개(기본 14)만 남긴다.
#   파일은 deploy/backups/waferai-날짜.dump — 수동 백업(backup.sh)과 같은 이름 규칙이다.
# 복원은 deploy/README.md "백업과 복원".
set -eu

KEEP="${BACKUP_KEEP:-14}"
INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
mkdir -p /backups

while true; do
    stamp=$(date +%Y%m%d-%H%M%S)
    target="/backups/waferai-$stamp.dump"
    partial="/backups/.waferai-$stamp.dump.partial"
    # 중간에 실패하면 반쪽짜리 파일이 정상 백업처럼 남지 않도록 임시 이름으로 쓰고 옮긴다.
    if pg_dump --format=custom --file="$partial"; then
        mv "$partial" "$target"
        echo "$(date -Iseconds) 백업 완료: $target ($(du -h "$target" | cut -f1))"
        ls -1t /backups/waferai-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
            rm -f -- "$old"
        done
    else
        rm -f "$partial"
        echo "$(date -Iseconds) 백업 실패 — 다음 주기에 다시 시도합니다" >&2
    fi
    sleep $((INTERVAL_HOURS * 3600))
done
