"""새 모델 승격 — 고정 테스트 셋으로 재고, 기준을 넘을 때만 운영 모델을 교체한다.

    python3 -m scripts.promote_model --candidate runs/<시각>/model.pth            # 판정만
    python3 -m scripts.promote_model --candidate runs/<시각>/model.pth --apply    # 통과 시 교체

교체는 models/ 의 .pth 를 바꾸고 ONNX 를 다시 만드는 것이다. 이전 파일은 models/archive/ 에
남긴다. 서버에 반영하려면 models/ 를 서버로 옮기고 api 를 재시작한다 — 기동하면서 새 모델이
등록되고, 학습 중이던 재학습 작업이 자동으로 완료된다.

판정 기준

  * 후보는 지금 분할(split_id)로 학습된 것이어야 한다. 아니면 테스트 셋이 오염돼 잴 수 없다.
  * 기준 모델이 같은 분할로 학습됐으면 공정한 비교다. 후보가 기준보다 나쁘면(허용 오차 이상)
    거부한다. 균형(balanced)과 실제 분포(natural) 양쪽 macro-F1 을 본다.
  * 기준 모델이 1학기 모델이면 비교가 공정하지 않다. 그 모델은 이 테스트 셋의 샘플을 학습에
    썼기 때문에 점수가 부풀려져 있다. 그래서 비교 수치는 참고로만 보여주고, 후보가 절대 하한을
    넘는지만 본다.

기록에 남기는 것은 이 스크립트가 직접 잰 값이다. 체크포인트에 적힌 값을 그대로 믿지 않는다.
"""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scripts.training_common import DEFAULT_DATA, evaluate_test, load_training_set, pick_device

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_NAME = 'best_coatnet_model_optimized.pth'
ONNX_NAME = 'coatnet_wafer.onnx'
DEFAULT_FLOOR = 0.85          # 기준 모델이 오염됐을 때 후보에게 요구하는 균형 macro-F1 하한
DEFAULT_TOLERANCE = 0.005     # 공정한 비교에서 허용하는 하락폭


@dataclass
class Verdict:
    passed: bool
    fair_comparison: bool
    reasons: list[str] = field(default_factory=list)


def decide(candidate: dict, current: dict | None, candidate_split: str | None,
           current_split: str | None, split_id: str, floor: float = DEFAULT_FLOOR,
           tolerance: float = DEFAULT_TOLERANCE) -> Verdict:
    """승격 여부. candidate/current 는 evaluate_test 결과."""
    if candidate_split != split_id:
        return Verdict(False, False, [
            f'후보가 다른 분할({candidate_split or "기록 없음"})로 학습됐습니다. '
            f'지금 테스트 셋({split_id})으로 공정하게 잴 수 없습니다'])

    fair = current is not None and current_split == split_id
    reasons = []
    if fair:
        for view in ('balanced', 'natural'):
            new, old = candidate[view]['macro_f1'], current[view]['macro_f1']
            if new < old - tolerance:
                reasons.append(f'{view} macro-F1 이 {old:.4f} → {new:.4f} 로 떨어졌습니다')
    else:
        score = candidate['balanced']['macro_f1']
        if score < floor:
            reasons.append(f'balanced macro-F1 {score:.4f} 가 하한 {floor:.2f} 미만입니다')
    return Verdict(not reasons, fair, reasons)


def evaluate_checkpoint(path: Path, dataset, device: str, limit, batch_size: int):
    from waferai.backends import TorchBackend

    backend = TorchBackend(path, device)
    result = evaluate_test(backend.model, dataset, device, limit=limit, batch_size=batch_size)
    split = backend.metadata.get('split_id')
    del backend
    return result, split


