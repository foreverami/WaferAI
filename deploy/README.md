# 배포 절차

서버 한 대에 Docker Compose 로 세 컨테이너를 띄운다.

```
브라우저 ──▶ web (Nginx :80/:443) ──▶ api (FastAPI :8000) ──▶ db (PostgreSQL 16)
             정적 화면 + 보안 헤더         모델 · 판정 · 인증           기록 · 계정
             /api 만 안으로 넘김           포트를 밖에 열지 않음         포트를 밖에 열지 않음
```

| 파일 | 역할 |
|---|---|
| `compose.yaml` | 세 서비스 정의 |
| `compose.https.yaml` | HTTPS 전환 시 덧씌움 |
| `.env.example` | 운영 비밀값 양식 → `.env` 로 복사 |
| `nginx/default.conf` | HTTP 설정 (로컬 확인, 인증서 첫 발급) |
| `nginx/https.conf.example` | HTTPS 설정 양식 |
| `nginx/security-headers.conf` | 보안 헤더 (CSP 등) |
| `entrypoint.sh` | API 기동 시 마이그레이션 → 서버 시작 |
| `backup.sh` | PostgreSQL 백업 |
| `../Dockerfile` | API 이미지 |
| `../frontend/Dockerfile` | 화면 이미지 |

## 서버 요구사항

권장 4 vCPU / 8GB RAM / 50GB 디스크. x86_64 와 ARM64(Oracle Cloud 등) 모두 된다 —
CPU 전용 torch 인덱스와 화면 빌드 도구가 두 아키텍처를 모두 지원하는 것을 확인했다.

Docker Engine 과 Compose 플러그인이 필요하다. 설치는 공식 문서를 따른다:
https://docs.docker.com/engine/install/

## 처음 배포

```sh
# 1. 코드
git clone <저장소> waferai && cd waferai          # 또는 압축 파일을 풀어도 된다

# 2. 모델 가중치 — 이미지에 넣지 않고 실행 시 붙인다
#    models/best_coatnet_model_optimized.pth   (필수, Google Drive 원본)
#    models/coatnet_wafer.onnx                 (선택, 아래 참고)

# 3. 운영 비밀값
cd deploy
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # → POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → WAFERAI_SECRET_KEY
vi .env

# 4. 기동 (첫 빌드는 torch 를 받느라 수 분 걸린다)
docker compose up -d --build
docker compose ps                          # 세 서비스 모두 healthy 가 될 때까지
curl http://localhost/healthz              # {"status":"ok","backend":"onnx"}

# 5. 첫 관리자 — 비밀번호는 실행 중에 직접 입력한다 (인자로 넘기지 않는다)
docker compose exec api python -m scripts.create_user \
    --employee-id 사번 --name 이름 --email me@example.com --role admin
```

**ONNX 파일**: 서버 이미지에는 익스포트 도구(onnx)가 없다. 개발 장비에서
`python3 -m scripts.export_onnx` 로 만들어 `models/` 에 함께 복사한다. 없으면 PyTorch 로
자동 전환되어 그대로 동작한다.

**백엔드 고르기**: 어느 쪽이 빠른지는 CPU 에 따라 뒤집힌다(개발 장비 ARM 에서는 PyTorch 가
빨랐다). 서버에서 재고 `.env` 의 `WAFERAI_BACKEND` 를 정한다.

```sh
docker compose exec api python -m scripts.benchmark
vi .env && docker compose up -d            # 값을 바꿨으면 다시 띄운다
```

## HTTPS

도메인이 서버 IP 를 가리키고 있어야 한다. 인증서는 Let's Encrypt 에서 받는다.

```sh
cd deploy
# 1. 인증서 발급 — HTTP 설정이 /.well-known/acme-challenge/ 에 응답해야 한다 (기본 설정에 들어 있다)
docker run --rm -v "$PWD/certbot/www:/var/www/certbot" -v "$PWD/certbot/conf:/etc/letsencrypt" \
    certbot/certbot certonly --webroot -w /var/www/certbot \
    -d 도메인 --email 메일주소 --agree-tos --no-eff-email

# 2. HTTPS 설정 생성 후 전환
sed 's/DOMAIN/도메인/g' nginx/https.conf.example > nginx/https.conf
docker compose -f compose.yaml -f compose.https.yaml up -d

# 3. 갱신 — crontab 에 등록 (인증서는 90일마다 만료)
# 0 4 * * 1 cd /경로/deploy && docker run --rm -v "$PWD/certbot/www:/var/www/certbot" \
#   -v "$PWD/certbot/conf:/etc/letsencrypt" certbot/certbot renew --quiet \
#   && docker compose exec web nginx -s reload
```

