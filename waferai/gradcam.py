"""Grad-CAM — AI 가 어디를 보고 판단했는지 보여준다.

`pytorch-grad-cam` 라이브러리 대신 직접 구현했다. 이유는 셋이다.

  1. CoAtNet 의 마지막 스테이지 출력이 (1, 768, 7, 7) 4D NCHW 로 실측됐다.
     라이브러리가 필요한 지점인 어텐션 토큰 → 공간 해상도 변환(reshape_transform)이
     이 모델에는 아예 필요 없다. 기능상세설명서 §3.3.3 의 reshape_transform_coatnet()
     언급은 불필요한 내용이다.
  2. 남는 계산은 30줄 남짓이라, 배포 이미지에 의존성을 더할 이유가 없다.
  3. 직접 구현하면 수치를 테스트로 고정할 수 있다.

ONNX Runtime 은 순전파만 하므로 여기서는 쓸 수 없다. Grad-CAM 은 예측 점수를 마지막
특징맵으로 미분한 값을 가중치로 쓰기 때문에 역전파가 반드시 필요하다.
"""
from __future__ import annotations

import cv2
import numpy as np

CAM_SIZE = (224, 224)
DEFAULT_ALPHA = 0.5


class GradCAM:
    """대상 레이어의 활성값과 기울기로 클래스 활성 맵을 만든다.

    훅을 걸어두므로 다 쓰면 `release()` 를 부르거나 `with` 로 감싼다.
    """

    def __init__(self, model, target_layer):
        self.model = model
        self.target_layer = target_layer
        self._activations = None
        self._gradients = None
        self._handles = [
            target_layer.register_forward_hook(self._save_activation),
            target_layer.register_full_backward_hook(self._save_gradient),
        ]

    def _save_activation(self, _module, _inputs, output):
        self._activations = output

    def _save_gradient(self, _module, _grad_input, grad_output):
        self._gradients = grad_output[0]

    def __call__(self, model_input: np.ndarray, class_index: int | None = None
                 ) -> tuple[np.ndarray, int]:
        """(224x224 float32 [0,1] CAM, 사용한 클래스 인덱스)."""
        import torch

        self.model.zero_grad(set_to_none=True)
        # 모델 파라미터가 requires_grad=False 여도 그래프가 만들어지도록 입력에 건다.
        tensor = torch.from_numpy(model_input).clone().requires_grad_(True)

        with torch.enable_grad():
            logits = self.model(tensor)
            if class_index is None:
                class_index = int(logits.argmax(dim=1).item())
            logits[0, class_index].backward()

        if self._activations is None or self._gradients is None:
            raise RuntimeError('대상 레이어에서 활성값이나 기울기를 얻지 못했습니다')

        activations = self._activations[0].detach()      # (C, H, W)
        gradients = self._gradients[0].detach()          # (C, H, W)
        if activations.ndim != 3:
            raise RuntimeError(
                f'대상 레이어 출력이 (C, H, W) 가 아닙니다: {tuple(activations.shape)}')

        # 채널별 기울기를 공간 평균해 가중치로 삼고, 양의 기여만 남긴다.
        weights = gradients.mean(dim=(1, 2))
        cam = torch.relu((weights[:, None, None] * activations).sum(dim=0))

        cam_array = cam.cpu().numpy().astype(np.float32)
        peak = float(cam_array.max())
        if peak > 0:
            cam_array /= peak
        # 7x7 → 224x224. 여기는 라벨이 아니라 연속값이라 선형 보간이 맞다.
        resized = cv2.resize(cam_array, CAM_SIZE, interpolation=cv2.INTER_LINEAR)
        return np.clip(resized, 0.0, 1.0), class_index

    def release(self) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles = []
        self._activations = self._gradients = None

    def __enter__(self) -> 'GradCAM':
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def find_target_layer(model):
    """CoAtNet 의 마지막 스테이지. 실측상 (1, 768, 7, 7) 을 낸다."""
    stages = getattr(model, 'stages', None)
    if stages is None or not len(stages):
        raise AttributeError('모델에 stages 가 없습니다. Grad-CAM 대상 레이어를 찾을 수 없습니다')
    return stages[-1]


def overlay_heatmap(cam: np.ndarray, background_rgb: np.ndarray,
                    alpha: float = DEFAULT_ALPHA) -> np.ndarray:
    """CAM 을 원본 위에 겹친 RGB 이미지.

    배경은 모델이 실제로 본 그림(`preprocess.to_rgb`)을 써야 한다. 다른 렌더링을
    깔면 히트맵 위치가 미묘하게 어긋나 설명이 틀어진다.
    """
    if background_rgb.shape[:2] != cam.shape[:2]:
        raise ValueError(f'크기가 다릅니다: CAM {cam.shape[:2]}, 배경 {background_rgb.shape[:2]}')

    # applyColorMap 은 BGR 을 내므로 RGB 로 되돌린다.
    colored = cv2.applyColorMap((cam * 255).astype(np.uint8), cv2.COLORMAP_JET)
    colored = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB).astype(np.float32)
    blended = alpha * colored + (1.0 - alpha) * background_rgb.astype(np.float32)
    return np.clip(blended, 0, 255).astype(np.uint8)
