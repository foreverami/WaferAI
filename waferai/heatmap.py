"""Grad-CAM 히트맵 생성·보관.

ERD 와 플로우차트가 지정한 지연 연산(Lazy Eval)을 따른다. 모든 웨이퍼의 히트맵을
미리 만들면 서버가 놀지 않는데, 실제로 열어보는 건 검토 대상 5% 남짓이다.

PyTorch 모델도 지연 로딩한다. `/predict` 는 ONNX 로 돌고 Grad-CAM 만 PyTorch 가
필요하므로, 아무도 히트맵을 열지 않으면 102MB 를 아예 올리지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock

import cv2
import numpy as np

from waferai.backends import CLASSES
from waferai.gradcam import GradCAM, find_target_layer, overlay_heatmap
from waferai.preprocess import to_model_input, to_rgb, validate_map


class HeatmapService:
    def __init__(self, checkpoint, output_dir, device: str = 'cpu'):
        self.checkpoint = Path(checkpoint)
        self.output_dir = Path(output_dir)
        self.device = device
        self._backend = None
        self._cam = None
        # 역전파는 훅에 상태를 남기므로 동시에 두 요청이 들어오면 섞인다.
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    def _ensure_loaded(self) -> None:
        """첫 히트맵 요청에서만 PyTorch 를 올린다."""
        if self._backend is not None:
            return
        from waferai.backends import TorchBackend

        self._backend = TorchBackend(self.checkpoint, self.device)
        self._cam = GradCAM(self._backend.model, find_target_layer(self._backend.model))

    def path_for(self, wafer_id: str, class_name: str) -> Path:
        safe_class = class_name.replace('/', '_')
        return self.output_dir / f'{wafer_id}__{safe_class}.png'

    def generate(self, wafer_id: str, wafer_map, class_name: str | None = None) -> Path:
        """히트맵 PNG 를 만들어 저장하고 경로를 돌려준다. 이미 있으면 그대로 쓴다."""
        wafer_map = validate_map(wafer_map)
        class_index = CLASSES.index(class_name) if class_name else None

        with self._lock:
            self._ensure_loaded()
            model_input = to_model_input(wafer_map)
            cam, used_index = self._cam(model_input, class_index)

        used_class = CLASSES[used_index]
        target = self.path_for(wafer_id, used_class)
        if target.is_file():
            return target

        # 배경은 모델이 실제로 본 그림이어야 히트맵 위치가 어긋나지 않는다.
        blended = overlay_heatmap(cam, to_rgb(wafer_map))
        target.parent.mkdir(parents=True, exist_ok=True)
        ok, buffer = cv2.imencode('.png', cv2.cvtColor(blended, cv2.COLOR_RGB2BGR))
        if not ok:
            raise RuntimeError('히트맵 PNG 인코딩에 실패했습니다')
        target.write_bytes(buffer.tobytes())
        return target

    def cached_path(self, wafer_id: str, class_name: str) -> Path | None:
        candidate = self.path_for(wafer_id, class_name)
        return candidate if candidate.is_file() else None

    def release(self) -> None:
        if self._cam is not None:
            self._cam.release()
        self._cam = self._backend = None


def top_class(probabilities: dict[str, float]) -> str:
    return max(probabilities.items(), key=lambda kv: kv[1])[0]
