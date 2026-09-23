# WaferAI — 웨이퍼 결함 분류 서비스

WM-811K 로 학습한 CoAtNet-0 9클래스 분류기를 웹 서비스로 배포하는 프로젝트.
Colab 학습 코드는 `training_reference.py` 에 보존돼 있다.

현재 **Phase 4** 까지 완료: 공용 전처리 · 추론 백엔드 · 판정 로직 · 인증/권한 ·
SQLAlchemy 모델 · Alembic 마이그레이션 · Grad-CAM · 검토 워크플로 · React 화면.
Docker Compose 배포는 Phase 5.

## 설치

```sh
python3 -m pip install -r requirements.txt
cp .env.example .env          # 값을 채운다
```

## 실행

```sh
python3 -m unittest discover -s tests -v       # 테스트 126개
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

## 데이터베이스

개발·테스트는 SQLite, 운영은 PostgreSQL. 같은 SQLAlchemy 모델이 양쪽에서 돌도록
JSONB 같은 Postgres 전용 타입은 쓰지 않는다.

```sh
python3 -m alembic upgrade head                        # 적용
python3 -m alembic revision --autogenerate -m "설명"    # 모델 수정 후 생성
```

`tests/test_migrations.py` 가 마이그레이션 결과와 모델 정의가 일치하는지 검사한다.
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

기능상세설명서 §3.3.2 는 `defect_ratio < 0.05 → none` 을 지시하지만, 검증 분할
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

- **완전히 독립적인 테스트 셋은 여전히 없다.** 학습 코드가 결함 샘플을 전부
  학습·검증에 써버려, 남은 미사용 데이터가 'none' 뿐이다. 위 96.45% 와 클래스별
  수치는 best 체크포인트를 고르는 데 쓰인 분할에서 나온 값이라 낙관적으로 편향돼
  있다. 발표에는 "검증 정확도" 로 표기해야 정확하다.
  'none' 20,000건의 98.22% 만이 편향 없는 추정치다.
- 깨끗한 수치를 얻으려면 train/val/test 3분할로 재학습해야 한다. 재학습 루프를
  붙이는 Phase 6 에서 같이 정리한다.

## 원본

- 모델: https://drive.google.com/file/d/1AUzCSh8HZ46zwe3L1_BYTgIAsnqZhSZG/view
- 데이터: https://drive.google.com/file/d/1KUrAg_hEinV8_7UwbwT2lmN9H954pUcr/view
  (2,095,505,977바이트 — Drive 연결 도구 한도를 넘으므로 별도 로컬 다운로드 필요)
