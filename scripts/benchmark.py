"""배포 서버에서 추론 백엔드를 실측한다.

    python3 -m scripts.benchmark

어느 백엔드가 빠른지는 CPU 아키텍처에 따라 뒤집힌다. 개발 장비(Apple Silicon arm64)
에서는 PyTorch 가 ONNX Runtime 보다 빨랐지만, 배포 대상인 x86 리눅스에서는 ORT 가
AVX 계열 커널로 앞서는 경우가 많다. 서버를 정한 뒤 여기서 재고 `--backend` 를 고른다.
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np

from waferai.inference import DEFAULT_CHECKPOINT, DEFAULT_ONNX
from waferai.preprocess import to_model_input

WARMUP = 5
REPEATS = 30


def sample_input() -> np.ndarray:
    return to_model_input(np.random.default_rng(0).integers(0, 3, (45, 48)).astype(np.uint8))


def measure(run, model_input) -> tuple[float, float]:
    """(중앙값 ms, p95 ms). 평균은 이상치에 휘둘리므로 쓰지 않는다."""
    for _ in range(WARMUP):
        run(model_input)
    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        run(model_input)
        samples.append((time.perf_counter() - start) * 1000)
    return float(np.median(samples)), float(np.percentile(samples, 95))


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 추론 백엔드 벤치마크')
    parser.add_argument('--checkpoint', default=DEFAULT_CHECKPOINT)
    parser.add_argument('--onnx', default=DEFAULT_ONNX)
    args = parser.parse_args()

    model_input = sample_input()
    print(f'CPU 논리 코어: {os.cpu_count()}    입력: {model_input.shape}\n')
    results: dict[str, float] = {}

    from waferai.backends import TorchBackend

    torch_backend = TorchBackend(args.checkpoint)
    median, p95 = measure(torch_backend.probabilities, model_input)
    results['torch'] = median
    print(f'{"PyTorch":28s} 중앙값 {median:6.1f} ms   p95 {p95:6.1f} ms')

    if os.path.isfile(args.onnx):
        import onnxruntime as ort

        best = None
        for threads in (0, 1, 2, 4, 8):
            if threads > (os.cpu_count() or 1):
                continue
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            if threads:
                options.intra_op_num_threads = threads
            session = ort.InferenceSession(args.onnx, options,
                                           providers=['CPUExecutionProvider'])
            name = session.get_inputs()[0].name
            median, p95 = measure(lambda x: session.run(None, {name: x}), model_input)
            label = f'ONNX Runtime (intra_op={threads or "기본"})'
            print(f'{label:28s} 중앙값 {median:6.1f} ms   p95 {p95:6.1f} ms')
            if best is None or median < best[1]:
                best = (threads, median)
        results['onnx'] = best[1]
        print(f'\nONNX 최적 스레드 수: {best[0] or "기본"}')
    else:
        print(f'\nONNX 모델이 없어 건너뜁니다: {args.onnx}')
        print('  python3 -m scripts.export_onnx 로 먼저 생성하세요')

    if len(results) == 2:
        winner = min(results, key=results.get)
        gap = abs(results['torch'] - results['onnx']) / max(results.values())
        print(f'\n권장 백엔드: {winner}  (차이 {gap:.0%})')
        print('  create_app(backend=...) 또는 --backend 로 지정한다.')
        print('  Grad-CAM 은 어느 쪽을 고르든 PyTorch 를 지연 로딩해 쓴다.')


if __name__ == '__main__':
    main()
