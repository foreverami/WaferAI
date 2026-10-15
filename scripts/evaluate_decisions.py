"""운영 모델의 판정 로직 효과를 고정 테스트 셋에서 잰다 — 엔지니어 업무량과 새는 불량.

    python3 -m scripts.evaluate_decisions --device mps

재는 것 (실제 분포와 균형 표본 각각):
  1. 기본 설정의 판정 경로 분포와 경로별 정확도 — 사람이 보지 않고 나가는 비율과 그중 틀린 비율.
  2. 확신도 임계값별 검토 부담과 새는 불량의 맞교환 — 임계값을 고르는 근거.
  3. 저밀도 규칙을 켰을 때 — 1학기 모델에서 해로웠던 결과가 새 모델에서도 같은지.
  4. 이미지 경로 영향 — 렌더링 이미지를 거쳐도 예측이 같은지.

1학기 측정(scripts/evaluate.py)은 학습과 섞인 검증 분할에서 했다. 여기서는 학습에 쓰지 않은
테스트 셋을 쓴다. 확률은 모델 해시와 함께 data/test_probs.npz 에 캐시하고, 모델이 바뀌면
다시 계산한다.
"""
from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

import numpy as np

from scripts.evaluate import evaluate_decisions, measure_image_path
from scripts.training_common import (CLASS_NAMES, DEFAULT_DATA, NONE_INDEX, balanced,
                                     confidence_profile, load_training_set, pick_device,
                                     probabilities)
from waferai.decision import Thresholds

CHECKPOINT = 'models/best_coatnet_model_optimized.pth'
ONNX = 'models/coatnet_wafer.onnx'
CACHE = 'data/test_probs.npz'
SWEEP = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def summarize(decisions: list[dict], truth: np.ndarray) -> dict:
    """사람이 보지 않고 나가는 건과 그중 틀린 건을, 틀린 방식별로 나눠 센다."""
    index_of = {name: i for i, name in enumerate(CLASS_NAMES)}
    final = np.array([index_of[d['final_class']] for d in decisions])
    paths = np.array([d['decision_path'] for d in decisions])
    unattended = paths != 'REVIEW_NEEDED'
    wrong = (final != truth) & unattended
    defect = truth != NONE_INDEX
    review = ~unattended
    return {
        'n': len(decisions),
        'paths': {path: int((paths == path).sum()) for path in
                  ('AUTO_PASS', 'RULE_BASE_NONE', 'RULE_BASE_NEAR_FULL', 'REVIEW_NEEDED')},
        'unattended': float(unattended.mean()),
        'unattended_accuracy': float((final == truth)[unattended].mean()) if unattended.any() else 0.0,
        'escaped': int(wrong.sum()),
        # 실제 결함을 정상으로 내보냄 — 불량이 그대로 흘러가는 가장 나쁜 경우
        'missed_defect': int((wrong & defect & (final == NONE_INDEX)).sum()),
        # 결함은 잡았지만 유형이 틀림 — 원인 분석이 엇나간다
        'wrong_type': int((wrong & defect & (final != NONE_INDEX)).sum()),
        # 정상을 결함으로 내보냄 — 멀쩡한 웨이퍼를 버리거나 재검사한다
        'false_alarm': int((wrong & ~defect).sum()),
        'review': int(review.sum()),
        'review_ai_correct': float((final == truth)[review].mean()) if review.any() else 0.0,
        'missed_by_class': Counter(CLASS_NAMES[i] for i in truth[wrong & defect & (final == NONE_INDEX)]),
    }


def print_summary(title: str, s: dict) -> None:
    n = s['n']
    print(f'\n  ── {title} ({n:,}건)')
    for path, count in s['paths'].items():
        if count:
            print(f'      {path:<22s} {count:7,d}  {count / n:6.2%}')
    print(f"      사람이 보지 않고 나가는 건 {s['unattended']:.2%} (그 안에서 정확도 {s['unattended_accuracy']:.2%})")
    print(f"      그중 틀린 건 {s['escaped']:,}건 = 전체의 {s['escaped'] / n:.2%}")
    print(f"        · 결함을 정상으로 {s['missed_defect']:,}건 · 결함 유형 틀림 {s['wrong_type']:,}건 · "
          f"정상을 결함으로 {s['false_alarm']:,}건")
    if s['missed_by_class']:
        print('        · 정상으로 나간 결함: ' + ', '.join(
            f'{name} {count}' for name, count in s['missed_by_class'].most_common()))
    print(f"      검토 대기 {s['review']:,}건 ({s['review'] / n:.2%}) — 그중 AI 1순위가 맞은 비율 "
          f"{s['review_ai_correct']:.2%}")


def load_probabilities(dataset, test: np.ndarray, device: str, batch_size: int, cache: bool = True):
    from waferai.backends import TorchBackend, file_sha256

    model_sha = file_sha256(CHECKPOINT)
    path = Path(CACHE)
    if cache and path.is_file():
        stored = np.load(path, allow_pickle=False)
        if str(stored['model_sha256']) == model_sha and str(stored['split_id']) == dataset.split_id \
                and stored['probabilities'].shape[0] == len(test):
            print(f'  캐시 재사용: {path}')
            return stored['probabilities'], model_sha
    backend = TorchBackend(CHECKPOINT, device)
    print(f'  테스트 {len(test):,}건 추론 중 (장치 {device}) ...', flush=True)
    probs = probabilities(backend.model, [dataset.maps[i] for i in test], device, batch_size)
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, probabilities=probs, model_sha256=model_sha,
                            split_id=dataset.split_id)
    del backend
    return probs, model_sha


