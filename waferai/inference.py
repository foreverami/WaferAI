"""웨이퍼 결함 추론 — 전처리·백엔드·판정을 묶는 진입점.

    from waferai.inference import Predictor
    predictor = Predictor.from_paths('models/best_coatnet_model_optimized.pth',
                                     'models/coatnet_wafer.onnx')
    result = predictor.predict(wafer_map)

CLI:
    python3 -m waferai.inference                      # 모델 로드만 확인
    python3 -m waferai.inference --map sample.npy     # 맵 파일로 예측
    python3 -m waferai.inference --image sample.png   # 렌더링 이미지로 예측
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from waferai.backends import CLASSES, MODEL_NAME, PredictorBackend, build_backend
from waferai.decision import Thresholds, decide
from waferai.preprocess import defect_ratio, to_model_input, validate_map

__all__ = ['CLASSES', 'MODEL_NAME', 'Predictor', 'preprocess', 'load_model', 'predict']

DEFAULT_CHECKPOINT = 'models/best_coatnet_model_optimized.pth'
DEFAULT_ONNX = 'models/coatnet_wafer.onnx'


class Predictor:
    """맵 하나를 받아 확률과 처리 경로를 돌려준다."""

    def __init__(self, backend: PredictorBackend, thresholds: Thresholds | None = None):
        self.backend = backend
        self.thresholds = thresholds or Thresholds()

    @classmethod
    def from_paths(cls, checkpoint=DEFAULT_CHECKPOINT, onnx_path=DEFAULT_ONNX,
                   prefer: str = 'auto', thresholds: Thresholds | None = None) -> 'Predictor':
        return cls(build_backend(checkpoint, onnx_path, prefer), thresholds)

    @property
    def metadata(self) -> dict:
        return {'backend': self.backend.name, **getattr(self.backend, 'metadata', {})}

    def predict(self, wafer_map, thresholds: Thresholds | None = None) -> dict:
        wm = validate_map(wafer_map)
        probabilities = self.backend.probabilities(to_model_input(wm))
        distribution = {name: float(p) for name, p in zip(CLASSES, probabilities)}
        result = decide(distribution, defect_ratio(wm), thresholds or self.thresholds)
        result['probabilities'] = distribution
        result['map_size'] = [int(wm.shape[1]), int(wm.shape[0])]
        # 하위 호환 — 기존 응답을 쓰던 화면이 바로 깨지지 않도록 유지한다.
        result['predicted_class'] = result['final_class']
        result['confidence'] = result['ai_top1']['confidence']
        return result


# ---------------------------------------------------------------------------
# 이전 함수형 API. server.py 와 기존 테스트가 쓰고 있어 유지한다.
# ---------------------------------------------------------------------------

def preprocess(wafer_map):
    """(1, 3, 224, 224) torch.Tensor. 수치는 `preprocess.to_model_input` 과 동일하다."""
    import torch

    return torch.from_numpy(to_model_input(wafer_map))


def load_model(path=DEFAULT_CHECKPOINT, device: str = 'cpu'):
    """PyTorch 모델과 체크포인트 메타데이터. Grad-CAM 등 torch 가 필요한 경로용."""
    from waferai.backends import TorchBackend

    backend = TorchBackend(path, device)
    return backend.model, backend.metadata


def predict(model, wafer_map) -> dict:
    """이미 만들어 둔 torch 모델로 예측한다."""
    import torch

    wm = validate_map(wafer_map)
    device = next(model.parameters()).device
    with torch.inference_mode():
        probabilities = model(preprocess(wm).to(device)).softmax(dim=1)[0].cpu().numpy()
    distribution = {name: float(p) for name, p in zip(CLASSES, probabilities)}
    result = decide(distribution, defect_ratio(wm))
    result['probabilities'] = distribution
    result['predicted_class'] = result['final_class']
    result['confidence'] = result['ai_top1']['confidence']
    return result


def _load_input(args) -> np.ndarray | None:
    if args.map:
        return np.load(args.map, allow_pickle=False)
    if args.image:
        from waferai.image_adapter import image_to_wafer_map

        wafer_map, info = image_to_wafer_map(Path(args.image).read_bytes())
        for warning in info['warnings']:
            print(f'[경고] {warning}')
        return wafer_map
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 추론')
    parser.add_argument('--checkpoint', default=DEFAULT_CHECKPOINT)
    parser.add_argument('--onnx', default=DEFAULT_ONNX)
    parser.add_argument('--backend', default='auto', choices=['auto', 'onnx', 'torch'])
    parser.add_argument('--map', help='0/1/2 값을 담은 .npy 웨이퍼 맵')
    parser.add_argument('--image', help='학습과 같은 색으로 렌더링된 웨이퍼 맵 PNG/JPG')
    args = parser.parse_args()

    predictor = Predictor.from_paths(args.checkpoint, args.onnx, args.backend)
    output = {'model': predictor.metadata}
    wafer_map = _load_input(args)
    if wafer_map is not None:
        output['prediction'] = predictor.predict(wafer_map)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
