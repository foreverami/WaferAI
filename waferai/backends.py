"""추론 백엔드 — PyTorch 와 ONNX Runtime 을 같은 인터페이스 뒤에 둔다.

`/predict` 는 ONNX Runtime 을 쓰고, PyTorch 는 Grad-CAM 전용으로 남긴다.
ONNX Runtime 은 순전파만 하므로 역전파가 필요한 Grad-CAM 을 돌릴 수 없다.

두 경로가 갈라지면 조용히 다른 답을 낼 수 있으므로,
tests/test_backend_parity.py 가 같은 입력에서 두 백엔드의 확률이 일치함을 검증한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

CLASSES = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
           'Near-full', 'Random', 'Scratch', 'none']
MODEL_NAME = 'coatnet_0_rw_224.sw_in1k'
NUM_CLASSES = len(CLASSES)


def softmax(logits: np.ndarray) -> np.ndarray:
    """수치적으로 안정한 softmax (최댓값을 빼고 지수화)."""
    shifted = logits.astype(np.float32) - logits.max()
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum()


def load_checkpoint(path) -> tuple[dict, dict]:
    """학습 체크포인트에서 가중치와 메타데이터를 꺼낸다.

    학습 코드가 `{'epoch', 'model_state_dict', 'val_acc'}` 형태로 저장하므로
    맨 state_dict 가 아니다. 형식이 다르면 임의 가중치로 추론하지 않고 중단한다.
    """
    import torch

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'모델 체크포인트가 없습니다: {path}')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if not isinstance(checkpoint, dict) or 'model_state_dict' not in checkpoint:
        raise ValueError('체크포인트에 model_state_dict 가 있어야 합니다')
    metadata = {key: checkpoint.get(key) for key in ('epoch', 'val_acc')}
    return checkpoint['model_state_dict'], metadata


def build_torch_model(state_dict: dict, device: str = 'cpu'):
    """timm 으로 구조를 만들고 가중치를 strict 로 올린다."""
    import timm

    model = timm.create_model(MODEL_NAME, pretrained=False, num_classes=NUM_CLASSES)
    model.load_state_dict(state_dict, strict=True)
    model.to(device).eval()
    return model


class PredictorBackend(ABC):
    """(1, 3, 224, 224) float32 배열 → 클래스 확률 (9,)."""

    name: str

    @abstractmethod
    def probabilities(self, model_input: np.ndarray) -> np.ndarray:
        ...


class TorchBackend(PredictorBackend):
    name = 'torch'

    def __init__(self, checkpoint, device: str = 'cpu'):
        state_dict, self.metadata = load_checkpoint(checkpoint)
        self.model = build_torch_model(state_dict, device)
        self.device = device
        self.source_path = Path(checkpoint)

    def probabilities(self, model_input: np.ndarray) -> np.ndarray:
        import torch

        with torch.inference_mode():
            logits = self.model(torch.from_numpy(model_input).to(self.device))
            return logits.softmax(dim=1)[0].cpu().numpy()


class OnnxBackend(PredictorBackend):
    name = 'onnx'

    def __init__(self, onnx_path, intra_op_threads: int | None = None):
        import onnxruntime as ort

        onnx_path = Path(onnx_path)
        if not onnx_path.is_file():
            raise FileNotFoundError(f'ONNX 모델이 없습니다: {onnx_path} '
                                    f'(python3 -m scripts.export_onnx 로 생성하세요)')
        options = ort.SessionOptions()
        if intra_op_threads:
            options.intra_op_num_threads = intra_op_threads
        self.session = ort.InferenceSession(str(onnx_path), options,
                                            providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.metadata = _read_onnx_metadata(onnx_path)
        self.source_path = onnx_path

    def probabilities(self, model_input: np.ndarray) -> np.ndarray:
        logits = self.session.run(None, {self.input_name: model_input.astype(np.float32)})[0]
        return softmax(logits[0])


def _read_onnx_metadata(onnx_path: Path) -> dict:
    """익스포트 때 심어둔 epoch / val_acc 를 읽는다."""
    import onnxruntime as ort

    raw = ort.InferenceSession(str(onnx_path),
                               providers=['CPUExecutionProvider']).get_modelmeta()
    custom = raw.custom_metadata_map or {}
    epoch = custom.get('epoch')
    val_acc = custom.get('val_acc')
    return {
        'epoch': int(epoch) if epoch is not None else None,
        'val_acc': float(val_acc) if val_acc is not None else None,
    }


def build_backend(checkpoint=None, onnx_path=None, prefer: str = 'auto',
                  device: str = 'cpu') -> PredictorBackend:
    """백엔드를 고른다.

    prefer='auto' 면 ONNX 파일이 있을 때 ONNX, 없으면 PyTorch 로 떨어진다.
    아직 익스포트하지 않은 환경에서도 서버가 뜨게 하기 위함이다.
    """
    if prefer not in ('auto', 'onnx', 'torch'):
        raise ValueError(f"prefer 는 auto/onnx/torch 중 하나여야 합니다 (현재 {prefer!r})")
    if prefer == 'onnx':
        return OnnxBackend(onnx_path)
    if prefer == 'torch':
        return TorchBackend(checkpoint, device)
    if onnx_path and Path(onnx_path).is_file():
        return OnnxBackend(onnx_path)
    return TorchBackend(checkpoint, device)