def embed_profile(profile: dict, model_sha: str) -> None:
    """운영 체크포인트의 test_metrics 에 확신도 프로필을 심고 ONNX 를 다시 만든다.

    학습 스크립트가 만드는 모델은 evaluate_test 가 프로필을 넣으므로 이 단계가 필요 없다.
    프로필 없이 배포된 모델(첫 재학습 모델)을 위한 한 번짜리 보정이다. 파일 해시가 바뀌므로
    서버는 다음 기동 때 이를 새 버전으로 등록한다(가중치는 같다).
    """
    import torch

    from scripts.export_onnx import export
    from waferai.backends import file_sha256

    path = Path(CHECKPOINT)
    if file_sha256(path) != model_sha:
        raise SystemExit('체크포인트가 확률 캐시를 만든 뒤 바뀌었습니다. 캐시를 지우고 다시 재세요.')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    test_metrics = dict(checkpoint.get('test_metrics') or {})
    test_metrics['confidence_profile'] = profile
    checkpoint['test_metrics'] = test_metrics
    temp = path.with_name(path.name + '.tmp')
    torch.save(checkpoint, temp)
    temp.replace(path)
    print(f'\n[프로필 심기] {path} → 새 해시 {file_sha256(path)[:12]} (가중치는 같다)')
    export(str(path), ONNX)                      # .pth 만 바꾸면 서버가 짝 불일치로 거부한다


def main() -> None:
    parser = argparse.ArgumentParser(description='판정 로직 효과 측정 (고정 테스트 셋)')
    parser.add_argument('--data', default=DEFAULT_DATA)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--limit', type=int, help='테스트 표본 상한 (동작 확인용, 캐시하지 않음)')
    parser.add_argument('--image-check', type=int, default=300,
                        help='이미지 경로 비교 표본 수 (0 이면 생략)')
    parser.add_argument('--embed-profile', action='store_true',
                        help='확신도 프로필을 운영 체크포인트에 심고 ONNX 를 다시 만든다')
    args = parser.parse_args()
    if args.embed_profile and args.limit:
        raise SystemExit('--embed-profile 은 테스트 셋 전체로 잰 프로필만 심습니다 (--limit 제거)')

    os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
    os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
    device = pick_device(args.device)

    dataset = load_training_set(args.data)
    test = dataset.indices('test')
    if args.limit:
        test = test[:args.limit]
    truth = dataset.labels[test]
    maps = [dataset.maps[i] for i in test]
    position = {index: row for row, index in enumerate(test)}
    rows = np.array([position[i] for i in balanced(test, dataset.labels, 7)], dtype=np.int64)
    print(f'[테스트 셋] split_id {dataset.split_id} · 실제 분포 {len(test):,}건 · 균형 {len(rows):,}건')

    probs, model_sha = load_probabilities(dataset, test, device, args.batch_size,
                                          cache=not args.limit)
    print(f'  모델 {model_sha[:12]} · 정확도 {float((probs.argmax(1) == truth).mean()):.4f}')
    profile = confidence_profile(probs)
    curve = dict(profile['review_curve'])
    print(f"  확신도 프로필: 최대 {profile['confidence_max']:.4f} · 임계값 0.90 이면 검토 "
          f"{curve.get(0.9, 0):.1%} · 0.92 이면 {curve.get(0.92, 0):.1%}")

    views = {'실제 분포': np.arange(len(test)), '균형': rows}

    print('\n[1] 기본 설정 (확신도 0.80 · 고밀도 0.80 · 저밀도 꺼짐)')
    for label, view in views.items():
        decisions = evaluate_decisions(probs[view], [maps[i] for i in view], CLASS_NAMES, Thresholds())
        print_summary(label, summarize(decisions, truth[view]))

    print('\n[2] 확신도 임계값별 (실제 분포) — 검토 부담과 새는 불량의 맞교환')
    print(f"      {'임계값':>6s} {'검토 대기':>10s} {'무인 통과':>10s} {'틀린 무인':>10s} {'결함→정상':>10s} {'검토 중 AI 정답':>14s}")
    natural = views['실제 분포']
    natural_maps = [maps[i] for i in natural]
    for confidence in SWEEP:
        s = summarize(evaluate_decisions(probs, natural_maps, CLASS_NAMES,
                                         Thresholds(confidence=confidence)), truth)
        n = s['n']
        print(f"      {confidence:6.2f} {s['review'] / n:10.2%} {s['unattended']:10.2%} "
              f"{s['escaped'] / n:10.2%} {s['missed_defect']:10,d} {s['review_ai_correct']:14.2%}")

    print('\n[3] 저밀도 규칙(5% 미만 → none)을 켰을 때')
    for label, view in views.items():
        view_maps = [maps[i] for i in view]
        off = summarize(evaluate_decisions(probs[view], view_maps, CLASS_NAMES, Thresholds()), truth[view])
        on = summarize(evaluate_decisions(probs[view], view_maps, CLASS_NAMES,
                                          Thresholds(low_density=0.05)), truth[view])
        print(f"      {label}: 틀린 무인 통과 {off['escaped']:,} → {on['escaped']:,}건, "
              f"결함을 정상으로 {off['missed_defect']:,} → {on['missed_defect']:,}건, "
              f"규칙이 확정한 건 {on['paths']['RULE_BASE_NONE']:,}")

    if args.image_check:
        from waferai.backends import TorchBackend

        print(f'\n[4] 이미지 경로 영향 (균형 표본 앞 {args.image_check}개)')
        sample = rows[:args.image_check]
        backend = TorchBackend(CHECKPOINT, device)
        measure_image_path(backend, [maps[i] for i in sample], truth[sample], CLASS_NAMES,
                           args.image_check)

    if args.embed_profile:
        embed_profile(profile, model_sha)


if __name__ == '__main__':
    main()
