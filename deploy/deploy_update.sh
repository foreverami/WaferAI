#!/bin/sh
# 맥(로컬)에서 실행한다: 지금 커밋과 모델 파일을 운영 서버에 올리고 다시 띄운다.
#
#   sh deploy/deploy_update.sh                # 기본 호스트 waferai-vm (~/.ssh/config)
#   HOST=다른호스트 sh deploy/deploy_update.sh
#
# 하는 일
#   1. 커밋하지 않은 변경이 있으면 멈춘다 (올라가는 것은 커밋된 내용뿐이다).
#   2. 코드를 git archive 로 서버 ~/waferai 에 푼다 (.env · backups · models 는 건드리지 않는다).
#   3. 모델 파일은 서버와 해시가 다를 때만 올린다. 임시 이름으로 받은 뒤 옮겨서, 올리는 도중에
#      api 가 반쪽짜리 파일을 읽는 일이 없게 한다. .pth 와 .onnx 는 짝이라 함께 바꾼다.
#   4. HTTPS 설정(nginx/https.conf)을 예시 파일에서 다시 만든다. 이 파일은 서버에서 도메인을 넣어
#      만든 것이라 git 에 없고, 다시 만들지 않으면 예시에 더한 설정(로그인 속도 제한 등)이 운영에
#      반영되지 않는다 (11/17 운영 점검에서 실제로 빠져 있었다). 문법 검사에 실패하면 되돌린다.
#   5. 컨테이너를 다시 만들고(마이그레이션은 api 가 기동하며 적용) 상태를 보여 준다.
set -eu
HOST="${HOST:-waferai-vm}"
COMPOSE="docker compose -f compose.yaml -f compose.https.yaml"
cd "$(dirname "$0")/.."

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "커밋하지 않은 변경이 있습니다. 커밋한 뒤 다시 실행하세요." >&2
    exit 1
fi

echo "[1/4] 코드 올리기 ($(git rev-parse --short HEAD))"
git archive --format=tar HEAD | ssh "$HOST" 'mkdir -p ~/waferai && tar -x -C ~/waferai'

echo "[2/4] 모델 파일 확인"
changed=0
for f in best_coatnet_model_optimized.pth coatnet_wafer.onnx; do
    local_sha=$(shasum -a 256 "models/$f" | cut -d' ' -f1)
    remote_sha=$(ssh "$HOST" "sha256sum ~/waferai/models/$f 2>/dev/null | cut -d' ' -f1" || true)
    if [ "$local_sha" != "$remote_sha" ]; then
        echo "  $f 올리는 중 (${local_sha%"${local_sha#????????????}"})"
        scp -q "models/$f" "$HOST:~/waferai/models/.$f.upload"
        changed=1
    else
        echo "  $f 같음"
    fi
done
if [ "$changed" = 1 ]; then
    ssh "$HOST" 'cd ~/waferai/models && for f in .*.upload; do [ -e "$f" ] && mv "$f" "$(echo "$f" | sed "s/^\.//; s/\.upload$//")"; done; true'
fi

echo "[3/4] HTTPS 설정 다시 만들기"
ssh "$HOST" 'cd ~/waferai/deploy/nginx && if [ -f https.conf ]; then
    domain=$(sed -n "s/^ *server_name \([^ ;]*\);.*/\1/p" https.conf | head -1)
    [ -n "$domain" ] || { echo "https.conf 에서 도메인을 찾지 못했습니다" >&2; exit 1; }
    cp https.conf https.conf.bak
    # 같은 파일(inode)에 덮어써야 컨테이너에 붙은 파일이 바뀐다
    sed "s/DOMAIN/$domain/g" https.conf.example > https.conf.new && cat https.conf.new > https.conf && rm https.conf.new
    echo "  $domain 으로 다시 만듦"
else
    echo "  https.conf 없음 (HTTP 구성) — 건너뜀"
fi'

echo "[4/4] 다시 띄우기"
ssh "$HOST" "cd ~/waferai/deploy && mkdir -p backups && $COMPOSE up -d --build && sleep 20 && $COMPOSE ps"
# 설정 파일만 바뀐 경우 컨테이너는 다시 만들어지지 않는다 — 문법을 검사하고 다시 읽힌다
ssh "$HOST" "cd ~/waferai/deploy && if $COMPOSE exec -T web nginx -t; then
    $COMPOSE exec -T web nginx -s reload && echo '  Nginx 설정 반영'
else
    echo '  Nginx 설정 오류 — 이전 설정으로 되돌립니다' >&2
    [ -f nginx/https.conf.bak ] && cat nginx/https.conf.bak > nginx/https.conf
    $COMPOSE exec -T web nginx -s reload
    exit 1
fi"
echo
echo "끝. 확인:"
echo "  SMOKE_ID=사번 SMOKE_PASSWORD=비밀번호 sh deploy/smoke.sh https://waferai-demo.eastasia.cloudapp.azure.com"
