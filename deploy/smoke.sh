#!/bin/sh
# 배포 후 확인 — Nginx 를 거쳐 API 까지 실제로 도는지 본다. CI 와 실제 서버에서 같은 것을 쓴다.
#
#   sh deploy/smoke.sh http://localhost                       # 로그인 없이 되는 확인만
#   SMOKE_ID=사번 SMOKE_PASSWORD=비밀번호 sh deploy/smoke.sh https://도메인
#                                                             # 로그인 · 모델 상태 · 예측 · 히트맵까지
#
# 계정 정보는 인자가 아니라 환경변수로 받는다. 명령행 인자는 셸 히스토리와 ps 에 남는다.
# 비밀번호에 큰따옴표나 역슬래시가 있으면 JSON 이 깨지므로 그런 계정은 쓰지 않는다.
set -eu
BASE=${1:?사용법: smoke.sh <주소>  예) http://localhost}
BASE=${BASE%/}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

ok()   { echo "  ok  $1"; }
fail() { echo "  FAIL $1"; exit 1; }
status_of() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@"; }

echo "[1] /healthz"
body=$(curl -fsS --max-time 15 "$BASE/healthz") || fail "healthz 응답 없음"
echo "$body" | grep -q '"status":"ok"' || fail "healthz: $body"
ok "$body"

echo "[2] 화면과 보안 헤더"
curl -fsS --max-time 15 -D "$TMP/headers" -o "$TMP/index.html" "$BASE/" || fail "/ 응답 없음"
grep -q 'id="root"' "$TMP/index.html" || fail "/ 가 화면(index.html)이 아닙니다"
grep -qi '^content-security-policy:' "$TMP/headers" || fail "Content-Security-Policy 헤더가 없습니다"
grep -qi '^x-content-type-options: *nosniff' "$TMP/headers" || fail "X-Content-Type-Options 헤더가 없습니다"
ok "index.html · CSP · nosniff"

echo "[3] 화면 라우팅 — /review 를 직접 열어도 index.html"
code=$(status_of "$BASE/review")
[ "$code" = "200" ] || fail "/review → $code"
ok "200"

echo "[4] 로그인 없이 API 는 막힘"
code=$(status_of "$BASE/api/auth/me")
[ "$code" = "401" ] || fail "/api/auth/me → $code (401 이어야 합니다)"
ok "401"

if [ -z "${SMOKE_ID:-}" ] || [ -z "${SMOKE_PASSWORD:-}" ]; then
    echo
    echo "로그인이 필요한 확인은 건너뜀. SMOKE_ID 와 SMOKE_PASSWORD 를 주면 예측 · 히트맵까지 확인합니다."
    exit 0
fi

echo "[5] 로그인"
printf '{"employee_id":"%s","password":"%s"}' "$SMOKE_ID" "$SMOKE_PASSWORD" > "$TMP/login.json"
code=$(curl -s -o "$TMP/me.json" -D "$TMP/login_headers" -w '%{http_code}' --max-time 15 \
    -H 'Content-Type: application/json' --data @"$TMP/login.json" "$BASE/api/auth/login")
[ "$code" = "200" ] || fail "로그인 → $code: $(cat "$TMP/me.json")"
# 쿠키는 Secure 속성이 있어 http 에서는 curl 의 쿠키 저장소가 돌려보내지 않는다. 헤더에서 직접 꺼내 쓴다.
cookie=$(sed -n 's/^[Ss]et-[Cc]ookie: *\([^;]*\).*/\1/p' "$TMP/login_headers" | head -1)
[ -n "$cookie" ] || fail "로그인 응답에 세션 쿠키가 없습니다"
grep -qi 'httponly' "$TMP/login_headers" || fail "세션 쿠키에 HttpOnly 가 없습니다"
ok "$(sed -n 's/.*"role":"\([^"]*\)".*/role=\1/p' "$TMP/me.json") · HttpOnly 쿠키"

echo "[6] 모델 상태"
curl -fsS --max-time 15 -H "Cookie: $cookie" -o "$TMP/status.json" "$BASE/api/status" || fail "/api/status 실패"
grep -q '"model_ready":true' "$TMP/status.json" || fail "model_ready 가 아닙니다: $(cat "$TMP/status.json")"
ok "model_ready · backend=$(sed -n 's/.*"backend":"\([^"]*\)".*/\1/p' "$TMP/status.json")"

echo "[7] 예측 — 합성 웨이퍼 업로드"
printf '[[0,1,0],[1,2,1],[0,1,0]]' > "$TMP/synthetic.json"
curl -fsS --max-time 60 -H "Cookie: $cookie" -o "$TMP/predict.json" \
    -F "file=@$TMP/synthetic.json;type=application/json" "$BASE/api/predict" || fail "/api/predict 실패"
wafer_id=$(sed -n 's/.*"wafer_id":"\([^"]*\)".*/\1/p' "$TMP/predict.json")
[ -n "$wafer_id" ] || fail "예측 응답에 wafer_id 가 없습니다: $(cat "$TMP/predict.json")"
ok "$(sed -n 's/.*"final_class":"\([^"]*\)".*"decision_path":"\([^"]*\)".*/\1 · \2/p' "$TMP/predict.json")"

echo "[8] 히트맵 — 첫 요청은 PyTorch 를 올리느라 CPU 서버에서 수십 초 걸릴 수 있음"
started=$(date +%s)
curl -fsS --max-time 300 -H "Cookie: $cookie" -o "$TMP/heatmap.png" \
    "$BASE/api/records/$wafer_id/heatmap" || fail "히트맵 생성 실패"
magic=$(head -c 4 "$TMP/heatmap.png" | od -An -tx1 | tr -d ' \n')
[ "$magic" = "89504e47" ] || fail "히트맵 응답이 PNG 가 아닙니다"
ok "PNG $(wc -c < "$TMP/heatmap.png" | tr -d ' ')바이트 · $(( $(date +%s) - started ))초"

echo
echo "모두 통과"
