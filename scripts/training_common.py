"""학습(train.py)과 승격(promote_model.py)이 함께 쓰는 데이터·평가 도구.

전처리는 여기서 다시 구현하지 않는다. 서빙과 같은 waferai.preprocess 를 쓴다.
학습과 서빙의 전처리가 갈라지면 정확도가 조용히 무너지기 때문이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from waferai.preprocess import to_model_input

CLASS_NAMES = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
               'Near-full', 'Random', 'Scratch', 'none']
NONE_INDEX = CLASS_NAMES.index('none')
SPLITS = {'train': 0, 'val': 1, 'test': 2}
DEFAULT_DATA = 'data/training_set.npz'


@dataclass
class TrainingSet:
    maps: list[np.ndarray]
    labels: np.ndarray
    split: np.ndarray
    sample_ids: np.ndarray
    split_id: str

    def indices(self, name: str) -> np.ndarray:
        return np.flatnonzero(self.split == SPLITS[name])


def unpack(flat: np.ndarray, shapes: np.ndarray) -> list[np.ndarray]:
    maps, offset = [], 0
    for height, width in shapes:
        size = int(height) * int(width)
        maps.append(flat[offset:offset + size].reshape(int(height), int(width)))
        offset += size
    return maps


def load_training_set(path=DEFAULT_DATA) -> TrainingSet:
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'학습 데이터가 없습니다: {path}\n'
                         '  python3 -m scripts.prepare_training_data --source ~/Downloads/LSWMD.pkl')
    data = np.load(path, allow_pickle=False)
    names = [str(name) for name in data['class_names']]
    if names != CLASS_NAMES:
        raise SystemExit(f'클래스 순서가 다릅니다: {names}')
    return TrainingSet(maps=unpack(data['flat'], data['shapes']),
                       labels=data['labels'].astype(np.int64),
                       split=data['split'], sample_ids=data['sample_ids'],
                       split_id=str(data['split_id']))


def balanced(indices: np.ndarray, labels: np.ndarray, seed: int) -> np.ndarray:
    """결함 전부 + 같은 수의 정상(none). 1학기 학습과 같은 균형 맞추기다."""
    rng = np.random.default_rng(seed)
    defects = indices[labels[indices] != NONE_INDEX]
    normals = indices[labels[indices] == NONE_INDEX]
    chosen = rng.choice(normals, size=min(len(defects), len(normals)), replace=False)
    return np.sort(np.concatenate([defects, chosen])).astype(np.int64)


def probabilities(model, maps, device: str, batch_size: int = 32) -> np.ndarray:
    """(N, 9) 확률. 서빙과 똑같은 to_model_input 을 거친다."""
    import torch

    model.eval()
    outputs = []
    with torch.inference_mode():
        for start in range(0, len(maps), batch_size):
            batch = np.concatenate([to_model_input(m) for m in maps[start:start + batch_size]])
            logits = model(torch.from_numpy(batch).to(device))
            outputs.append(logits.float().softmax(dim=1).cpu().numpy())
    return np.concatenate(outputs) if outputs else np.zeros((0, len(CLASS_NAMES)))


def metrics(true: np.ndarray, predicted: np.ndarray) -> dict:
    from sklearn.metrics import f1_score

    labels = list(range(len(CLASS_NAMES)))
    per_class = f1_score(true, predicted, labels=labels, average=None, zero_division=0)
    return {
        'n': int(len(true)),
        'accuracy': float((true == predicted).mean()) if len(true) else 0.0,
        'macro_f1': float(f1_score(true, predicted, labels=labels, average='macro',
                                   zero_division=0)),
        'per_class_f1': {name: round(float(score), 4) for name, score in zip(CLASS_NAMES, per_class)},
    }


#: 확신도 프로필을 재는 임계값 눈금 — 설정 화면 슬라이더와 같은 0.01 간격
CONFIDENCE_GRID = [round(0.50 + 0.01 * step, 2) for step in range(50)]      # 0.50 … 0.99


def confidence_profile(probs: np.ndarray) -> dict:
    """모델이 내는 확신도의 분포 — 설정 화면이 임계값의 효과를 미리 보여 주는 데 쓴다.

    review_curve 는 (임계값, 그 값 미만이라 검토로 가는 비율) 의 목록이다. 밀도 규칙은 빼고
    확신도만 본 값이라 실제 검토율의 상한에 가깝다. confidence_max 를 넘는 임계값은 모든
    웨이퍼를 검토로 보내므로 서버가 설정 상한으로 쓴다. Focal Loss 로 학습한 모델은
    확신도가 좁은 구간(0.90 – 0.92)에 몰려, 이 곡선 없이는 임계값 0.05 차이가 검토량을
    몇 배로 바꾸는 것을 알 수 없다.
    """
    top1 = probs.max(axis=1) if len(probs) else np.zeros(0)
    return {
        'n': int(len(top1)),
        'confidence_max': round(float(top1.max()), 4) if len(top1) else 0.0,
        'review_curve': [[threshold, round(float((top1 < threshold).mean()), 4)]
                         for threshold in CONFIDENCE_GRID] if len(top1) else [],
    }


def evaluate_test(model, dataset: TrainingSet, device: str, seed: int = 7,
                  limit: int | None = None, batch_size: int = 32) -> dict:
    """고정 테스트 셋 평가. 두 가지로 잰다.

    balanced — 결함 전부 + 같은 수의 정상. 1학기 val_acc 96.45% 와 같은 조건.
    natural  — 테스트 셋 전체. 정상이 압도적인 실제 분포에 가깝다.
    """
    test = dataset.indices('test')
    if limit:
        test = test[:limit]
    probs = probabilities(model, [dataset.maps[i] for i in test], device, batch_size)
    predicted = probs.argmax(axis=1)
    true = dataset.labels[test]

    balanced_idx = balanced(test, dataset.labels, seed)
    position = {index: row for row, index in enumerate(test)}
    # 빈 목록을 그냥 배열로 만들면 실수형이 되어 인덱스로 쓸 수 없다 (표본이 적을 때 결함이 0개일 수 있다)
    rows = np.array([position[i] for i in balanced_idx], dtype=np.int64)
    return {
        'split_id': dataset.split_id,
        'balanced': metrics(true[rows], predicted[rows]),
        'natural': metrics(true, predicted),
        # 실제 분포(테스트 셋 전체)에서 잰다 — 운영에서 들어오는 분포에 가장 가깝다
        'confidence_profile': confidence_profile(probs),
    }


def pick_device(requested: str = 'auto') -> str:
    import torch

    if requested != 'auto':
        return requested
    if torch.cuda.is_available():
        return 'cuda'
    if torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'
