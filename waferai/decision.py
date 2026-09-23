"""AI 확률 → 처리 경로 판정 (Human-in-the-Loop 분기점).

기능상세설명서 §3.3.2 와 플로우차트 §2.2 가 서로 다른 규칙을 말하고, 기능상세설명서
쪽에는 정의되지 않은 구간이 있다. 확신도 0.60~0.80 을 "Rule-Base Pass" 로 보내지만
밀도 규칙이 낼 수 있는 답은 none 과 Near-full 둘뿐이라, 밀도가 0.05~0.80 사이인
웨이퍼는 갈 곳이 없다.

여기서는 그 구간을 없앤 4단계로 통일한다. 위에서부터 순서대로 검사한다.

    ① 밀도 < 0.05   → none,      RULE_BASE  (AI 무시)
    ② 밀도 > 0.80   → Near-full, RULE_BASE  (AI 무시)
    ③ 확신도 ≥ 0.80 → AI 1순위,  AUTO_PASS
    ④ 그 외         → AI 1순위,  REVIEW_NEEDED (엔지니어 확정 전까지 잠정)

①②를 AI 보다 먼저 두는 이유는, 결함이 거의 없거나 거의 전부인 웨이퍼는 픽셀 통계가
AI 보다 신뢰할 만하기 때문이다. 문서가 말한 "Rule-Base 방어선"의 취지다.

임계값 3개는 하드코딩하지 않는다. UIUX 문서 화면 6·7 에 엔지니어가 조정하는
슬라이더가 설계돼 있으므로 설정값으로 주입받는다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum

CLASS_NONE = 'none'
CLASS_NEAR_FULL = 'Near-full'


class DecisionPath(str, Enum):
    """웨이퍼가 어느 경로로 처리됐는지. UI 뱃지 색과 1:1 대응한다."""

    RULE_BASE_NONE = 'RULE_BASE_NONE'            # 보라 — 밀도가 낮아 정상 확정
    RULE_BASE_NEAR_FULL = 'RULE_BASE_NEAR_FULL'  # 보라 — 밀도가 높아 Near-full 강제
    AUTO_PASS = 'AUTO_PASS'                      # 초록 — AI 확신도 충족
    REVIEW_NEEDED = 'REVIEW_NEEDED'              # 빨강 — 엔지니어 검토 대기


@dataclass(frozen=True)
class Thresholds:
    """판정 임계값. 운영 중 설정 화면에서 바뀔 수 있다."""

    low_density: float = 0.05
    high_density: float = 0.80
    confidence: float = 0.80

    def __post_init__(self) -> None:
        for name in ('low_density', 'high_density', 'confidence'):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f'{name} 은 0.0~1.0 이어야 합니다 (현재 {value})')
        if self.low_density >= self.high_density:
            raise ValueError('low_density 는 high_density 보다 작아야 합니다')

    def as_dict(self) -> dict:
        return asdict(self)


def decide(probabilities: dict[str, float], defect_ratio: float,
           thresholds: Thresholds | None = None) -> dict:
    """확률 분포와 결함 밀도로 최종 클래스와 처리 경로를 정한다.

    `probabilities` 는 클래스명 → 확률. `defect_ratio` 는 패딩 전 원본 맵에서
    배경을 제외하고 센 결함 비율(`preprocess.defect_ratio`).
    """
    if not probabilities:
        raise ValueError('확률 분포가 비어 있습니다')
    thresholds = thresholds or Thresholds()

    ranked = sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)
    top1 = {'class': ranked[0][0], 'confidence': float(ranked[0][1])}
    top2 = {'class': ranked[1][0], 'confidence': float(ranked[1][1])} if len(ranked) > 1 else None

    if defect_ratio < thresholds.low_density:
        final_class, path = CLASS_NONE, DecisionPath.RULE_BASE_NONE
    elif defect_ratio > thresholds.high_density:
        final_class, path = CLASS_NEAR_FULL, DecisionPath.RULE_BASE_NEAR_FULL
    elif top1['confidence'] >= thresholds.confidence:
        final_class, path = top1['class'], DecisionPath.AUTO_PASS
    else:
        final_class, path = top1['class'], DecisionPath.REVIEW_NEEDED

    return {
        'final_class': final_class,
        'decision_path': path.value,
        'requires_human_review': path is DecisionPath.REVIEW_NEEDED,
        'rule_base_applied': path in (DecisionPath.RULE_BASE_NONE,
                                      DecisionPath.RULE_BASE_NEAR_FULL),
        'ai_top1': top1,
        'ai_top2': top2,
        'defect_ratio': float(defect_ratio),
        'thresholds': thresholds.as_dict(),
    }
