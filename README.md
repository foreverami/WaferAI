# WaferAI 추론 검증

사용자가 제공한 Colab 학습 코드를 `training_reference.py`에 보존했습니다.
기존 `/Users/jowongon/캡스톤 디자인`의 파일은 수정하지 않았습니다.

## 실행

현재 작업 폴더에서 다음 명령을 실행합니다.

```sh
python3 -m unittest discover -s tests -v
python3 -m waferai.inference
python3 -m waferai.inference --map sample.npy
```

기본 모델 경로는 `models/best_coatnet_model_optimized.pth`입니다.
입력은 값이 0, 1, 2인 2차원 웨이퍼 맵을 저장한 `.npy` 파일입니다.
일반 사진이나 JPEG를 입력받는 인터페이스가 아닙니다.
패딩, 최근접 리사이즈, RGB 매핑, 정규화는 학습 코드의 검증 경로를 따릅니다.
모델 구조와 체크포인트가 맞지 않으면 실패하며 임의 가중치로 예측하지 않습니다.

## 검증 범위

테스트는 학습 전처리와의 수치 일치, 잘못된 입력 거부, 가중치 누락 시 중단을 검증합니다.
`val_acc`는 체크포인트가 기록한 값이며 독립 테스트 정확도가 아닙니다.
0.8 검토 임계값은 기존 추론 코드에서 가져온 임시 기준으로, 성능 검증이 필요합니다.
합성 입력으로 추론 성공을 확인하더라도 실제 데이터 정확도를 증명하지 않습니다.

## 원본

- 모델: https://drive.google.com/file/d/1AUzCSh8HZ46zwe3L1_BYTgIAsnqZhSZG/view
- 데이터: https://drive.google.com/file/d/1KUrAg_hEinV8_7UwbwT2lmN9H954pUcr/view

데이터 파일은 2,095,505,977바이트로 Drive 연결 도구의 268,435,456바이트 다운로드 한도를 초과합니다.
`LSWMD.pkl`은 별도 로컬 다운로드가 필요합니다.

## 로컬 웹 프로그램

```sh
python3 -m uvicorn waferai.server:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다.
NPY 외에 헤더 없는 숫자 CSV, 2차원 배열 JSON을 업로드할 수 있습니다(최대 2MB, 512×512).
화면의 합성 예제를 다운로드한 뒤 업로드하여 전체 흐름을 확인할 수 있습니다.
예측·입력 맵·모델 SHA-256·검토 이력을 `data/waferai.sqlite3`에 보존합니다.
원래 예측은 유지하고 검토 라벨은 별도 누적합니다. 최근 200건을 화면에 표시합니다.
로그인 없는 단일 사용자 로컬 프로토타입입니다. Grad-CAM, 센서 통합, 재학습은 아직 연결하지 않았습니다.
