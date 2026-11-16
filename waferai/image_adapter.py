"""렌더링된 웨이퍼 맵 이미지(PNG/JPG)를 0/1/2 맵으로 되돌린다.

모델은 사진이 아니라 전기 검사 결과인 0/1/2 웨이퍼 맵으로 학습됐다. 이 모듈은
웨이퍼 맵을 3색으로 그린 이미지의 색을 역으로 풀어 `preprocess` 가 받을 수 있는 맵을
만든다. 조용히 잘못 해석하는 것이 가장 나쁜 실패라, 확신의 정도에 따라 셋으로 나눈다.

    1. 학습 색(검정/초록/노랑)            그대로 읽는다.
    2. 알려진 색상표(viridis, 회색조 등)   표의 순서대로 0/1/2 로 바꿔 읽는다. 경고만 붙인다.
    3. 처음 보는 3색                       배경 = 테두리 색, 결함 = 다이 중 적은 쪽 색으로
                                           *추정* 한다. 결과는 반드시 사람 검토로 보낸다
                                           (palette.guessed). Near-full 처럼 결함이 더 많은
                                           웨이퍼는 추정이 뒤집힐 수 있기 때문이다.

3색으로 설명되지 않는 이미지(사진, 그라데이션)는 거부한다.

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

#: 학습 색으로 그린 이미지는 JPEG 로 저장해도 평균 색 차이가 한 자릿수다. 이보다 크면 허용 거리 안에
#: 들어오더라도 '비슷한 다른 색' 으로 보고 색상표 해석으로 넘긴다 (노란 배경을 결함으로 읽는 사고 방지).
MAX_TRAINING_MEAN_DISTANCE = 30.0


#: 알려진 색상표 — 0/1/2 순서. matplotlib 으로 WM-811K 를 그리면 흔히 나오는 것들이다.
KNOWN_PALETTES = {
    'viridis': np.array([[68, 1, 84], [33, 145, 140], [253, 231, 37]], dtype=np.float32),
    'gray': np.array([[0, 0, 0], [128, 128, 128], [255, 255, 255]], dtype=np.float32),
    'gray_r': np.array([[255, 255, 255], [128, 128, 128], [0, 0, 0]], dtype=np.float32),
}

#: 3색 군집에서 중심과의 허용 거리, 그 밖 픽셀의 최대 비율
CLUSTER_TOLERANCE = 60.0
MAX_UNCLUSTERED_RATIO = 0.04
#: 알려진 색상표와 군집 중심의 허용 거리
PALETTE_MATCH_TOLERANCE = 45.0
#: 추정 모드에서 결함(적은 쪽)이 다이의 이 비율을 넘으면 정상과 결함을 가릴 수 없다고 본다
MAX_GUESSED_DEFECT_SHARE = 0.45


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


def three_colors(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """이미지를 3색으로 군집한다. 반환: (군집 중심 3개, 픽셀별 군집 번호, 중심에서 먼 픽셀 비율)."""
    import cv2

    pixels = rgb.reshape(-1, 3).astype(np.float32)
    sample = pixels[:: max(1, len(pixels) // 20000)]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centers = cv2.kmeans(sample, 3, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    distances = np.linalg.norm(pixels[:, None, :] - centers[None, :, :], axis=2)
    labels = distances.argmin(axis=1)
    far = float((distances.min(axis=1) > CLUSTER_TOLERANCE).mean())
    return centers, labels.reshape(rgb.shape[:2]), far


def corner_cluster(labels: np.ndarray) -> tuple[int, float]:
    """네 모서리 조각에서 가장 많은 군집과 그 비율. 원형 웨이퍼의 모서리는 늘 배경이다."""
    k = max(2, min(labels.shape) // 12)
    corners = np.concatenate([labels[:k, :k].ravel(), labels[:k, -k:].ravel(),
                              labels[-k:, :k].ravel(), labels[-k:, -k:].ravel()])
    counts = np.bincount(corners, minlength=3)
    return int(counts.argmax()), float(counts.max() / len(corners))


def match_known_palette(centers: np.ndarray, labels: np.ndarray) -> tuple[str, np.ndarray] | None:
    """군집 중심이 알려진 색상표와 맞고, 그 표의 배경색이 실제로 모서리에 있으면 (이름, 군집 → 0/1/2).

    gray 와 gray_r 은 같은 세 색을 반대 순서로 쓴다. 색만 보면 둘 다 맞으므로 배경 위치로 가른다.
    """
    background, _ = corner_cluster(labels)
    for name, palette in KNOWN_PALETTES.items():
        distance = np.linalg.norm(centers[:, None, :] - palette[None, :, :], axis=2)
        order = distance.argmin(axis=1)
        if len(set(order.tolist())) != 3 or distance[np.arange(3), order].max() > PALETTE_MATCH_TOLERANCE:
            continue
        if order[background] == 0:
            return name, order.astype(np.uint8)
    return None


def guess_palette(labels: np.ndarray) -> np.ndarray:
    """처음 보는 3색: 배경 = 네 모서리의 색, 결함 = 나머지 둘 중 적은 쪽.

    원형 웨이퍼는 둘러싼 사각형의 변에는 닿지만 모서리에는 닿지 않는다. 그래서 테두리 전체가
    아니라 네 모서리 조각을 본다.
    """
    background, share = corner_cluster(labels)
    if share < 0.75:
        raise UnsupportedImage('배경색을 찾을 수 없습니다 — 웨이퍼 바깥(네 모서리)이 한 가지 색이어야 합니다')
    others = [k for k in range(3) if k != background]
    sizes = {k: int((labels == k).sum()) for k in others}
    defect = min(others, key=sizes.get)
    normal = max(others, key=sizes.get)
    share = sizes[defect] / max(1, sizes[defect] + sizes[normal])
    if share > MAX_GUESSED_DEFECT_SHARE:
        raise UnsupportedImage(
            f'정상과 결함 색을 구분할 수 없습니다 (두 색이 {share:.0%} 대 {1 - share:.0%}). '
            '학습 색(검정/초록/노랑)이나 viridis 로 그린 이미지를 올려주세요')
    mapping = np.zeros(3, dtype=np.uint8)
    mapping[normal], mapping[defect] = 1, 2
    return mapping


def read_palette(rgb: np.ndarray) -> tuple[np.ndarray, dict]:
    """학습 색이 아닌 이미지 → (0/1/2 인덱스, 색상표 정보). 3색이 아니면 거부한다."""
    centers, labels, far = three_colors(rgb)
    if far > MAX_UNCLUSTERED_RATIO:
        raise UnsupportedImage(
            f'세 가지 색으로 그린 웨이퍼 맵이 아닙니다 — 세 색에서 벗어난 픽셀 {far:.1%}. '
            '실물 사진이나 그라데이션 이미지는 판정할 수 없습니다')
    known = match_known_palette(centers, labels)
    if known:
        name, mapping = known
        return mapping[labels], {'name': name, 'guessed': False, 'unclustered_ratio': round(far, 6)}
    mapping = guess_palette(labels)
    return mapping[labels], {'name': 'unknown', 'guessed': True, 'unclustered_ratio': round(far, 6)}


def image_to_wafer_map(data: bytes) -> tuple[np.ndarray, dict]:
    """렌더링 이미지 → (0/1/2 맵, 진단 정보)."""
    rgb = decode_image(data)
    indices, unmatched_ratio, mean_distance = snap_to_lut(rgb)
    palette = {'name': 'training', 'guessed': False}
    warnings = []
    if unmatched_ratio > MAX_UNMATCHED_RATIO or mean_distance > MAX_TRAINING_MEAN_DISTANCE:
        indices, palette = read_palette(rgb)
        if palette['guessed']:
            warnings.append('처음 보는 색 체계라 배경 · 정상 · 결함 색을 추정해서 읽었습니다. '
                            '추정이 틀릴 수 있어 사람 검토로 보냅니다')
        else:
            warnings.append(f"학습과 다른 색 체계({palette['name']})를 학습 색으로 바꿔 읽었습니다")

    wafer_map = crop_to_content(indices)
    info = {
        'source': 'image',
        'decoded_size': [int(rgb.shape[1]), int(rgb.shape[0])],
        'cropped_size': [int(wafer_map.shape[1]), int(wafer_map.shape[0])],
        'unmatched_ratio': round(unmatched_ratio, 6),
        'mean_snap_distance': round(mean_distance, 3),
        'palette': palette,
        'downsampled': False,
        'warnings': warnings,
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
