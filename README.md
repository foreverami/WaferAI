# WaferAI — 웨이퍼 결함 분류 서비스

WM-811K 로 학습한 CoAtNet-0 9클래스 분류기를 웹 서비스로 배포하는 프로젝트.
Colab 학습 코드는 `training_reference.py` 에 보존돼 있다.

현재 **Phase 6** 까지 완료: 공용 전처리 · 추론 백엔드 · 판정 로직 · 인증/권한 ·
SQLAlchemy 모델 · Alembic 마이그레이션 · Grad-CAM · 검토 워크플로 · React 화면 ·
Docker Compose + Nginx 배포 구성 · 재학습 루프와 3분할 학습 파이프라인.
서버 배포 절차는 [deploy/README.md](deploy/README.md).

**운영 모델은 3분할 재학습 모델이다 (10/13 교체).** 학습에 쓰지 않은 테스트 셋 17,504건에서
정확도 97.74% · macro-F1 0.891 (아래 "첫 재학습 결과"). 기본 판정 설정에서 96.4% 가 사람
검토 없이 나가고, 그중 틀리는 건은 전체의 0.74% 다 ("판정 로직 효과"). 남은 일: 서버 배포.

## 설치

```sh
python3 -m pip install -r requirements-dev.txt   # 개발: 서버 의존성 + 테스트·평가 도구
cp .env.example .env                              # 값을 채운다
```

`requirements.txt` 는 서버 실행에 필요한 것만 담는다(배포 이미지가 이것을 쓴다).
`tests/test_deploy.py` 가 이미지에 들어가는 코드의 import 를 모두 덮는지 검사한다.

## 실행

```sh
python3 -m unittest discover -s tests -v       # 테스트 197개
python3 -m alembic upgrade head                # 스키마 생성/갱신
python3 -m scripts.create_user --employee-id 202104346 --name 이름 \
    --email me@example.com --role admin        # 첫 관리자 (비밀번호는 실행 중 입력)
python3 -m uvicorn waferai.server:app --host 127.0.0.1 --port 8000
```

프론트엔드는 따로 띄운다. 개발 중에는 Vite(5173)와 FastAPI(8000)가 다른 포트라
쿠키가 오가지 않으므로, Vite 프록시가 같은 출처처럼 보이게 한다.

```sh
npm --prefix frontend install
npm --prefix frontend run dev        # http://127.0.0.1:5173
```

화면만 빨리 확인하려면 관리자 계정을 만들 필요 없이 `python3 -m scripts.serve_preview` 로
백엔드를 띄운다. 임시 DB 에 테스트 고정 계정 3개(tests/conftest.py)를 심어 두므로 로컬 밖에서는
쓰면 안 된다.

```sh
python3 -m scripts.export_onnx                 # .pth → .onnx (동등성 검증 포함)
python3 -m scripts.benchmark                   # 배포 서버에서 백엔드 실측
python3 -m waferai.inference --image wafer.png  # 렌더링 이미지로 예측
python3 -m waferai.inference --map wafer.npy    # 0/1/2 맵으로 예측
```

## 인증과 권한

로그인은 JWT 를 **httpOnly 쿠키**에 담는다. localStorage 에 두면 XSS 한 번에
탈취되지만 httpOnly 쿠키는 자바스크립트가 읽지 못한다. CSRF 는 SameSite 로 막는다.

| 등급 | 조회·검토 | 임계값 변경 | 계정 관리 |
|---|---|---|---|
| `engineer` | O | X | X |
| `senior_engineer` | O | O | X |
| `admin` | O | O | O |

UI 에서 버튼을 감추는 것은 방어가 아니다. 개발자도구로 우회되므로 모든 엔드포인트가
서버에서 등급을 확인한다. 비밀번호는 bcrypt 로 해싱하되, 72바이트 한계 때문에
SHA-256 으로 길이를 먼저 고정한다 — 한글은 글자당 3바이트라 24자면 한도에 닿는다.

