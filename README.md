# WaferAI — 웨이퍼 결함 분류 서비스

WM-811K 로 학습한 CoAtNet-0 9클래스 분류기를 웹 서비스로 배포하는 프로젝트.
Colab 학습 코드는 `training_reference.py` 에 보존돼 있다.

현재 **Phase 1** 까지 완료: 공용 전처리 · 추론 백엔드 · 판정 로직 · `/api/predict`.
인증과 PostgreSQL 은 Phase 2, Grad-CAM 은 Phase 3 에서 붙인다.

## 설치

```sh
python3 -m pip install -r requirements.txt
```

## 실행

```sh
python3 -m unittest discover -s tests -v       # 테스트 44개
python3 -m scripts.export_onnx                 # .pth → .onnx (동등성 검증 포함)
python3 -m scripts.benchmark                   # 배포 서버에서 백엔드 실측
python3 -m uvicorn waferai.server:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 연다.

```sh
python3 -m waferai.inference --image wafer.png   # 렌더링 이미지로 예측
python3 -m waferai.inference --map wafer.npy     # 0/1/2 맵으로 예측
```

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

| 순서 | 조건 | 결과 | 경로 |
|---|---|---|---|
| ① | 결함밀도 < 0.05 | `none` | `RULE_BASE_NONE` |
| ② | 결함밀도 > 0.80 | `Near-full` | `RULE_BASE_NEAR_FULL` |
| ③ | 확신도 ≥ 0.80 | AI 1순위 | `AUTO_PASS` |
| ④ | 그 외 | AI 1순위(잠정) | `REVIEW_NEEDED` |

결함밀도 = 값2 / (값1 + 값2). 배경은 분모에서 뺀다. 임계값 3개는
`Thresholds` 로 주입하며, Phase 2 에서 설정 테이블로 옮긴다.

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
