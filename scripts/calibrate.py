"""운영 모델의 확률 보정 · 클래스별 임계값 · 입력 감지 기준을 맞추고, 효과를 테스트 셋으로 잰다.

    python3 -m scripts.calibrate                 # 재기만 한다 (docs/calibration_report.json)
    python3 -m scripts.calibrate --embed         # 결과를 운영 체크포인트에 심고 ONNX 를 다시 만든다

원칙 — 맞추는 것은 전부 검증 분할(val)에서, 효과는 학습에도 보정에도 쓰지 않은 테스트 셋에서만
잰다. 테스트 셋으로 임계값을 고르면 그 수치는 다시 부풀려진 값이 된다.

  1. 온도(T): 검증 분할 NLL 최소. 정확도는 그대로, 확신도의 척도만 바뀐다.
  2. 클래스별 임계값: 검증 분할에서 (틀린 무인 통과 비용 + λ × 검토 건수) 를 좌표 하강으로 줄인다.
     결함을 정상으로 내보내는 오류는 MISSED_WEIGHT 배로 무겁게 센다.
  3. 입력 감지: 학습 · 검증 · 테스트 맵 172,950장의 모양 분포와, 합성한 가짜 입력으로 잰다.
  4. 색상표: 테스트 맵을 다른 색상표로 그려 되읽었을 때 맵이 그대로 복원되는지 잰다.

확률은 data/val_probs.npz, data/test_probs.npz 캐시를 쓴다 (모델 해시 · 분할이 맞을 때만).
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.training_common import (CLASS_NAMES, DEFAULT_DATA, NONE_INDEX, balanced,
                                     confidence_profile, load_training_set, pick_device,
                                     probabilities)
from waferai import ood
from waferai.calibration import apply_temperature, expected_calibration_error, fit_temperature
from waferai.decision import Thresholds, decide
from waferai.preprocess import defect_ratio

CHECKPOINT = 'models/best_coatnet_model_optimized.pth'
ONNX = 'models/coatnet_wafer.onnx'
CACHES = {'val': 'data/val_probs.npz', 'test': 'data/test_probs.npz'}
REPORT = 'docs/calibration_report.json'

#: 보정된 확신도는 0.98 – 0.999 에 몰린다. 위쪽은 0.001 간격으로 본다.
GRID = np.round(np.concatenate([np.arange(0.50, 0.99, 0.01), np.arange(0.990, 0.9995, 0.001)]), 3)
#: 목표 함수 — 검증 분할에서 (무게 3, 5, 10, 20, 40) × (검토 비용 0.05 – 0.5) 를 훑어 골랐다.
#: 결함을 정상으로 내보내는 오류 1건 = 유형 오류 10건, 검토 1건 = 유형 오류 0.2건.
#: 이 점에서 검토가 약 2%p 늘고 틀린 무인 통과와 결함 누락이 절반 가까이 준다. 더 엄격한 점
#: (검토 비용 0.1)은 결함 누락이 거의 0 이지만 검토가 9% 를 넘어 기본값으로 두지 않았다.
MISSED_WEIGHT = 10.0
REVIEW_COST = 0.2
HIGH_DENSITY = 0.80


# ── 확률 ────────────────────────────────────────────────────────────────────

def load_probs(split: str, dataset, indices: np.ndarray, device: str) -> np.ndarray:
    from waferai.backends import TorchBackend, file_sha256

    sha = file_sha256(CHECKPOINT)
    path = Path(CACHES[split])
    if path.is_file():
        stored = np.load(path, allow_pickle=False)
        if str(stored['model_sha256']) == sha and str(stored['split_id']) == dataset.split_id \
                and stored['probabilities'].shape[0] == len(indices):
            return stored['probabilities']
    print(f'  {split} {len(indices):,}건 추론 중 (장치 {device}) ...', flush=True)
    backend = TorchBackend(CHECKPOINT, device)
    probs = probabilities(backend.model, [dataset.maps[i] for i in indices], device, 16)
    np.savez_compressed(path, probabilities=probs, model_sha256=sha, split_id=dataset.split_id)
    return probs


# ── 판정 비용 (벡터화 — 임계값 탐색용) ───────────────────────────────────────

def outcome(conf, top1, truth, rule, thresholds: np.ndarray) -> dict:
    """클래스별 임계값 배열로 판정했을 때의 건수. rule = 고밀도 규칙에 걸림(Near-full 확정)."""
    final = np.where(rule, CLASS_NAMES.index('Near-full'), top1)
    unattended = rule | (conf >= thresholds[top1])
    wrong = unattended & (final != truth)
    missed = wrong & (truth != NONE_INDEX) & (final == NONE_INDEX)
    return {'review': int((~unattended).sum()), 'wrong': int(wrong.sum()), 'missed': int(missed.sum())}


def cost(o: dict, review_cost: float) -> float:
    return (o['wrong'] - o['missed']) + MISSED_WEIGHT * o['missed'] + review_cost * o['review']


def fit_class_thresholds(conf, top1, truth, rule, start: float, review_cost: float) -> np.ndarray:
    thresholds = np.full(len(CLASS_NAMES), start)
    for _ in range(4):
        changed = False
        for k in range(len(CLASS_NAMES)):
            best_t, best_c = thresholds[k], cost(outcome(conf, top1, truth, rule, thresholds), review_cost)
            for t in GRID:
                trial = thresholds.copy()
                trial[k] = t
                c = cost(outcome(conf, top1, truth, rule, trial), review_cost)
                if c < best_c - 1e-9:
                    best_t, best_c = t, c
            if best_t != thresholds[k]:
                thresholds[k], changed = best_t, True
        if not changed:
            break
    return thresholds


def global_threshold_for_review(conf, top1, truth, rule, review_target: int) -> float:
    """검토 건수가 review_target 에 가장 가까운 단일 임계값 — 클래스별 임계값의 효과를 떼어 보기 위함."""
    best = min(GRID, key=lambda t: abs(outcome(conf, top1, truth, rule, np.full(9, t))['review'] - review_target))
    return float(best)


# ── 실제 판정 함수로 잰 결과 (보고용) ─────────────────────────────────────────

def decide_all(probs, maps, truth, thresholds: Thresholds, use_shape: bool) -> dict:
    final, paths = [], []
    for p, wm in zip(probs, maps):
        reasons = list(ood.check_shape(wm).reasons) if use_shape else None
        d = decide({n: float(v) for n, v in zip(CLASS_NAMES, p)}, defect_ratio(wm), thresholds,
                   out_of_scope=reasons or None)
        final.append(CLASS_NAMES.index(d['final_class']))
        paths.append(d['decision_path'])
    final, paths = np.array(final), np.array(paths)
    unattended = ~np.isin(paths, ['REVIEW_NEEDED', 'OUT_OF_SCOPE'])
    wrong = unattended & (final != truth)
    defect = truth != NONE_INDEX
    review = ~unattended
    missed_mask = wrong & defect & (final == NONE_INDEX)
    n = len(truth)
    return {
        'n': n,
        'paths': {p: int((paths == p).sum()) for p in
                  ('AUTO_PASS', 'RULE_BASE_NEAR_FULL', 'REVIEW_NEEDED', 'OUT_OF_SCOPE')},
        'unattended_rate': round(float(unattended.mean()), 4),
        'unattended_accuracy': round(float((final == truth)[unattended].mean()), 4),
        'review_rate': round(float(review.mean()), 4),
        'review': int(review.sum()),
        'escaped': int(wrong.sum()),
        'escaped_rate': round(float(wrong.mean()), 4),
        'missed_defect': int(missed_mask.sum()),
        'missed_by_class': {CLASS_NAMES[k]: int(((truth == k) & missed_mask).sum())
                            for k in range(len(CLASS_NAMES)) if ((truth == k) & missed_mask).any()},
        'wrong_type': int((wrong & defect & (final != NONE_INDEX)).sum()),
        'false_alarm': int((wrong & ~defect).sum()),
        'review_ai_correct': round(float((final == truth)[review].mean()), 4) if review.any() else None,
    }


# ── 입력 감지 ────────────────────────────────────────────────────────────────

def synthetic_inputs(seed: int = 3) -> dict[str, list[np.ndarray]]:
    """웨이퍼 맵이 아닌 입력들. 모두 0/1/2 값이라 형식 검사는 통과한다."""
    rng = np.random.default_rng(seed)
    out: dict[str, list[np.ndarray]] = {k: [] for k in
                                       ('무작위 잡음', '가득 찬 사각형', '체크무늬', '줄무늬', '사각 웨이퍼', '아주 작은 웨이퍼')}
    for _ in range(100):
        h, w = rng.integers(30, 160, size=2)
        out['무작위 잡음'].append(rng.integers(0, 3, size=(h, w)).astype(np.uint8))
        rect = np.ones((h, w), np.uint8)
        rect[rng.random((h, w)) < rng.uniform(0.02, 0.5)] = 2
        out['가득 찬 사각형'].append(rect)
        yy, xx = np.indices((h, w))
        cell = int(rng.integers(1, 6))
        out['체크무늬'].append((((yy // cell + xx // cell) % 2) + 1).astype(np.uint8))
        stripes = ((yy // int(rng.integers(1, 6))) % 3).astype(np.uint8)
        out['줄무늬'].append(stripes)
        square = np.zeros((h + 6, w + 6), np.uint8)
        square[3:-3, 3:-3] = 1
        square[3:-3, 3:-3][rng.random((h, w)) < 0.1] = 2
        out['사각 웨이퍼'].append(square)
        r = int(rng.integers(3, 7))
        yy, xx = np.indices((2 * r + 1, 2 * r + 1))
        tiny = (((yy - r) ** 2 + (xx - r) ** 2) <= r * r).astype(np.uint8)
        out['아주 작은 웨이퍼'].append(tiny)
    return out


def measure_ood(dataset, device: str, temperature: float, class_thr: dict) -> dict:
    checks = [ood.check_shape(m) for m in dataset.maps]
    features = np.array([[c.ellipse_iou, c.die_fraction, c.dies] for c in checks])
    flagged_real = np.array([not c.in_distribution for c in checks])
    result = {
        'real_maps': len(dataset.maps),
        'real_flagged': int(flagged_real.sum()),
        'real_flagged_test': int(flagged_real[dataset.indices('test')].sum()),
        'ellipse_iou_percentiles': {str(q): round(float(np.percentile(features[:, 0], q)), 4)
                                    for q in (0.05, 0.1, 1, 50)},
        'die_fraction_percentiles': {str(q): round(float(np.percentile(features[:, 1], q)), 4)
                                     for q in (0.05, 1, 50, 99, 99.95)},
        'synthetic': {},
    }
    # 합성 입력을 모델에 넣으면 무엇이라 하는지 — 모양 검사 없이는 몇 장이 자동 통과됐을지
    from waferai.backends import TorchBackend

    backend = TorchBackend(CHECKPOINT, device)
    thresholds = Thresholds(class_confidence=class_thr)
    for name, maps in synthetic_inputs().items():
        caught = sum(not ood.check_shape(m).in_distribution for m in maps)
        probs = apply_temperature(probabilities(backend.model, maps, device, 16), temperature)
        would_pass = 0
        for p, wm in zip(probs, maps):
            d = decide({n: float(v) for n, v in zip(CLASS_NAMES, p)}, defect_ratio(wm), thresholds)
            would_pass += d['decision_path'] != 'REVIEW_NEEDED'
        result['synthetic'][name] = {'n': len(maps), 'caught': int(caught),
                                     'auto_pass_without_check': int(would_pass)}
    return result


# ── 색상표 ───────────────────────────────────────────────────────────────────

def measure_palettes(maps: list[np.ndarray], seed: int = 5) -> dict:
    import cv2

    from waferai.image_adapter import (KNOWN_PALETTES, UnsupportedImage, encode_png,
                                       image_to_wafer_map)
    from waferai.preprocess import COLOR_LUT, pad_to_square

    rng = np.random.default_rng(seed)
    palettes = {'training': COLOR_LUT.astype(np.uint8), **{k: v.astype(np.uint8) for k, v in KNOWN_PALETTES.items()}}
    result = {}
    reference = []
    for wm in maps:
        square = cv2.resize(pad_to_square(wm), (224, 224), interpolation=cv2.INTER_NEAREST)
        reference.append(square)
    for name in list(palettes) + ['random']:
        same = guessed = rejected = wrong_unflagged = 0
        for square in reference:
            if name == 'random':
                while True:
                    colors = rng.integers(0, 256, size=(3, 3)).astype(np.uint8)
                    if min(np.linalg.norm(colors[i].astype(float) - colors[j]) for i in range(3) for j in range(i)) > 120:
                        break
                palette = colors
            else:
                palette = palettes[name]
            try:
                restored, info = image_to_wafer_map(encode_png(palette[square]))
            except UnsupportedImage:
                rejected += 1
                continue
            guessed += bool(info['palette'].get('guessed'))
            content = ood.crop_content(square)
            exact = restored.shape == content.shape and bool((restored == content).all())
            same += exact
            # 잘못 읽었는데 사람 검토로도 가지 않는 경우 — 0 이어야 한다
            wrong_unflagged += (not exact) and not info['palette'].get('guessed')
        result[name] = {'n': len(reference), 'restored_exactly': same, 'guessed': guessed,
                        'rejected': rejected, 'wrong_unflagged': wrong_unflagged}
    return result


# ── 체크포인트에 심기 ────────────────────────────────────────────────────────

def embed(calibration: dict, profile: dict) -> None:
    import shutil

    import torch

    from scripts.export_onnx import export
    from waferai.backends import file_sha256

    path = Path(CHECKPOINT)
    backup = path.with_name(f'backup_{file_sha256(path)[:12]}.pth')
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f'  기존 체크포인트 보관: {backup}')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    test_metrics = dict(checkpoint.get('test_metrics') or {})
    test_metrics['confidence_profile'] = profile          # 설정 화면 상한은 보정된 확신도 기준
    checkpoint['test_metrics'] = test_metrics
    checkpoint['calibration'] = calibration
    temp = path.with_name(path.name + '.tmp')
    torch.save(checkpoint, temp)
    temp.replace(path)
    print(f'\n[심기] {path} → 새 해시 {file_sha256(path)[:12]} (가중치는 같다)')
    export(str(path), ONNX)


def main() -> None:
    global MISSED_WEIGHT
    parser = argparse.ArgumentParser(description='확률 보정 · 클래스별 임계값 · 입력 감지 측정')
    parser.add_argument('--data', default=DEFAULT_DATA)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--review-cost', type=float, default=REVIEW_COST)
    parser.add_argument('--missed-weight', type=float, default=MISSED_WEIGHT)
    parser.add_argument('--embed', action='store_true', help='운영 체크포인트에 심고 ONNX 를 다시 만든다')
    args = parser.parse_args()

    MISSED_WEIGHT = args.missed_weight
    os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
    os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
    device = pick_device(args.device)
    dataset = load_training_set(args.data)
    split = {name: dataset.indices(name) for name in ('val', 'test')}
    truth = {name: dataset.labels[idx] for name, idx in split.items()}
    maps = {name: [dataset.maps[i] for i in idx] for name, idx in split.items()}
    raw = {name: load_probs(name, dataset, idx, device) for name, idx in split.items()}
    rule = {name: np.array([defect_ratio(m) > HIGH_DENSITY for m in maps[name]]) for name in split}
    print(f'[데이터] split_id {dataset.split_id} · 검증 {len(truth["val"]):,} · 테스트 {len(truth["test"]):,}')

    # 1. 온도
    temperature = fit_temperature(raw['val'], truth['val'])
    cal = {name: apply_temperature(raw[name], temperature) for name in split}
    ece = {f'{name}_{kind}': round(expected_calibration_error(p, truth[name]), 4)
           for name in split for kind, p in (('before', raw[name]), ('after', cal[name]))}
    print(f'[1] 온도 T = {temperature} · ECE 테스트 {ece["test_before"]} → {ece["test_after"]}')

    # 2. 클래스별 임계값 (검증 분할에서)
    conf_v, top_v = cal['val'].max(1), cal['val'].argmax(1)
    thr = fit_class_thresholds(conf_v, top_v, truth['val'], rule['val'], 0.80, args.review_cost)
    class_thresholds = {name: float(t) for name, t in zip(CLASS_NAMES, thr)}
    print('[2] 클래스별 임계값 (검증 분할에서 맞춤):', class_thresholds)

    # 같은 검토량에서 단일 임계값이었다면 — 클래스별 임계값의 몫을 떼어 본다
    review_val = outcome(conf_v, top_v, truth['val'], rule['val'], thr)['review']
    same_review_global = global_threshold_for_review(conf_v, top_v, truth['val'], rule['val'], review_val)

    # 3. 테스트 셋에서 실제 판정 함수로
    test_maps, test_truth = maps['test'], truth['test']
    scenarios = {
        'before': (raw['test'], Thresholds(), False),
        'calibrated_same_review_global': (cal['test'], Thresholds(confidence=same_review_global), False),
        'after': (cal['test'], Thresholds(class_confidence=class_thresholds), True),
    }
    effect = {}
    position = {index: row for row, index in enumerate(split['test'])}
    rows = np.array([position[i] for i in balanced(split['test'], dataset.labels, 7)], dtype=np.int64)
    for key, (probs, thresholds, use_shape) in scenarios.items():
        effect[key] = {
            'natural': decide_all(probs, test_maps, test_truth, thresholds, use_shape),
            'balanced': decide_all(probs[rows], [test_maps[i] for i in rows], test_truth[rows],
                                   thresholds, use_shape),
        }
        n = effect[key]['natural']
        print(f"[3] {key:<32s} 검토 {n['review_rate']:.2%} · 틀린 무인 {n['escaped']} · "
              f"결함→정상 {n['missed_defect']} · 무인 정확도 {n['unattended_accuracy']:.2%}")

    # 4. 입력 감지 · 5. 색상표
    print('[4] 입력 감지 측정 중 ...', flush=True)
    ood_result = measure_ood(dataset, device, temperature, class_thresholds)
    print(f"    실제 맵 {ood_result['real_maps']:,}장 중 걸린 것 {ood_result['real_flagged']} "
          f"(테스트 {ood_result['real_flagged_test']})")
    for name, r in ood_result['synthetic'].items():
        print(f"    {name:<10s} {r['caught']}/{r['n']} 감지 · 검사 없었다면 무인 통과 {r['auto_pass_without_check']}")
    print('[5] 색상표 측정 중 ...', flush=True)
    palette_maps = [test_maps[i] for i in rows[:400]]
    palettes = measure_palettes(palette_maps)
    for name, r in palettes.items():
        print(f"    {name:<9s} 정확 복원 {r['restored_exactly']}/{r['n']} · 추정 {r['guessed']} · 거부 {r['rejected']} "
              f"· 잘못 읽고 검토도 안 감 {r['wrong_unflagged']}")

    profile = confidence_profile(cal['test'])
    calibration = {
        'temperature': temperature,
        'class_thresholds': class_thresholds,
        'fitted_on': 'val',
        'split_id': dataset.split_id,
        'objective': {'missed_defect_weight': MISSED_WEIGHT, 'review_cost': args.review_cost},
        'ece': ece,
        'test_effect': {k: v['natural'] for k, v in effect.items()},
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    report = {
        'calibration': calibration,
        'same_review_global_threshold': same_review_global,
        'effect': effect,
        'ood': ood_result,
        'palettes': palettes,
        'confidence_profile_before': confidence_profile(raw['test']),
        'confidence_profile_after': profile,
    }
    Path(REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'\n보고서: {REPORT}')
    if args.embed:
        embed(calibration, profile)


if __name__ == '__main__':
    main()