## Human-in-the-Loop

UIUX 문서의 세 가지 처리 경로를 그대로 API 로 옮겼다.

| 화면 동작 | 엔드포인트 |
|---|---|
| 1순위 승인 (대형 버튼) | `POST /api/records/{id}/approve` |
| 2순위 수정 (링크) | `POST /api/records/{id}/approve` `{"rank": 2}` |
| 수동 라벨링 (드롭다운) | `POST /api/records/{id}/review` `{"label": "Scratch"}` |
| 리뷰 대기열 | `GET /api/records?review_only=true` |

`approve` 는 클래스명을 클라이언트가 되돌려 보내지 않는다. 서버가 저장된 확률에서
직접 고르므로 화면에 보이는 값과 저장되는 값이 어긋날 여지가 없다.

**원래 AI 예측은 어떤 경로로도 덮어쓰지 않는다.** 검토 결과는 `review_result` 에
따로 쌓인다. 나중에 모델 성능을 되짚으려면 AI 가 원래 뭐라고 했는지가 남아 있어야
한다. 검토가 끝나면 `requires_human_review` 만 내려 대기열에서 빠진다.

## Grad-CAM (설명가능성)

```sh
GET /api/records/{id}/heatmap                    # AI 1순위 기준
GET /api/records/{id}/heatmap?class_name=Donut   # 2순위 등 특정 클래스
```

`pytorch-grad-cam` 라이브러리를 쓰지 않고 `waferai/gradcam.py` 에 직접 구현했다.
CoAtNet 마지막 스테이지 출력이 **(1, 768, 7, 7) 4D NCHW** 로 실측돼, 라이브러리가
필요한 지점인 어텐션 토큰 → 공간 해상도 변환(`reshape_transform`)이 이 모델에는
아예 필요 없다. 기능상세설명서 §3.3.3 의 `reshape_transform_coatnet()` 언급은
불필요한 내용이다. 남는 계산은 30줄 남짓이라 배포 이미지에 의존성을 더할 이유가 없다.

**지연 생성(Lazy Eval)** — ERD 와 플로우차트의 설계를 따른다. 실제로 열어보는 건
검토 대상 5% 남짓이라 전부 미리 만들면 서버가 낭비된다. 한 번 만든 뒤에는 디스크에서
낸다.

**PyTorch 지연 로딩** — `/predict` 는 ONNX 로 돌고 Grad-CAM 만 PyTorch 가 필요하다.
아무도 히트맵을 열지 않으면 102MB 를 아예 올리지 않는다. ONNX Runtime 은 순전파만
하므로 역전파가 필요한 Grad-CAM 을 돌릴 수 없다.

### 히트맵이 실제로 결함을 가리키는지

값이 나오는 것만으로는 부족하다. 위치가 엉뚱하면 설명가능성이 아니라 잘못된 확신을
준다. `tests/test_gradcam.py` 가 CAM 질량 중심의 정규화 반경을 재서 검증한다.

| 합성 패턴 | CAM 질량 반경 | 기대 |
|---|---|---|
| Center | 0.405 | 가운데 |
| Donut | 0.547 | 중간 |
| Edge-Ring | 0.880 | 가장자리 |

결함 기하와 순서가 정확히 일치한다.

## 화면 (frontend/)

Vite + React 19 + React Router 7 + Tailwind 4. UIUX 문서 §5 의 컬러 토큰을 그대로
쓴다(타이포 스케일은 Figma 시안 기준 10.5px 라 실제 화면에서 너무 작아, 위계는 두고
읽을 수 있는 크기로 올렸다).

로그인 → 메인 대시보드 → 헤더 아래 탭으로 다른 화면 이동.

| 경로 | 화면 | 최소 등급 |
|---|---|---|
| `/login` | 로그인 | — |
| `/` | 대시보드 (KPI + 웨이퍼 카드) | engineer |
| `/review` | 리뷰 대기열 | engineer |
| `/settings` | 판정 임계값 | senior_engineer |

