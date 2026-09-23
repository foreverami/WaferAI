"""웨이퍼 맵 전처리 — 학습과 서빙이 공유하는 유일한 정의.

training_reference.py 의 `WaferDataset.__getitem__` + `val_transform`(증강 제외)
경로를 그대로 재현한다. 순서가 학습과 어긋나면 정확도가 무너지므로
이 모듈 밖에서 패딩·리사이즈·색 변환을 다시 구현하지 않는다.

    원본 맵(0/1/2) → 정사각 제로 패딩 → 224 INTER_NEAREST → 컬러 LUT
                   → /255 → ImageNet 정규화 → (1, 3, 224, 224)

tests/test_preprocess.py 가 torchvision 기준 구현과 rtol=0, atol=0 으로
일치함을 검증한다.
"""
from __future__ import annotations

import cv2
import numpy as np

TARGET_SIZE = (224, 224)
VALID_VALUES = (0, 1, 2)

#: 학습 `WaferDataset.COLOR_LUT` 와 동일. RGB 순서이며 BGR 로 바꾸지 않는다.
COLOR_LUT = np.array(
    [
        [0, 0, 0],        # 0 배경
        [0, 255, 0],      # 1 정상 다이
        [255, 255, 0],    # 2 결함 다이
    ],
    dtype=np.uint8,
)

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def validate_map(wafer_map) -> np.ndarray:
    """0/1/2 값만 가진 비어 있지 않은 2차원 배열로 정규화한다."""
    wm = np.asarray(wafer_map)
    if wm.ndim != 2 or not wm.size or not np.isin(wm, VALID_VALUES).all():
        raise ValueError('0, 1, 2 값만 가진 비어 있지 않은 2차원 웨이퍼 맵이어야 합니다')
    return wm.astype(np.uint8)


def pad_to_square(wm: np.ndarray) -> np.ndarray:
    """0 으로 정사각 패딩. 나누어떨어지지 않는 1픽셀은 학습과 같이 하단/우측에 둔다."""
    h, w = wm.shape
    side = max(h, w)
    pad_h, pad_w = (side - h) // 2, (side - w) // 2
    return np.pad(wm, ((pad_h, side - h - pad_h), (pad_w, side - w - pad_w)))


def to_rgb(wm: np.ndarray) -> np.ndarray:
    """(224, 224, 3) uint8 RGB.

    리사이즈를 라벨맵(0/1/2) 상태에서 끝낸 뒤 LUT 를 적용한다. 순서를 바꾸면
    보간 방식에 따라 학습에 없던 중간색이 생긴다.
    """
    resized = cv2.resize(pad_to_square(wm), TARGET_SIZE, interpolation=cv2.INTER_NEAREST)
    return COLOR_LUT[resized]


def to_model_input(wafer_map) -> np.ndarray:
    """(1, 3, 224, 224) float32 — 모델에 그대로 넣을 수 있는 배열."""
    rgb = to_rgb(validate_map(wafer_map))
    chw = rgb.astype(np.float32).transpose(2, 0, 1) / np.float32(255)
    normalized = (chw - IMAGENET_MEAN[:, None, None]) / IMAGENET_STD[:, None, None]
    return normalized[None, ...]


def defect_ratio(wafer_map) -> float:
    """결함 다이 비율 = 값 2 / (값 1 + 값 2).

    배경(0)은 분모에서 뺀다. 넣으면 같은 불량률이라도 웨이퍼 크기와 여백에 따라
    값이 달라진다. 패딩 전 원본 맵에서 세야 하므로 `to_rgb` 앞에서 호출한다.
    """
    wm = validate_map(wafer_map)
    die_count = int((wm == 1).sum()) + int((wm == 2).sum())
    return int((wm == 2).sum()) / die_count if die_count else 0.0
