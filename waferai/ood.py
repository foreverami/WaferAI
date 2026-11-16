"""웨이퍼 맵처럼 생기지 않은 입력을 걸러낸다 (분포 밖 입력 감지).

모델은 무엇을 넣든 9개 클래스 중 하나를 고른다. 사각형으로 가득 찬 배열, 무작위 잡음,
체크무늬도 'Random' 이나 'Near-full' 로 그럴듯하게 판정해 버린다. 그래서 모델 앞에서
입력의 *모양* 을 본다. 실제 웨이퍼 맵은 모양이 아주 일정하다 — 학습 데이터 172,950장을
재면 (scripts/calibrate.py):

    타원 일치도(내용 영역에 내접한 타원과 다이 영역의 IoU)  99.95% 가 0.905 이상
    다이 비율(내용 영역 중 다이가 차지하는 비율)            99.9% 가 0.72 – 0.81
    다이 수                                                 99.99% 가 470 이상

기준은 이 분포의 바깥쪽에 넉넉히 둔다. 진짜 웨이퍼를 거르는 것(오탐)이 가짜를 놓치는
것보다 나쁘다. 걸린 입력은 거절하지 않고 '판정 불가 — 확인 필요' 로 사람에게 보낸다.
형식은 맞으니 사람이 보고 판단할 수 있고, 거절하면 업로드한 사람이 이유를 모른 채 막힌다.

특징은 배경(0)만 있는 테두리를 잘라낸 뒤 잰다. 같은 웨이퍼를 여백을 붙여 올려도 값이
같아야 하기 때문이다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

#: 기준 — 학습 데이터 분포의 0.05 – 99.95 백분위보다 바깥 (scripts/calibrate.py 가 다시 잰다)
MIN_ELLIPSE_IOU = 0.85
DIE_FRACTION_RANGE = (0.65, 0.86)
MIN_DIES = 200


@dataclass(frozen=True)
class ShapeCheck:
    ellipse_iou: float
    die_fraction: float
    dies: int
    in_distribution: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        data = asdict(self)
        data['reasons'] = list(self.reasons)
        return data


def crop_content(wm: np.ndarray) -> np.ndarray:
    rows = np.flatnonzero((wm > 0).any(axis=1))
    cols = np.flatnonzero((wm > 0).any(axis=0))
    if not rows.size:
        return wm[:0, :0]
    return wm[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def shape_features(wm: np.ndarray) -> tuple[float, float, int]:
    """(타원 일치도, 다이 비율, 다이 수). 다이가 없으면 (0, 0, 0)."""
    content = crop_content(np.asarray(wm))
    if not content.size:
        return 0.0, 0.0, 0
    h, w = content.shape
    dies = content > 0
    yy, xx = np.ogrid[:h, :w]
    ellipse = ((xx + 0.5 - w / 2) / (w / 2)) ** 2 + ((yy + 0.5 - h / 2) / (h / 2)) ** 2 <= 1
    union = int((dies | ellipse).sum())
    iou = int((dies & ellipse).sum()) / union if union else 0.0
    return float(iou), float(dies.mean()), int(dies.sum())


def check_shape(wm: np.ndarray) -> ShapeCheck:
    iou, fraction, dies = shape_features(wm)
    reasons = []
    if dies < MIN_DIES:
        reasons.append(f'다이가 {dies}개뿐입니다 (실제 웨이퍼는 {MIN_DIES}개 이상)')
    if iou < MIN_ELLIPSE_IOU:
        reasons.append(f'원형 웨이퍼 모양이 아닙니다 (타원 일치도 {iou:.2f}, 기준 {MIN_ELLIPSE_IOU})')
    low, high = DIE_FRACTION_RANGE
    if not low <= fraction <= high:
        reasons.append(f'다이가 차지하는 비율이 웨이퍼와 다릅니다 ({fraction:.0%}, '
                       f'실제 웨이퍼는 {low:.0%} – {high:.0%})')
    return ShapeCheck(round(iou, 4), round(fraction, 4), dies, not reasons, tuple(reasons))
