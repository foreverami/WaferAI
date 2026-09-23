"""학습 체크포인트(.pth) → ONNX 모델.

    python3 -m scripts.export_onnx

익스포트 직후 같은 입력으로 PyTorch 와 ONNX Runtime 의 확률을 비교해, 어긋나면
파일을 남기지 않고 실패한다. 조용히 다른 답을 내는 모델을 배포하는 것이 최악이다.
epoch / val_acc 는 ONNX 메타데이터에 심어 어느 체크포인트에서 나왔는지 추적한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from waferai.backends import (CLASSES, TorchBackend, load_checkpoint, build_torch_model,
                              softmax)
from waferai.preprocess import to_model_input

DEFAULT_CHECKPOINT = 'models/best_coatnet_model_optimized.pth'
DEFAULT_OUTPUT = 'models/coatnet_wafer.onnx'
OPSET = 17
PARITY_TOLERANCE = 1e-4


def sample_inputs(count: int = 6) -> list[np.ndarray]:
    """검증용 입력. 크기와 결함 분포를 섞어 경계 경로까지 지나게 한다."""
    rng = np.random.default_rng(0)
    shapes = [(45, 48), (53, 53), (26, 30), (64, 64), (33, 41), (48, 45)]
    return [to_model_input(rng.integers(0, 3, shapes[i % len(shapes)]).astype(np.uint8))
            for i in range(count)]


def export(checkpoint: str, output: str) -> Path:
    import torch

    state_dict, metadata = load_checkpoint(checkpoint)
    model = build_torch_model(state_dict, 'cpu')

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    example = torch.from_numpy(to_model_input(np.zeros((45, 48), dtype=np.uint8)))

    print(f'[1/3] ONNX 익스포트 중 (opset {OPSET}) ...')
    # dynamo=False (레거시 익스포터)를 의도적으로 쓴다. PyTorch 2.9+ 의 기본값인
    # dynamo=True 는 (1) 가중치를 .onnx.data 로 분리해 파일이 둘로 갈라지고
    # — 서버가 모델 파일 하나를 SHA-256 으로 버전 관리하는 구조와 맞지 않는다 —
    # (2) external_data=False 로 단일 파일을 만들어도 실측이 더 느렸다(35.2ms vs 31.2ms).
    # CoAtNet 에는 새 익스포터가 필요한 제어 흐름이 없으므로 레거시로 충분하다.
    torch.onnx.export(
        model, (example,), str(output_path),
        input_names=['input'], output_names=['logits'],
        dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
        opset_version=OPSET, dynamo=False,
    )

    print('[2/3] 체크포인트 메타데이터 심는 중 ...')
    import onnx

    proto = onnx.load(str(output_path))
    proto.doc_string = f'WaferAI CoAtNet-0 · {len(CLASSES)} classes'
    for key, value in metadata.items():
        if value is not None:
            entry = proto.metadata_props.add()
            entry.key, entry.value = key, str(value)
    entry = proto.metadata_props.add()
    entry.key, entry.value = 'classes', ','.join(CLASSES)
    onnx.save(proto, str(output_path))

    print('[3/3] PyTorch ↔ ONNX 동등성 검증 중 ...')
    verify(checkpoint, output_path)

    size_mb = output_path.stat().st_size / 1024 ** 2
    print(f'\n완료: {output_path} ({size_mb:.1f} MB)')
    print(f'  epoch={metadata.get("epoch")}  val_acc={metadata.get("val_acc")}')
    return output_path


def verify(checkpoint: str, onnx_path: Path) -> float:
    """두 백엔드의 확률 최대 오차를 재고, 허용치를 넘으면 파일을 지우고 실패시킨다."""
    import onnxruntime as ort

    torch_backend = TorchBackend(checkpoint)
    session = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name

    worst = 0.0
    for model_input in sample_inputs():
        expected = torch_backend.probabilities(model_input)
        actual = softmax(session.run(None, {input_name: model_input})[0][0])
        worst = max(worst, float(np.abs(expected - actual).max()))
        if expected.argmax() != actual.argmax():
            onnx_path.unlink(missing_ok=True)
            raise SystemExit('검증 실패: 두 백엔드의 예측 클래스가 다릅니다. ONNX 파일을 삭제했습니다')

    if worst > PARITY_TOLERANCE:
        onnx_path.unlink(missing_ok=True)
        raise SystemExit(f'검증 실패: 확률 최대 오차 {worst:.2e} > 허용치 {PARITY_TOLERANCE:.0e}. '
                         'ONNX 파일을 삭제했습니다')
    print(f'      확률 최대 오차 {worst:.2e} (허용치 {PARITY_TOLERANCE:.0e}) — 통과')
    return worst


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI CoAtNet-0 ONNX 익스포트')
    parser.add_argument('--checkpoint', default=DEFAULT_CHECKPOINT)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    export(**vars(parser.parse_args()))


if __name__ == '__main__':
    main()
