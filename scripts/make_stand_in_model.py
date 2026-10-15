"""CI 용 대역 모델 — 학습된 가중치 대신 같은 구조의 무작위 가중치로 .pth 와 .onnx 를 만든다.

    python3 -m scripts.make_stand_in_model                      # models/ 에 만든다
    python3 -m scripts.make_stand_in_model --output-dir /tmp/m   # 다른 곳에

가중치(약 107MB)는 저장소에 넣지 않으므로 GitHub Actions 에는 모델이 없다. 모델이 없으면 앱이
뜨지 않아 API · 인증 · DB 테스트가 전부 건너뛰어지고, CI 가 초록불이어도 핵심 경로를 검사하지
않은 셈이 된다. 구조가 같은 대역 모델이면 전처리 → 추론 → 판정 → 저장 경로가 그대로 돈다.

예측 값은 의미가 없다. 학습된 모델이어야 뜻이 있는 테스트(Grad-CAM 이 결함 위치를 가리키는지
등)는 WAFERAI_STAND_IN_MODEL=1 일 때 건너뛴다 (tests/conftest.py 의 TRAINED_MODEL).

이미 파일이 있으면 만들지 않는다. 실수로 운영 모델을 덮어쓰지 않기 위해서다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_NAME = 'best_coatnet_model_optimized.pth'
ONNX_NAME = 'coatnet_wafer.onnx'


def make(output_dir: Path, seed: int = 0) -> tuple[Path, Path]:
    import timm
    import torch

    from scripts.export_onnx import export
    from waferai.backends import MODEL_NAME, NUM_CLASSES

    checkpoint, onnx_path = output_dir / CHECKPOINT_NAME, output_dir / ONNX_NAME
    existing = [path for path in (checkpoint, onnx_path) if path.exists()]
    if existing:
        raise SystemExit(f'이미 있습니다: {", ".join(map(str, existing))}\n'
                         '  운영 모델을 덮어쓰지 않도록 대역 모델은 빈 자리에만 만듭니다.')

    torch.manual_seed(seed)
    model = timm.create_model(MODEL_NAME, pretrained=False, num_classes=NUM_CLASSES)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 학습 메타데이터(epoch, val_acc, split_id, test_metrics)는 일부러 비운다.
    # 서버는 이것을 1학기 모델처럼 '테스트 성적 없는 모델' 로 다룬다.
    torch.save({'model_state_dict': model.state_dict()}, checkpoint)
    export(str(checkpoint), str(onnx_path))
    return checkpoint, onnx_path


def main() -> None:
    parser = argparse.ArgumentParser(description='CI 용 대역 모델 생성')
    parser.add_argument('--output-dir', default=str(ROOT / 'models'))
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    checkpoint, onnx_path = make(Path(args.output_dir), args.seed)
    print(f'\n대역 모델: {checkpoint}\n          {onnx_path}')
    print('테스트할 때 WAFERAI_STAND_IN_MODEL=1 을 주면 학습된 모델이 필요한 테스트를 건너뜁니다.')


if __name__ == '__main__':
    main()