def apply(candidate: Path, models_dir: Path, report: dict) -> Path:
    """이전 파일을 보관하고 후보를 운영 위치에 놓은 뒤 ONNX 를 다시 만든다."""
    from scripts.export_onnx import export

    archive = models_dir / 'archive' / datetime.now().strftime('%Y%m%d-%H%M%S')
    archive.mkdir(parents=True, exist_ok=True)
    for name in (CHECKPOINT_NAME, ONNX_NAME):
        if (models_dir / name).is_file():
            shutil.move(str(models_dir / name), archive / name)

    shutil.copy2(candidate, models_dir / CHECKPOINT_NAME)
    # .pth 만 바꾸고 ONNX 를 그대로 두면 서버가 옛 모델을 낸다. 반드시 다시 만든다.
    export(str(models_dir / CHECKPOINT_NAME), str(models_dir / ONNX_NAME))
    (archive / 'PROMOTION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return archive


def print_table(candidate: dict, current: dict | None, fair: bool) -> None:
    label = '현재 모델' if fair else '현재 모델 (오염 · 참고용)'
    print(f'\n  {"":24s}{"후보":>18s}{label:>28s}')
    for view in ('balanced', 'natural'):
        for metric in ('accuracy', 'macro_f1'):
            new = candidate[view][metric]
            old = f'{current[view][metric]:.4f}' if current else '-'
            print(f'  {view + " " + metric:24s}{new:>18.4f}{old:>24s}')
    print(f'  {"표본 수 (balanced/natural)":24s}'
          f'{candidate["balanced"]["n"]:>9,d}/{candidate["natural"]["n"]:<8,d}')


def main() -> None:
    parser = argparse.ArgumentParser(description='새 모델 승격 판정·적용')
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--current', default=str(ROOT / 'models' / CHECKPOINT_NAME))
    parser.add_argument('--models-dir', default=str(ROOT / 'models'))
    parser.add_argument('--data', default=DEFAULT_DATA)
    parser.add_argument('--floor', type=float, default=DEFAULT_FLOOR)
    parser.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--limit', type=int, help='테스트 표본 상한 (동작 확인용, 판정에는 쓰지 말 것)')
    parser.add_argument('--apply', action='store_true', help='통과하면 운영 모델을 교체한다')
    parser.add_argument('--force', action='store_true', help='판정과 무관하게 교체한다')
    args = parser.parse_args()

    import os
    os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
    os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
    device = pick_device(args.device)

    dataset = load_training_set(args.data)
    print(f'[테스트 셋] split_id {dataset.split_id} · {len(dataset.indices("test")):,}개 · 장치 {device}')
    if args.limit:
        print(f'  ⚠️ --limit {args.limit}: 동작 확인용입니다. 판정 결과를 믿지 마세요')

    print('[후보] 평가 중 ...', flush=True)
    candidate, candidate_split = evaluate_checkpoint(Path(args.candidate), dataset, device,
                                                     args.limit, args.batch_size)
    current = current_split = None
    if Path(args.current).is_file():
        print('[현재 모델] 평가 중 ...', flush=True)
        current, current_split = evaluate_checkpoint(Path(args.current), dataset, device,
                                                     args.limit, args.batch_size)

    verdict = decide(candidate, current, candidate_split, current_split, dataset.split_id,
                     args.floor, args.tolerance)
    print_table(candidate, current, verdict.fair_comparison)
    if current is not None and not verdict.fair_comparison:
        print('\n  현재 모델은 이 테스트 셋의 샘플을 학습에 썼습니다(1학기 모델). 그래서 위 숫자는\n'
              '  부풀려져 있고 비교 기준으로 쓰지 않습니다. 후보가 하한을 넘는지만 봅니다.')

    print(f'\n판정: {"통과" if verdict.passed else "거부"}')
    for reason in verdict.reasons:
        print(f'  - {reason}')

    report = {'decided_at': datetime.now(timezone.utc).isoformat(), 'split_id': dataset.split_id,
              'candidate': str(args.candidate), 'candidate_test': candidate,
              'current_test': current, 'fair_comparison': verdict.fair_comparison,
              'passed': verdict.passed, 'reasons': verdict.reasons, 'forced': args.force,
              'limited': args.limit}

    if not args.apply:
        print('\n판정만 했습니다. 교체하려면 --apply 를 붙이세요.')
        raise SystemExit(0 if verdict.passed else 1)
    if not verdict.passed and not args.force:
        print('\n교체하지 않았습니다. 관리 화면에서 재학습 작업을 실패로 표시하고 사유를 남기세요.')
        raise SystemExit(1)
    if args.limit and not args.force:
        raise SystemExit('--limit 로 잰 결과로는 교체하지 않습니다.')

    archive = apply(Path(args.candidate), Path(args.models_dir), report)
    print(f'\n교체 완료. 이전 파일과 판정 기록: {archive}')
    print('다음: models/ 를 서버로 옮기고  docker compose restart api')
    print('      → 기동하며 새 모델이 등록되고 학습 중이던 재학습 작업이 완료됩니다.')


if __name__ == '__main__':
    main()
