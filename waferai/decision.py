"""AI 확률 → 처리 경로 판정 (Human-in-the-Loop 분기점).

기능상세설명서 §3.3.2 와 플로우차트 §2.2 가 서로 다른 규칙을 말하고, 기능상세설명서
쪽에는 정의되지 않은 구간이 있다. 확신도 0.60~0.80 을 "Rule-Base Pass" 로 보내지만
밀도 규칙이 낼 수 있는 답은 none 과 Near-full 둘뿐이라, 밀도가 0.05~0.80 사이인
웨이퍼는 갈 곳이 없다.

여기서는 그 구간을 없앤 단계 판정으로 통일한다. 위에서부터 순서대로 검사한다.

    ① 밀도 < low_density   → none,      RULE_BASE   (기본 꺼짐 — 아래 참고)
    ② 밀도 > high_density  → Near-full, RULE_BASE   (기본 0.80)
    ③ 확신도 ≥ confidence  → AI 1순위,  AUTO_PASS
    ④ 그 외                → AI 1순위,  REVIEW_NEEDED (엔지니어 확정 전까지 잠정)

애초에 ①②를 AI 앞에 둔 것은 "결함이 거의 없거나 거의 전부인 웨이퍼는 픽셀 통계가
AI 보다 믿을 만하다"는 가정이었다. 실제 데이터로 재 보니 ①에서는 그 가정이 틀렸고,
지금은 기본으로 끈다. 근거는 `Thresholds` 문서화 참고.

임계값은 하드코딩하지 않는다. UIUX 문서 화면 6·7 에 엔지니어가 조정하는 슬라이더가
설계돼 있으므로 설정값으로 주입받는다.
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
    """판정 임계값. 운영 중 설정 화면에서 바뀔 수 있다.

    low_density 기본값이 None(규칙 끔)인 이유 — 검증 분할 10,208건 측정 결과:

        저밀도 규칙 켬(0.05)  전체 정확도 93.78%  잘못 새어나간 건 430건
        저밀도 규칙 끔        전체 정확도 96.45%  잘못 새어나간 건 143건

    규칙에 걸린 1,087건 중 291건이 실제로는 결함이었다(Loc 118, Edge-Ring 54,
    Scratch 50, Edge-Loc 38, Center 31). 같은 건들을 AI 에게 맡기면 98.34% 로
    맞힌다. 결함 다이가 5% 미만이어도 얇은 Scratch 나 작은 Loc 은 명백한 결함인데,
    픽셀을 세는 규칙은 패턴을 못 보기 때문이다. 0.01 까지 낮춰도 규칙 정확도는
    9.1% 에 그쳐, 임계값 조정이 아니라 규칙 자체가 틀렸다.

    기능상세설명서 §3.3.2 의 "defect_ratio < 0.05 → none" 설계는 이 측정으로
    반증됐다. 설정으로 되살릴 수는 있게 두되 기본은 끈다.

    high_density 는 유지한다. 0.80 에서 걸린 20건이 전부 실제 Near-full 이었고
    AI 도 같은 답을 냈다(규칙 100% / AI 100%). 측정상 이득은 없지만, 모델이
    드리프트해도 거의 전면 불량인 웨이퍼는 확정적으로 잡아주는 방어선이 된다.
    """

    low_density: float | None = None
    high_density: float | None = 0.80
    confidence: float = 0.80

    def __post_init__(self) -> None:
        for name in ('low_density', 'high_density', 'confidence'):
            value = getattr(self, name)
            if value is None:
                continue
            if not 0.0 <= value <= 1.0:
                raise ValueError(f'{name} 은 0.0~1.0 이어야 합니다 (현재 {value})')
        if self.low_density is not None and self.high_density is not None \
                and self.low_density >= self.high_density:
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

    if thresholds.low_density is not None and defect_ratio < thresholds.low_density:
        final_class, path = CLASS_NONE, DecisionPath.RULE_BASE_NONE
    elif thresholds.high_density is not None and defect_ratio > thresholds.high_density:
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