상세 팝업은 원본 / 히트맵 / 겹쳐보기 토글과 1순위 승인 · 2순위 수정 · 수동 라벨링
세 경로를 담는다.

> **목록에는 `/thumbnail`, 상세에만 `/heatmap`.** 카드마다 히트맵을 부르면 목록을
> 한 번 열 때 카드 수만큼 역전파가 돌아 지연 생성 설계가 무너진다. 썸네일은 모델을
> 건드리지 않고 LUT 와 리사이즈만 한다.

라우터 가드는 편의지 방어가 아니다. 실제 차단은 서버가 하며, 등급이 모자란 사용자가
주소를 직접 쳐도 API 가 403 을 낸다.

## 배포

`deploy/` 에 Docker Compose 구성이 있다 — db(PostgreSQL 16) · api(FastAPI) · web(Nginx).
절차·HTTPS·백업·문제 해결은 [deploy/README.md](deploy/README.md).

```sh
cd deploy && cp .env.example .env && docker compose up -d --build
```

## 데이터베이스

개발·테스트는 SQLite, 운영은 PostgreSQL. 같은 SQLAlchemy 모델이 양쪽에서 돌도록
JSONB 같은 Postgres 전용 타입은 쓰지 않는다.

```sh
python3 -m alembic upgrade head                        # 적용
python3 -m alembic revision --autogenerate -m "설명"    # 모델 수정 후 생성
```

`tests/test_migrations.py` 가 마이그레이션 결과와 모델 정의가 일치하는지 검사한다.

SQLite 와 PostgreSQL 은 같은 스키마를 다르게 다룬다. 운영 DB 에서도 테스트를 돌릴 수 있다:

```sh
WAFERAI_TEST_DATABASE_URL=postgresql+psycopg://... \
WAFERAI_TEST_MIGRATION_DATABASE_URL=postgresql+psycopg://.../별도DB \
    python3 -m unittest discover -s tests
```

실제로 SQLite 에서는 보이지 않던 문제가 PostgreSQL 에서 하나 드러났다. `settings.key` 에
기본키와 유니크 제약을 둘 다 걸었는데, PostgreSQL 은 테이블을 만들며 중복 제약을 합쳐
기본키에 유니크의 이름(`uq_settings_key`)을 붙였다. 모델과 DB 가 영원히 어긋나고,
그 이름으로 제약을 지우면 기본키가 지워지는 함정이었다. 마이그레이션 `3f2a9c1d7b84` 가
실제 제약 종류를 확인한 뒤 DB 별로 정리한다.
모델만 고치고 마이그레이션을 빼먹으면 개발에서는 `create_all` 이 덮어줘서 멀쩡해
보이지만 운영에서 터지므로, 그 간극을 배포 전에 잡는다.

ERD 문서의 7테이블 중 Vision 파이프라인에 해당하는 5개만 만들었다. Sensor AI 쪽
(equipment, sensor_alert, unified_report)과 retrain_job 은 범위 밖이다.
ERD 에 없던 `users` 를 추가했다 — UIUX 문서 화면 8 이 사번·부서·권한을 요구하는데
ERD 에는 사용자 테이블이 없었고, `review_result.reviewer` 가 자유 문자열이라 누가
검토했는지 추적할 수 없었다.

## 입력 형식

모델은 **사진이 아니라 0/1/2 웨이퍼 맵**으로 학습됐다 (0 배경 / 1 정상 다이 / 2 결함 다이).

| 경로 | 형식 | 비고 |
|---|---|---|
| 데이터 | `.npy` `.csv` `.json` | 정확한 경로. 최대 512×512 |
| 이미지 | `.png` `.jpg` | 학습과 같은 색(검정/초록/노랑)으로 렌더링된 맵. **224×224 권장** |

이미지 경로는 색을 역으로 풀어 맵을 복원한다. 다른 색 체계나 웨이퍼 실물 사진은
조용히 잘못 해석하지 않고 422 로 거부한다. 업로드 상한은 8MB.