HTTPS 를 켠 뒤로는 `docker compose` 명령마다 `-f compose.yaml -f compose.https.yaml` 를 붙인다.

## 백업과 복원

```sh
./backup.sh                                # backups/waferai-날짜.dump, 최근 14개 유지
# 매일 새벽 3시: 0 3 * * * cd /경로/deploy && ./backup.sh >> backups/backup.log 2>&1

docker compose exec -T db pg_restore -U waferai -d waferai --clean --if-exists \
    < backups/waferai-YYYYMMDD-HHMMSS.dump
```

히트맵은 다시 만들어지는 결과물이라 백업하지 않는다. 가중치는 원본이 Drive 에 있다.

## 업데이트

```sh
git pull
cd deploy && docker compose up -d --build   # 마이그레이션은 api 가 기동하며 자동 적용
```

## 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `up` 이 즉시 "POSTGRES_PASSWORD 를 넣으세요" | `deploy/.env` 가 없다 | `cp .env.example .env` 후 값 채우기 |
| api 가 unhealthy, 로그에 "운영 설정에 문제가 있습니다" | 비밀값 누락, 32바이트 미만, 또는 쿠키 보안 꺼짐 | 로그가 무엇이 문제인지 적어준다 |
| api 로그에 "모델 체크포인트가 없습니다" | `models/` 에 `.pth` 가 없다 | 가중치 복사 후 `docker compose restart api` |
| 로그인 성공 직후 다시 로그인 화면 | HTTP 로 접속했는데 `WAFERAI_COOKIE_SECURE=true` → 브라우저가 쿠키를 버린다 | HTTPS 적용. 로컬 확인은 `http://localhost` + Chrome 이면 된다 |
| 502 Bad Gateway | api 가 아직 모델을 올리는 중이거나 죽었다 | `docker compose logs api` |
| 히트맵이 처음에만 몇 초 걸림 | 정상. 첫 요청에서 PyTorch 를 올린다 | — |
| 업로드 시 413 | 8MB 초과 | 이미지는 224×224 로 내보내면 수십 KB 다 |

```sh
docker compose logs -f api                 # 실시간 로그
docker compose exec db psql -U waferai     # DB 직접 확인
```

## 검증 범위

이 구성은 Docker 가 없는 장비에서 작성했다. 그래서 Docker 없이 할 수 있는 만큼 검증했고,
남은 부분은 서버에서 처음 띄울 때 확인해야 한다.

**검증함**

- 런타임 의존성(`requirements.txt`)만 깐 새 환경에서 마이그레이션·기동·예측·히트맵까지 동작
- PostgreSQL 16 에서 전체 테스트 156개 통과, 마이그레이션 왕복(올리기·되돌리기)
- `entrypoint.sh` 로 운영 모드 기동 — 마이그레이션 자동 적용, 모델 자동 등록, 운영 안전 점검
- Nginx 설정 문법 — 공식 이미지와 같은 문맥(`http{}` 안 include)에서 파싱
- CSP — Nginx 와 같은 헤더를 붙이는 대역 서버로 Chrome 에서 전 화면을 돌려 위반 0건
- 빌드 컨텍스트 — `.dockerignore` 규칙이 `.env`·가중치·데이터를 막는지 (`tests/test_deploy.py`)

**서버에서 처음 확인할 것 (Docker 필요)**

- 이미지 빌드 자체. slim 이미지에 공유 라이브러리가 빠졌을 위험은 빌드 단계의 import 점검으로
  실행 전에 터지게 해 두었다
- 컨테이너 간 네트워크, 볼륨 권한, 헬스체크 대기 시간
- 실제 Nginx 의 동작 (헤더·라우팅은 대역 서버로 재현했다)
- 인증서 발급과 HTTPS
- 이미지 크기와 메모리 사용량
