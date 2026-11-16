"""확률 보정 (temperature scaling).

Focal Loss 와 label smoothing 으로 학습한 모델은 확신도를 낮게 말한다. 테스트 셋에서
1순위 확신도가 0.90 – 0.92 에 몰려 있어서, 임계값을 0.05 만 움직여도 검토량이 몇 배로
바뀌었다. 확률 p 를 p^(1/T) 로 다시 정규화하면(로짓을 T 로 나누는 것과 같다) 1순위는 그대로
두고 확신도의 '척도' 만 바로잡는다. T 는 검증 분할에서 음의 로그우도를 최소로 하는 값으로
맞추고(scripts/calibrate.py), 효과는 학습에도 보정에도 쓰지 않은 테스트 셋으로만 잰다.

정확도는 바뀌지 않는다 — argmax 가 그대로이기 때문이다. 바뀌는 것은 '확신도 0.8' 이
실제로 80% 맞는다는 뜻이 되는 것, 그래서 임계값이 해석 가능한 손잡이가 되는 것이다.
"""
from __future__ import annotations

import numpy as np

EPSILON = 1e-12


def apply_temperature(probabilities: np.ndarray, temperature: float | None) -> np.ndarray:
    """확률(마지막 축이 클래스)에 온도를 적용한다. T 가 없거나 1 이면 그대로."""
    probs = np.asarray(probabilities, dtype=np.float64)
    if not temperature or abs(temperature - 1.0) < 1e-9:
        return probs.astype(np.float32)
    logits = np.log(np.clip(probs, EPSILON, 1.0)) / float(temperature)
    logits -= logits.max(axis=-1, keepdims=True)
    scaled = np.exp(logits)
    return (scaled / scaled.sum(axis=-1, keepdims=True)).astype(np.float32)


def negative_log_likelihood(probabilities: np.ndarray, labels: np.ndarray) -> float:
    picked = np.clip(probabilities[np.arange(len(labels)), labels], EPSILON, 1.0)
    return float(-np.log(picked).mean())


def fit_temperature(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """NLL 이 가장 작은 T 를 찾는다 (0.05 – 5, 로그 격자 후 세밀 탐색)."""
    def nll(t):
        return negative_log_likelihood(apply_temperature(probabilities, t), labels)

    grid = np.exp(np.linspace(np.log(0.05), np.log(5.0), 120))
    best = float(grid[int(np.argmin([nll(t) for t in grid]))])
    fine = np.linspace(best * 0.9, best * 1.1, 81)
    return round(float(fine[int(np.argmin([nll(t) for t in fine]))]), 4)


def expected_calibration_error(probabilities: np.ndarray, labels: np.ndarray, bins: int = 15) -> float:
    """확신도 구간별 (평균 확신도 − 실제 정답률) 의 가중 평균. 0 에 가까울수록 확신도가 정직하다."""
    confidence = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == labels
    edges = np.linspace(0.0, 1.0, bins + 1)
    error = 0.0
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (confidence > low) & (confidence <= high)
        if mask.any():
            error += mask.mean() * abs(confidence[mask].mean() - correct[mask].mean())
    return float(error)