> 224×224 보다 큰 이미지는 축소되며, 폭이 좁은 결함(Scratch)이 손실될 수 있다는
> 경고가 응답에 함께 온다.

## 전처리 (학습과 동일해야 하는 부분)

`waferai/preprocess.py` 가 유일한 정의다. 다른 곳에서 다시 구현하지 않는다.

```
원본 맵(0/1/2) → 정사각 제로 패딩 → 224 INTER_NEAREST → 컬러 LUT
              → /255 → ImageNet 정규화 → (1, 3, 224, 224)
```

순서가 중요하다. 리사이즈는 **LUT 적용 전, 라벨맵 상태에서** 끝낸다.
`tests/test_preprocess.py` 가 torchvision 기준 구현과 `rtol=0, atol=0` 으로
일치함을 여러 형태에 대해 검증한다.

## 판정 로직

문서 세 곳(기능상세설명서 §3.3.2 · 플로우차트 §2.2 · 기존 코드)이 서로 다른 규칙을
말하고, 기능상세설명서 쪽에는 정의되지 않은 구간이 있었다. 아래 4단계로 통일했다.
위에서부터 순서대로 검사한다.

| 순서 | 조건 | 기본값 | 결과 | 경로 |
|---|---|---|---|---|
| ① | 결함밀도 < `low_density` | **꺼짐** | `none` | `RULE_BASE_NONE` |
| ② | 결함밀도 > `high_density` | 0.80 | `Near-full` | `RULE_BASE_NEAR_FULL` |
| ③ | 확신도 ≥ `confidence` | 0.80 | AI 1순위 | `AUTO_PASS` |
| ④ | 그 외 | — | AI 1순위(잠정) | `REVIEW_NEEDED` |

결함밀도 = 값2 / (값1 + 값2). 배경은 분모에서 뺀다.

### ① 이 기본으로 꺼져 있는 이유

기능상세설명서 §3.3.2 는 `defect_ratio < 0.05 → none` 을 지시하지만, 1학기 모델과 검증 분할
10,208건으로 재 보니 **정확도를 떨어뜨렸다.**

| | 규칙 켬(0.05) | 규칙 끔 |
|---|---|---|
| 전체 정확도 | 93.78% | **96.45%** |
| 잘못 새어나간 건 | 430건 | **143건** |
| 엔지니어 검토 부담 | 4.67% | 4.95% |

규칙에 걸린 1,087건 중 **291건이 실제로는 결함**이었다(Loc 118 · Edge-Ring 54 ·
Scratch 50 · Edge-Loc 38 · Center 31). 같은 건들을 AI 에게 맡기면 98.34% 로 맞힌다.
결함 다이가 5% 미만이어도 얇은 Scratch 나 작은 Loc 은 명백한 결함인데, 픽셀을 세는
규칙은 패턴을 못 보기 때문이다. 0.01 까지 낮춰도 규칙 정확도가 9.1% 라 임계값
조정이 아니라 규칙 자체가 틀렸다. 설정으로 되살릴 수는 있게 두되 기본은 끈다.

②는 유지한다. 0.80 에서 걸린 20건이 전부 실제 Near-full 이었고 AI 도 같은 답을
냈다(규칙 100% / AI 100%). 측정상 이득은 없지만, 재학습으로 모델이 드리프트해도
거의 전면 불량인 웨이퍼는 확정적으로 잡아주는 방어선이 된다.

### 임계값 변경

`settings` 테이블에 저장되며 `senior_engineer` 이상이 바꾼다.

```sh
GET  /api/settings/thresholds
PUT  /api/settings/thresholds     {"low_density": null, "high_density": 0.8, "confidence": 0.8}
```

`null` 은 해당 규칙을 끈다는 뜻이다. UIUX 문서 화면 6·7 의 슬라이더가 이 API 를 쓴다.

## 추론 백엔드

