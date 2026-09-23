"""렌더링된 웨이퍼 맵 이미지(PNG/JPG)를 0/1/2 맵으로 되돌린다.

모델은 사진이 아니라 전기 검사 결과인 0/1/2 웨이퍼 맵으로 학습됐다. 이 모듈은
학습과 같은 LUT 색(검정/초록/노랑)으로 그려진 이미지에 한해 색을 역으로 풀어
`preprocess` 가 받을 수 있는 맵을 만든다. 색 체계가 다른 이미지나 웨이퍼 실물
사진은 여기서 거부해야 하며, 조용히 잘못 해석하는 것이 가장 나쁜 실패다.

주의 — 이중 리샘플링:
    렌더링 이미지는 이미 한 번 224 로 확대된 결과일 수 있다. 여기서 또 축소하면
    폭이 1~2 다이뿐인 Scratch 결함이 사라질 수 있다. 그래서 224 로 내보낸
    이미지를 권장하고, 큰 이미지는 축소 사실을 경고로 돌려준다.
"""
from __future__ import annotations

import cv2
import numpy as np

from waferai.preprocess import COLOR_LUT, TARGET_SIZE, pad_to_square

#: 디코딩을 허용하는 최대 변 길이. 넘으면 거부한다.
MAX_DECODE_SIDE = 4096

#: 이 크기를 넘는 맵은 저장 전에 224 로 줄인다(리샘플링 1회로 끝내기 위해).
STORE_LIMIT = 512

#: LUT 색과의 허용 RGB 거리. LUT 색 사이 최소 거리가 255 이므로 그 절반(127.5)
#: 보다 조금 크게 두어, 안티에일리어싱으로 생긴 중간색은 통과시키고 팔레트 밖
#: 색(회색 185, 빨강·파랑 255)은 걸러낸다.
SNAP_TOLERANCE = 140.0

#: 허용 거리를 벗어난 픽셀의 최대 비율.
MAX_UNMATCHED_RATIO = 0.02


class UnsupportedImage(ValueError):
    """웨이퍼 맵 렌더링 이미지로 해석할 수 없는 입력."""


def decode_image(data: bytes) -> np.ndarray:
    """이미지 바이트 → (H, W, 3) uint8 RGB."""
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise UnsupportedImage('이미지를 디코딩할 수 없습니다 (PNG 또는 JPG 를 올려주세요)')
    if image.dtype != np.uint8:
        raise UnsupportedImage(f'8비트 이미지만 지원합니다 (현재 {image.dtype})')

    if image.ndim == 2:                                  # 흑백
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    elif image.shape[2] == 4:                            # 알파 → 검정 배경에 합성
        rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB).astype(np.float32)
        alpha = (image[:, :, 3:4].astype(np.float32)) / 255.0
        image = np.round(rgb * alpha).astype(np.uint8)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    else:
        raise UnsupportedImage(f'지원하지 않는 채널 수입니다 ({image.shape[2]})')

    if max(image.shape[:2]) > MAX_DECODE_SIDE:
        raise UnsupportedImage(
            f'이미지가 너무 큽니다 (최대 {MAX_DECODE_SIDE}px, 현재 {image.shape[1]}x{image.shape[0]})')
    return image


def snap_to_lut(rgb: np.ndarray) -> tuple[np.ndarray, float, float]:
    """가장 가까운 LUT 색으로 스냅해 0/1/2 인덱스를 만든다.

    JPEG 압축은 색을 미세하게 흔들기 때문에 정확히 일치하는 값을 찾으면 안 된다.
    반환: (인덱스 맵, 허용 거리를 벗어난 픽셀 비율, 평균 거리)
    """
    distances = np.linalg.norm(
        rgb[:, :, None, :].astype(np.float32) - COLOR_LUT[None, None, :, :].astype(np.float32),
        axis=3,
    )
    indices = distances.argmin(axis=2).astype(np.uint8)
    nearest = distances.min(axis=2)
    return indices, float((nearest > SNAP_TOLERANCE).mean()), float(nearest.mean())


def crop_to_content(wm: np.ndarray) -> np.ndarray:
    """배경(0)만 있는 테두리를 잘라낸다.

    렌더링 이미지는 이미 정사각 패딩이 된 상태다. 그대로 두고 또 패딩하면 웨이퍼가
    화면에서 작아져 학습 분포와 어긋나므로, 내용 영역만 남긴 뒤 표준 경로에 넘긴다.
    """
    rows = np.flatnonzero(wm.any(axis=1))
    cols = np.flatnonzero(wm.any(axis=0))
    if not rows.size or not cols.size:
        raise UnsupportedImage('웨이퍼 영역을 찾을 수 없습니다 (이미지가 전부 배경색입니다)')
    return wm[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def image_to_wafer_map(data: bytes) -> tuple[np.ndarray, dict]:
    """렌더링 이미지 → (0/1/2 맵, 진단 정보)."""
    rgb = decode_image(data)
    indices, unmatched_ratio, mean_distance = snap_to_lut(rgb)
    if unmatched_ratio > MAX_UNMATCHED_RATIO:
        raise UnsupportedImage(
            f'학습에 쓰인 색 체계(검정 배경 / 초록 정상 / 노랑 결함)와 다릅니다 — '
            f'팔레트 밖 픽셀 {unmatched_ratio:.1%}. 웨이퍼 맵 렌더링 이미지를 올려주세요')

    wafer_map = crop_to_content(indices)
    info = {
        'source': 'image',
        'decoded_size': [int(rgb.shape[1]), int(rgb.shape[0])],
        'cropped_size': [int(wafer_map.shape[1]), int(wafer_map.shape[0])],
        'unmatched_ratio': round(unmatched_ratio, 6),
        'mean_snap_distance': round(mean_distance, 3),
        'downsampled': False,
        'warnings': [],
    }

    if max(wafer_map.shape) > STORE_LIMIT:
        # 리샘플링을 1회로 끝내기 위해 여기서 곧장 224 까지 줄인다.
        # 이후 preprocess 의 패딩·리사이즈는 항등 연산이 된다.
        wafer_map = cv2.resize(pad_to_square(wafer_map), TARGET_SIZE,
                               interpolation=cv2.INTER_NEAREST)
        info['downsampled'] = True
        info['warnings'].append(
            '이미지 해상도가 커서 224x224 로 축소했습니다. 폭이 좁은 결함(Scratch)이 '
            '손실될 수 있으니 224x224 로 내보낸 이미지를 권장합니다')
    return wafer_map, info


def render_wafer_map(wm: np.ndarray, size: int | None = None) -> np.ndarray:
    """0/1/2 맵 → 학습과 같은 색의 RGB 이미지.

    라운드트립 테스트와 화면의 예제 생성에 쓴다. `size` 를 주면 그 크기로 확대한다.
    """
    if size is not None:
        wm = cv2.resize(pad_to_square(wm), (size, size), interpolation=cv2.INTER_NEAREST)
    return COLOR_LUT[wm]


def encode_png(rgb: np.ndarray) -> bytes:
    """RGB 배열 → PNG 바이트. OpenCV 는 BGR 로 받으므로 여기서만 뒤집는다."""
    ok, buffer = cv2.imencode('.png', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError('PNG 인코딩에 실패했습니다')
    return buffer.tobytes()
