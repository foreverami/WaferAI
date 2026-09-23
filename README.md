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

## 검증 범위 — 아직 증명되지 않은 것

- **독립 테스트 셋이 없다.** 체크포인트의 `val_acc` 96.45% 는 검증 정확도이며,
  'none' 을 언더샘플링한 균형 데이터 기준이다. 학습 코드는 train/val 8:2 분할만
  하고 테스트 셋을 떼지 않았다. 실제 분포에서의 성능은 다를 수 있다.
- 이미지 경로의 정확도 영향은 합성 웨이퍼 15건에서 클래스 일치 15/15,
  확률 차이 최대 0.009 로 확인했다. **실제 WM-811K 데이터로는 아직 재지 않았다.**
- 0.8 검토 임계값은 기존 코드에서 가져온 값으로, 성능 근거가 없다.

Phase 1.5 에서 `LSWMD.pkl` 을 내려받아 위 셋을 모두 측정해야 한다.

## 원본

- 모델: https://drive.google.com/file/d/1AUzCSh8HZ46zwe3L1_BYTgIAsnqZhSZG/view
- 데이터: https://drive.google.com/file/d/1KUrAg_hEinV8_7UwbwT2lmN9H954pUcr/view
  (2,095,505,977바이트 — Drive 연결 도구 한도를 넘으므로 별도 로컬 다운로드 필요)