`/api/predict` 는 ONNX Runtime, Grad-CAM 은 PyTorch 를 쓴다. ONNX Runtime 은
순전파만 하므로 역전파가 필요한 Grad-CAM 을 돌릴 수 없다.

`backend='auto'`(기본)는 ONNX 파일이 있으면 ONNX, 없으면 PyTorch 로 떨어진다.
`tests/test_backend_parity.py` 가 두 백엔드의 확률이 일치함을 검증한다.

**어느 쪽이 빠른지는 CPU 에 따라 뒤집힌다.** 개발 장비(Apple Silicon arm64) 실측은
PyTorch 22.5ms / ONNX Runtime 31.1ms 로 PyTorch 가 빨랐다. 배포 대상인 x86 리눅스
에서는 반대인 경우가 많으므로, 서버를 정한 뒤 `scripts/benchmark.py` 로 재고 고른다.

## 실측 결과 (Phase 1.5)

> **이 절과 "판정 로직"의 수치는 1학기 모델(10/13 교체 전)로 잰 것이다.** 지금 운영 모델의
> 성적은 "첫 재학습 결과", 새 모델의 판정 경로별 수치는 "판정 로직 효과" 에 있다.

`LSWMD.pkl` 전량에서 학습 분할을 시드까지 재현해 측정했다. 재현 스크립트는
`scripts/prepare_eval_set.py`, 측정은 `scripts/evaluate.py`.

```sh
python3 -m scripts.prepare_eval_set --source ~/Downloads/LSWMD.pkl
python3 -m scripts.evaluate --device mps        # 서빙은 CPU, 측정은 GPU 로 해도 된다
```

### 전처리가 학습과 같음 — 검증 정확도 96.4538% 재현 (차이 0.0000%p)

검증 분할 10,208건에서 체크포인트가 기록한 값과 소수점까지 일치한다.
CPU 와 MPS 양쪽에서 같은 값이 나왔다. 전처리가 한 단계라도 어긋나면 나올 수 없는 수치다.

### 클래스별 (검증 분할, F1)

Edge-Ring 0.990 · none 0.982 · Center 0.971 · Near-full 0.949(표본 30) ·
Random 0.944 · Edge-Loc 0.923 · Scratch 0.887 · Loc 0.868 · Donut 0.866

오류는 Loc ↔ Edge-Loc ↔ none 삼각형에 몰린다. 레이블 경계가 원래 모호한 클래스들이다.

### 판정 경로별 최종 정확도 (저밀도 규칙 끈 기본 설정)

| 경로 | 비율 | 최종 정확도 |
|---|---|---|
| `AUTO_PASS` | 94.86% | 98.52% |
| `RULE_BASE_NEAR_FULL` | 0.20% | 100% |
| `REVIEW_NEEDED` | 4.95% | 56.63% |

사람이 보지 않고 나가는 건 95.05%, 그중 잘못 나가는 건 전체의 1.40%.
검토 대기 건에서 AI 가 맞을 확률이 56.63% 라, 임계값 0.80 은 사람이 볼 값어치가
있는 건만 올리고 있다.

### 미학습 데이터에서의 정확도

균형 맞추기에서 빠져 학습이 한 번도 보지 않은 'none' 20,000건: **98.22%**.
정상을 결함으로 오인한 상위는 Edge-Loc 150건, Loc 87건, Center 49건.
검증 분할과 합산(30,208건)하면 97.63%.

### 이미지 경로 영향 (실데이터 300건)

배열 경로와 예측이 **99.00% 일치**(297/300). 정확도는 97.33% → 96.67% 로
0.66%p 낮다. 바뀐 3건은 모두 Loc 관련(Loc→Edge-Loc, Loc→none ×2)으로,
원래 모호한 클래스에서만 흔들렸다.

## 아직 증명되지 않은 것

- **테스트 표본이 작은 클래스가 있다.** Near-full 14건, Donut 32건이라 이 두 클래스의 F1 은
  한두 건에 크게 흔들린다.
