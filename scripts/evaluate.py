"""실제 WM-811K 데이터로 모델과 서빙 경로를 측정한다.

    python3 -m scripts.prepare_eval_set --source ~/Downloads/LSWMD.pkl   # 먼저 한 번
    python3 -m scripts.evaluate

재는 것:
  1. 검증 분할 정확도 — 학습이 기록한 val_acc 96.45% 가 재현되는지.
     재현되면 서빙 전처리가 학습과 같다는 강한 증거가 된다.
  2. 클래스별 정밀도/재현율/F1 과 혼동행렬 — 표본이 적은 클래스가 어디서 무너지는지.
  3. 실제 분포 성능 — 'none' 이 압도적인 운영 환경에서의 정확도.
     학습·검증은 'none' 을 언더샘플링한 균형 데이터였으므로 수치가 다르다.
  4. 판정 경로 분포 — 자동 통과/규칙 확정/검토 대기가 각각 몇 %인지.
     엔지니어 업무량을 좌우하므로 임계값 조정의 근거가 된다.
  5. 이미지 경로 영향 — 렌더링 이미지를 거쳤을 때 예측이 바뀌는 비율.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from waferai.decision import Thresholds, decide
from waferai.preprocess import defect_ratio, to_model_input

BATCH_SIZE = 32


def unpack(flat: np.ndarray, shapes: np.ndarray) -> list[np.ndarray]:
    maps, offset = [], 0
    for height, width in shapes:
        size = int(height) * int(width)
        maps.append(flat[offset:offset + size].reshape(int(height), int(width)))
        offset += size
    return maps


def batched_probabilities(backend, maps: list[np.ndarray], label: str) -> np.ndarray:
    """(N, 9) 확률. 한 장씩 부르면 느려서 배치로 묶는다."""
    import torch

    outputs = []
    for start in range(0, len(maps), BATCH_SIZE):
        chunk = maps[start:start + BATCH_SIZE]
        batch = np.concatenate([to_model_input(m) for m in chunk], axis=0)
        if backend.name == 'torch':
            with torch.inference_mode():
                tensor = torch.from_numpy(batch).to(backend.device)
                probs = backend.model(tensor).softmax(dim=1).float().cpu().numpy()
        else:
            logits = backend.session.run(None, {backend.input_name: batch})[0]
            shifted = logits - logits.max(axis=1, keepdims=True)
            exponentiated = np.exp(shifted)
            probs = exponentiated / exponentiated.sum(axis=1, keepdims=True)
        outputs.append(probs)
        done = min(start + BATCH_SIZE, len(maps))
        print(f'\r      {label}: {done:,}/{len(maps):,}', end='', flush=True)
    print()
    return np.concatenate(outputs, axis=0)


def print_per_class(true: np.ndarray, predicted: np.ndarray, classes: list[str]) -> None:
    from sklearn.metrics import classification_report

    print(classification_report(true, predicted, labels=range(len(classes)),
                                target_names=classes, digits=3, zero_division=0))


def print_confusion(true: np.ndarray, predicted: np.ndarray, classes: list[str]) -> None:
    from sklearn.metrics import confusion_matrix

    matrix = confusion_matrix(true, predicted, labels=range(len(classes)))
    width = max(len(name) for name in classes)
    print(' ' * (width + 2) + ''.join(f'{name[:6]:>7s}' for name in classes) + '     합계')
    for index, name in enumerate(classes):
        row = matrix[index]
        cells = ''.join(f'{value:7d}' for value in row)
        print(f'{name:>{width}s}  {cells}  {row.sum():7d}')
    print('  (행 = 실제, 열 = 예측)')


def evaluate_decisions(probabilities: np.ndarray, maps: list[np.ndarray],
                       classes: list[str], thresholds: Thresholds) -> list[dict]:
    return [decide({name: float(p) for name, p in zip(classes, probs)},
                   defect_ratio(wafer_map), thresholds)
            for probs, wafer_map in zip(probabilities, maps)]


def print_decision_quality(decisions: list[dict], truth: np.ndarray,
                           classes: list[str]) -> None:
    """경로별 최종 판정 정확도.

    자동 통과와 규칙 확정은 사람이 보지 않고 나가므로, 여기서 틀리면 그대로 불량이
    흘러간다. 특히 RULE_BASE_NONE 이 실제 결함을 none 으로 덮는 경우가 가장 위험하다.
    """
    index_of = {name: i for i, name in enumerate(classes)}
    final = np.array([index_of[d['final_class']] for d in decisions])
    paths = np.array([d['decision_path'] for d in decisions])
    correct = final == truth

    print(f"      {'경로':<22s} {'건수':>8s} {'비율':>8s} {'최종판정 정확도':>16s}")
    for path in ('AUTO_PASS', 'RULE_BASE_NONE', 'RULE_BASE_NEAR_FULL', 'REVIEW_NEEDED'):
        mask = paths == path
        if not mask.any():
            continue
        accuracy = float(correct[mask].mean())
        print(f'      {path:<22s} {int(mask.sum()):8,d} {mask.mean():7.2%} {accuracy:15.2%}')

    unattended = paths != 'REVIEW_NEEDED'
    print(f'\n      사람이 보지 않고 나가는 건: {unattended.mean():.2%} '
          f'(정확도 {float(correct[unattended].mean()):.2%})')
    escaped = int((~correct & unattended).sum())
    print(f'      그중 잘못 나간 건: {escaped:,}건 / 전체 {len(decisions):,}건 '
          f'= {escaped / len(decisions):.2%}')

    # 규칙이 결함을 none 으로 덮은 경우 — 가장 위험한 실패 방식
    forced_none = (paths == 'RULE_BASE_NONE') & ~correct
    if forced_none.any():
        missed = Counter(classes[i] for i in truth[forced_none])
        print(f'\n      ⚠️ 밀도 규칙이 none 으로 덮은 실제 결함 {int(forced_none.sum()):,}건: '
              + ', '.join(f'{name} {count}건' for name, count in missed.most_common()))

    review_mask = paths == 'REVIEW_NEEDED'
    if review_mask.any():
        print(f'\n      검토 대기 건에서 AI 1순위가 맞았을 비율: '
              f'{float(correct[review_mask].mean()):.2%}'
              ' (낮을수록 사람이 볼 값어치가 크다)')


def measure_image_path(backend, maps: list[np.ndarray], truth: np.ndarray,
                       classes: list[str], count: int) -> None:
    """렌더링 이미지를 거쳤을 때 예측이 얼마나 바뀌는지."""
    from waferai.image_adapter import encode_png, image_to_wafer_map, render_wafer_map

    sample = maps[:count]
    restored, kept = [], []
    for index, wafer_map in enumerate(sample):
        try:
            back, _ = image_to_wafer_map(encode_png(render_wafer_map(wafer_map, 224)))
            restored.append(back)
            kept.append(index)
        except Exception as error:                       # 복원 실패도 결과의 일부다
            print(f'      [복원 실패] {index}: {error}')
    if not restored:
        return

    direct = batched_probabilities(backend, [sample[i] for i in kept], '배열 경로').argmax(axis=1)
    through = batched_probabilities(backend, restored, '이미지 경로').argmax(axis=1)
    labels = truth[kept]

    agreement = float((direct == through).mean())
    print(f'\n      두 경로 예측 일치 : {agreement:.2%}  ({int((direct == through).sum()):,}/{len(kept):,})')
    print(f'      배열 경로 정확도  : {float((direct == labels).mean()):.2%}')
    print(f'      이미지 경로 정확도: {float((through == labels).mean()):.2%}')
    if agreement < 1.0:
        changed = np.flatnonzero(direct != through)[:5]
        print('      바뀐 예: ' + ', '.join(
            f'{classes[direct[i]]}→{classes[through[i]]}' for i in changed))


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 실데이터 평가')
    parser.add_argument('--data', default='data/eval_set.npz')
    parser.add_argument('--checkpoint', default='models/best_coatnet_model_optimized.pth')
    parser.add_argument('--onnx', default='models/coatnet_wafer.onnx')
    parser.add_argument('--backend', default='torch', choices=['auto', 'onnx', 'torch'])
    parser.add_argument('--device', default='cpu', choices=['cpu', 'mps', 'cuda'],
                        help='평가 전용 가속기. 서빙은 CPU 이지만 측정은 GPU 로 해도 된다 '
                             '(MPS 는 CPU 와 확률 오차 3e-07 로 동일함을 확인했다)')
    parser.add_argument('--limit', type=int, help='검증 표본 수 상한 (빠른 확인용)')
    parser.add_argument('--image-check', type=int, default=300,
                        help='이미지 경로 비교에 쓸 표본 수 (0 이면 생략)')
    parser.add_argument('--skip-holdout', action='store_true',
                        help='실제 분포 측정(20,000건)을 건너뛴다')
    parser.add_argument('--cache', default='data/val_probs.npz',
                        help='검증 확률 캐시. 있으면 재사용해 추론을 건너뛴다')
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        raise SystemExit(f'평가 데이터가 없습니다: {data_path}\n'
                         '  python3 -m scripts.prepare_eval_set --source ~/Downloads/LSWMD.pkl')

    from waferai.backends import build_backend

    data = np.load(data_path, allow_pickle=False)
    classes = [str(name) for name in data['class_names']]
    val_maps = unpack(data['val_flat'], data['val_shapes'])
    val_labels = data['val_labels'].astype(int)
    if args.limit:
        val_maps, val_labels = val_maps[:args.limit], val_labels[:args.limit]

    backend = build_backend(args.checkpoint, args.onnx, args.backend, args.device)
    thresholds = Thresholds()
    device = getattr(backend, 'device', 'cpu')
    print(f'백엔드: {backend.name} ({device})    검증 표본: {len(val_maps):,}개\n')

    print('[1] 검증 분할 정확도 — 학습 기록 재현 확인')
    cache = Path(args.cache) if args.cache else None
    # 캐시는 표본 수와 백엔드가 같을 때만 쓴다. 다르면 다시 추론한다.
    if cache and cache.is_file():
        stored = np.load(cache, allow_pickle=False)
        if stored['probabilities'].shape[0] == len(val_maps) and \
                str(stored['backend']) == f'{backend.name}:{device}':
            val_probs = stored['probabilities']
            print(f'      캐시 재사용: {cache}')
        else:
            val_probs = batched_probabilities(backend, val_maps, '추론 중')
    else:
        val_probs = batched_probabilities(backend, val_maps, '추론 중')
    if cache and not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, probabilities=val_probs,
                            backend=f'{backend.name}:{device}')
    val_pred = val_probs.argmax(axis=1)
    accuracy = float((val_pred == val_labels).mean())
    recorded = getattr(backend, 'metadata', {}).get('val_acc')
    print(f'\n      측정 정확도: {accuracy:.4%}')
    if recorded:
        gap = abs(accuracy * 100 - recorded)
        verdict = '재현됨' if gap < 0.5 else '불일치 — 전처리를 의심해야 함'
        print(f'      학습 기록  : {recorded:.4f}%   차이 {gap:.4f}%p → {verdict}')

    print('\n[2] 클래스별 성능')
    print_per_class(val_labels, val_pred, classes)
    print('[3] 혼동행렬')
    print_confusion(val_labels, val_pred, classes)

    print('\n[4] 판정 경로별 분포와 최종 정확도 (검증 분할 기준)')
    decisions = evaluate_decisions(val_probs, val_maps, classes, thresholds)
    print_decision_quality(decisions, val_labels, classes)

    if data['holdout_labels'].size and not args.skip_holdout:
        print('\n[5] 실제 분포 성능 — 미사용 none 을 더한 경우')
        holdout_maps = unpack(data['holdout_flat'], data['holdout_shapes'])
        holdout_labels = data['holdout_labels'].astype(int)
        if args.limit:
            holdout_maps = holdout_maps[:args.limit]
            holdout_labels = holdout_labels[:len(holdout_maps)]
        holdout_pred = batched_probabilities(backend, holdout_maps, '추론 중').argmax(axis=1)
        holdout_accuracy = float((holdout_pred == holdout_labels).mean())
        print(f"\n      미사용 'none' {len(holdout_maps):,}개 정확도: {holdout_accuracy:.2%}")
        combined_correct = int((val_pred == val_labels).sum()) + int(
            (holdout_pred == holdout_labels).sum())
        combined_total = len(val_maps) + len(holdout_maps)
        print(f'      합산 정확도 ({combined_total:,}개): {combined_correct / combined_total:.2%}')
        wrong = holdout_pred[holdout_pred != holdout_labels]
        if wrong.size:
            print('      정상을 결함으로 본 상위: ' + ', '.join(
                f'{classes[value]} {count}건' for value, count in Counter(wrong).most_common(3)))

    if args.image_check:
        print(f'\n[6] 이미지 경로 영향 (표본 {args.image_check:,}개)')
        measure_image_path(backend, val_maps, val_labels, classes, args.image_check)


if __name__ == '__main__':
    main()
