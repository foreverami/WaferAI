#!/bin/sh
# 서버에서 `docker compose up` 전에 돌리는 점검. 빠진 것을 한 번에 모두 알려 준다.
#
#   cd deploy && sh preflight.sh
#
# 기동 중에 하나씩 터지면 원인을 찾느라 시간이 간다. 도구 · 자원 · 파일 · 비밀값 · 포트를
# 미리 확인하고, 문제가 하나라도 있으면 0 이 아닌 값으로 끝난다.
set -u
cd "$(dirname "$0")"

problems=0
ok()   { echo "  ok  $1"; }
skip() { echo "  --  $1"; }
bad()  { echo "  !!  $1"; problems=$((problems + 1)); }

echo "[도구]"
if command -v docker >/dev/null 2>&1; then
    ok "docker $(docker --version | sed 's/,.*//')"
    if docker info >/dev/null 2>&1; then
        ok "docker 데몬 접근 가능"
    else
        bad "docker 데몬에 접근할 수 없습니다 (데몬이 꺼져 있거나 sudo 가 필요합니다: sudo usermod -aG docker \$USER)"
    fi
    if docker compose version >/dev/null 2>&1; then
        ok "docker compose $(docker compose version --short)"
    else
        bad "docker compose 플러그인이 없습니다 (docker-compose-plugin 패키지)"
    fi
else
    bad "docker 가 없습니다: https://docs.docker.com/engine/install/"
fi

echo "[자원]"
if [ -r /proc/meminfo ]; then
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2 / 1024 / 1024}' /proc/meminfo)
    if [ "$mem_gb" -ge 7 ]; then
        ok "메모리 ${mem_gb}GB"
    else
        bad "메모리 ${mem_gb}GB — 권장 8GB. 4GB 에서도 뜨지만 첫 히트맵(PyTorch 적재)이 느리고 여유가 없습니다"
    fi
else
    skip "메모리 확인 건너뜀 (/proc/meminfo 없음 — 리눅스 서버가 아님)"
fi
disk_gb=$(df -Pk . | awk 'NR == 2 {printf "%d", $4 / 1024 / 1024}')
if [ "$disk_gb" -ge 15 ]; then
    ok "디스크 여유 ${disk_gb}GB"
else
    bad "디스크 여유 ${disk_gb}GB — 이미지(약 3GB) · DB · 히트맵에 15GB 이상 필요합니다"
fi
cpus=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo '?')
ok "CPU ${cpus}개 · $(uname -m)"

echo "[파일]"
if [ -f ../models/best_coatnet_model_optimized.pth ]; then
    ok "모델 가중치 models/best_coatnet_model_optimized.pth"
else
    bad "models/best_coatnet_model_optimized.pth 가 없습니다 — 운영 모델을 복사하세요 (git 에는 없습니다)"
fi
if [ -f ../models/coatnet_wafer.onnx ]; then
    ok "ONNX 모델 models/coatnet_wafer.onnx"
else
    skip "models/coatnet_wafer.onnx 없음 — PyTorch 로 돌아갑니다 (개발 장비에서 export_onnx 로 만들어 복사하면 됩니다)"
fi

echo "[비밀값 deploy/.env]"
if [ -f .env ]; then
    for key in POSTGRES_PASSWORD WAFERAI_SECRET_KEY; do
        value=$(sed -n "s/^$key=//p" .env | tr -d '\r')
        if [ -z "$value" ]; then
            bad "$key 가 비어 있습니다 (.env.example 의 생성 명령으로 만드세요)"
        elif [ "$key" = WAFERAI_SECRET_KEY ] && [ "${#value}" -lt 32 ]; then
            bad "$key 가 32자 미만입니다 (${#value}자) — 서버가 기동을 거부합니다"
        else
            ok "$key 설정됨 (${#value}자)"
        fi
    done
    secure=$(sed -n 's/^WAFERAI_COOKIE_SECURE=//p' .env | tr -d '\r')
    if [ "${secure:-true}" = "true" ]; then
        ok "WAFERAI_COOKIE_SECURE=true (HTTPS 전제. http://localhost 확인은 그대로 됩니다)"
    else
        bad "WAFERAI_COOKIE_SECURE=$secure — 운영에서는 true 여야 서버가 뜹니다"
    fi
else
    bad ".env 가 없습니다: cp .env.example .env 후 값을 채우세요"
fi
mkdir -p certbot/www

echo "[포트]"
for port in "${WEB_PORT:-80}" "${WEB_TLS_PORT:-443}"; do
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$port\$"; then
        bad "포트 $port 를 다른 프로세스가 쓰고 있습니다 (ss -ltnp | grep :$port)"
    else
        ok "포트 $port 비어 있음"
    fi
done

echo
if [ "$problems" -eq 0 ]; then
    echo "문제 없음 — docker compose up -d --build"
else
    echo "문제 ${problems}개. 위 항목을 고친 뒤 다시 돌리세요."
    exit 1
fi