- 실제 공장 데이터(WM-811K 밖)에서의 정확도는 모른다. 운영에서 쌓이는 검토 결과로 확인한다.

## 재학습 (Phase 6)

### 왜 다시 학습하는가

1학기 학습은 웨이퍼 단위로 무작위 8:2 분할만 했다. 결함 샘플이 전부 학습·검증에 쓰여
오염되지 않은 테스트 정확도를 낼 수 없었다. 재학습에서는 두 가지를 바로잡는다.

* **테스트 셋을 따로 뗀다** — train 80 / val 10 / test 10.
* **로트 단위로 나눈다** — 같은 로트의 웨이퍼는 같은 공정을 거쳐 결함 패턴이 닮는다. 같은
  로트가 학습과 테스트에 갈라 들어가면 모델이 로트의 버릇을 외워 맞혀 정확도가 부풀려진다.

```sh
python3 -m scripts.prepare_training_data --source ~/Downloads/LSWMD.pkl   # → data/training_set.npz
```

로트 10,762개를 겹침 없이 나눴다. 분할의 지문이 `split_id`(`6685ab33cec9096d`)이며,
앞으로의 모든 모델은 같은 테스트 셋으로 평가해야 서로 비교할 수 있다.

| | train | val | test |
|---|---|---|---|
| 결함 | 20,477 | 2,620 | 2,422 |
| 정상(none) | 117,660 | 14,689 | 15,082 |

Near-full(테스트 14개)과 Donut(32개)은 데이터셋 자체가 작아 F1 이 한두 건에 크게 흔들린다.

### 학습 — GPU 가 필요하다

이 저장소의 개발 장비(Apple Silicon, 8GB)에서는 학습이 현실적이지 않다. 배치 32 학습이
메모리를 8GB 넘게 잡아 스왑으로 장비 전체가 멈췄고, 배치를 줄여도 초당 3.5장이라 15에폭에
이틀이 걸린다. 1학기 맥 학습이 1에폭 도중 중단된 것도 같은 이유로 보인다. Colab(T4)에서 돌린다.

```sh
python3 -m scripts.build_colab_bundle      # → build/WaferAI_colab_bundle.zip (23MB)
                                           #   build/colab_upload/ (9MB 조각 + 해시 + 노트북)
```

zip 을 Drive 의 `MyDrive/WaferAI/` 에 올리고 `notebooks/retrain_colab.ipynb` 를 Colab 에서 연다.
큰 파일을 한 번에 올리기 어려우면 `build/colab_upload/` 의 파일을 전부 올린다. 노트북이 조각을
이어 붙이고 SHA-256 으로 원본과 같은지 확인한 뒤에만 학습으로 넘어간다.
하이퍼파라미터는 1학기와 같고(배치 32, AdamW 5e-5, Focal Loss, AMP), 바뀐 것은 분할뿐이다.
**ImageNet 가중치에서 시작한다.** 1학기 모델에서 이어 학습하면 그 모델이 이미 본 샘플이
테스트 셋에 섞인다 — `scripts/train.py` 가 분할이 다른 가중치에서의 이어 학습을 거부한다.

맥에서는 동작 확인만 한다(`--limit 32 --epochs 1 --batch-size 4`). MPS 메모리가 한도를 넘으면
스왑 대신 즉시 오류로 멈추도록 묶어 두었다.

### 재학습 루프

```
엔지니어 검토 누적 ──▶ 500건 ──▶ 재학습 작업 자동 생성 (PENDING)
   ──▶ 관리자가 학습 데이터 내려받기 (RUNNING) ──▶ GPU 에서 학습 (--reviews)
   ──▶ 승격 판정 (고정 테스트 셋) ──▶ 통과 시 교체 ──▶ api 재시작 ──▶ 작업 자동 완료 (COMPLETED)
```

* "정답 500개" 는 검토가 끝난 **웨이퍼 수**다. 같은 웨이퍼를 여러 번 고쳐도 하나로 센다.
* 직전 *완료* 작업 이후의 검토만 센다. 실패한 작업의 검토는 다시 센다.
* 학습 데이터는 작업이 만들어진 시점에 고정된다. 그 뒤의 수정은 다음 작업 몫이다.
* 학습 데이터에는 생산 웨이퍼와 검토자 사번이 들어 있어 관리자만 내려받는다.

화면: **모델 관리** 탭 (수석 이상 조회, 관리자만 요청·내려받기·실패 처리).

### 승격 게이트

```sh
python3 -m scripts.promote_model --candidate runs/clean_v1/model.pth            # 판정만
python3 -m scripts.promote_model --candidate runs/clean_v1/model.pth --apply    # 통과 시 교체
```

후보와 현재 모델을 **같은 고정 테스트 셋으로 이 스크립트가 직접** 잰다(체크포인트에 적힌 값을
믿지 않는다). 균형 데이터와 실제 분포 양쪽 macro-F1 을 본다.

* 현재 모델이 같은 분할로 학습됐으면 공정한 비교다 — 후보가 나쁘면 거부한다.
* **현재 모델이 1학기 모델이면 비교가 공정하지 않다.** 그 모델은 이 테스트 셋의 샘플을 학습에
  썼기 때문에 점수가 부풀려져 있다. 그와 비교하면 새 모델이 항상 진다. 그래서 1학기 수치는
  참고로만 보여주고, 후보가 절대 하한(균형 macro-F1 0.85)을 넘는지만 본다.

교체하면 이전 `.pth`·`.onnx` 와 판정 기록이 `models/archive/` 에 남고 ONNX 를 다시 만든다.

### 첫 재학습 결과 (10/13, 운영 중)

Colab T4 에서 15에폭(에폭당 약 5.2분)을 끝까지 돌렸고, 검증 정확도가 가장 높았던 14에폭
(96.85%) 모델을 골랐다. 아래는 학습에 전혀 쓰지 않은 테스트 셋에서 잰 값이다. 승격 스크립트가
이 맥(MPS)에서 다시 잰 값이 Colab(CUDA)에서 잰 값과 소수 넷째 자리까지 같았다.

| 테스트 셋 | 표본 수 | 정확도 | macro-F1 |
|---|---|---|---|
| 실제 분포 | 17,504 | **97.74%** | **0.891** |
| 균형 (결함 전부 + 같은 수의 정상) | 4,844 | 96.24% | 0.918 |

클래스별 F1 (실제 분포): Edge-Ring 0.988 · none 0.990 · Center 0.931 · Near-full 0.929 ·
Random 0.890 · Edge-Loc 0.848 · Donut 0.839 · Scratch 0.820 · Loc 0.786.
실제 분포에서 낮아지는 것은 정상이 훨씬 많아 결함 클래스의 정밀도가 떨어지기 때문이다
(재현율은 두 방식이 같다).

승격 판정은 **통과**(첫 재학습이라 균형 macro-F1 0.85 하한 기준). 같은 테스트 셋에서 1학기
모델은 실제 분포 macro-F1 0.937 로 더 높게 나왔지만, 그 모델은 이 샘플들을 학습에 썼으므로
비교 기준이 아니다. 판정 기록과 1학기 모델은 `models/archive/20261013-175053/` 에 있다.

### 판정 로직 효과 (새 모델 · 테스트 셋, 10/15)

```sh
python3 -m scripts.evaluate_decisions --device mps     # 확률은 모델 해시로 data/test_probs.npz 에 캐시
```

기본 설정(확신도 0.80 · 고밀도 0.80 · 저밀도 꺼짐)에서:

| | 실제 분포 17,504건 | 균형 4,844건 |
|---|---|---|
| 사람 검토 없이 나감 | **96.42%** (그 안에서 정확도 99.23%) | 94.65% (98.41%) |
| 그중 틀린 건 (전체 대비) | **130건 = 0.74%** | 73건 = 1.51% |
| ㄴ 결함을 정상으로 | 19건 (Edge-Loc 8 · Loc 5 · Scratch 3 · Center 3) | 19건 |
| ㄴ 결함 유형 틀림 / 정상을 결함으로 | 40건 / 71건 | 40건 / 14건 |
| 검토 대기 | 3.58% — 그중 AI 1순위가 맞은 비율 57.74% | 5.35% (57.92%) |

1학기 발표의 "95.05% 통과 · 1.40% 오류" 와 같은 조건(균형 표본)으로 보면 94.65% · 1.51% 로
거의 같다. 다만 이번 값은 학습에 쓰지 않은 데이터에서 잰 것이다. 검토 대기 건에서 AI 가 맞는
비율이 58% 라, 임계값은 여전히 사람이 볼 가치가 있는 건을 골라 올리고 있다.

**확신도 임계값별** (실제 분포):

| 임계값 | 검토 대기 | 틀린 무인 통과 | 결함을 정상으로 |
|---|---|---|---|
| 0.70 | 2.14% | 1.22% | 27건 |
| 0.75 | 2.78% | 1.00% | 22건 |
| **0.80 (기본)** | **3.58%** | **0.74%** | **19건** |
| 0.85 | 5.00% | 0.49% | 12건 |
| 0.90 | 10.93% | 0.17% | 3건 |
| 0.95 | 99.92% | 0.00% | 0건 |

* 0.80 → 0.85 로 올리면 검토가 1.4%p 늘고, 정상으로 새는 결함이 19 → 12건으로 준다. 품질과
  업무량 사이의 선택이라 현장 기준으로 정할 일이다.
* **0.92 를 넘기면 사실상 전부 검토로 간다.** 이 모델의 확신도는 대부분 0.90 – 0.92 에 몰려 있다
  (Focal Loss 로 학습한 모델의 특성, 최댓값 0.97, 0.92 이상은 1.3%). 그래서 모델마다
  **확신도 프로필**(테스트 셋에서 잰 최대 확신도와 임계값별 검토율 곡선)을 `test_metrics` 에
  넣는다. 설정 화면은 슬라이더 상한을 모델의 최대 확신도에 맞추고, 값을 움직일 때 "테스트 셋
  기준 검토 대기 약 X%" 를 보여 주며 20% 를 넘으면 경고한다. 서버는 최대 확신도보다 높은
  임계값을 422 로 거부한다. 새로 학습하는 모델은 `evaluate_test` 가 프로필을 자동으로 넣고,
  첫 재학습 모델에는 `scripts.evaluate_decisions --embed-profile` 로 심었다 (메타데이터만
  바뀌어 파일 해시가 달라졌고, 가중치는 같다).

**저밀도 규칙은 여전히 해롭다.** 켜면 결함을 정상으로 내보내는 건이 19 → 140건으로 7배가 된다.
기본으로 꺼 둔 결정을 유지한다.

**이미지 경로**: 300건 모두 배열 경로와 예측이 같았다(1학기 모델은 297/300).

### 옛 ONNX 로 옛 모델을 내는 사고 방지

`.pth` 만 바꾸고 `.onnx` 를 다시 만들지 않으면, ONNX 로 도는 서버는 옛 모델을 조용히 계속 낸다.
ONNX 를 만들 때 원본 `.pth` 의 해시를 심어 두고, 서버가 기동하며 대조한다. 짝이 안 맞으면
`auto` 는 PyTorch 로 대신 돌고(느려도 맞는 쪽), `onnx` 로 고정했으면 기동을 거부한다.

## 원본

- 모델: https://drive.google.com/file/d/1AUzCSh8HZ46zwe3L1_BYTgIAsnqZhSZG/view
- 데이터: https://drive.google.com/file/d/1KUrAg_hEinV8_7UwbwT2lmN9H954pUcr/view
  (2,095,505,977바이트 — Drive 연결 도구 한도를 넘으므로 별도 로컬 다운로드 필요)
