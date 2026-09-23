"""LSWMD.pkl 에서 평가용 데이터를 한 번만 뽑아 압축 저장한다.

    python3 -m scripts.prepare_eval_set --source ~/Downloads/LSWMD.pkl

원본은 2GB 라 매번 올리면 8GB 장비에서 스왑이 심하다. 이 스크립트를 한 번 돌려
`data/eval_set.npz` 를 만들어 두고, 이후 평가는 그 파일만 쓴다.

학습(training_reference.py)의 분할을 시드까지 똑같이 재현해, 어떤 샘플이 학습에
쓰였고 어떤 샘플이 남았는지 구분한다. 재현이 맞는지는 학습 로그가 남긴
"총 학습 데이터 개수: 51038개" 와 대조해 확인한다.

저장 내용:
  val_*      학습의 검증 분할(20%). val_acc 재현과 클래스별 성능 측정에 쓴다.
  holdout_*  균형 맞추기에서 빠져 한 번도 쓰이지 않은 'none' 샘플.
             실제 분포(정상이 압도적)에서의 성능을 재는 데 쓴다.
"""
from __future__ import annotations

import argparse
import gc
from pathlib import Path

import numpy as np

CLASS_NAMES = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
               'Near-full', 'Random', 'Scratch', 'none']
LABEL_TO_INDEX = {name: i for i, name in enumerate(CLASS_NAMES)}
EXPECTED_BALANCED = 51038          # 학습 로그가 남긴 값
MAX_HOLDOUT_NONE = 20000           # 전량은 과하므로 상한을 둔다


def extract_label(value):
    """training_reference.py 의 extract_label 과 동일해야 한다."""
    if value is None or len(value) == 0:
        return 'Unlabeled'
    first = value[0]
    if isinstance(first, (list, np.ndarray)) and len(first) > 0:
        return first[0]
    return first


def pack(maps) -> tuple[np.ndarray, np.ndarray]:
    """가변 크기 맵들을 (평탄화 배열, 모양 배열) 로 묶는다. npz 는 가변 길이를 못 담는다."""
    shapes = np.array([m.shape for m in maps], dtype=np.int32)
    flat = np.concatenate([m.astype(np.uint8).ravel() for m in maps])
    return flat, shapes


def main() -> None:
    parser = argparse.ArgumentParser(description='평가용 데이터 준비')
    parser.add_argument('--source', default='~/Downloads/LSWMD.pkl')
    parser.add_argument('--output', default='data/eval_set.npz')
    parser.add_argument('--max-holdout', type=int, default=MAX_HOLDOUT_NONE)
    args = parser.parse_args()

    import pandas as pd
    from sklearn.model_selection import train_test_split

    source = Path(args.source).expanduser()
    if not source.is_file():
        raise SystemExit(f'원본이 없습니다: {source}')

    print(f'[1/5] {source.name} 로드 중 (2GB — 수 분 걸릴 수 있습니다) ...')
    raw = pd.read_pickle(source)
    print(f'      전체 샘플 {len(raw):,}개')

    print('[2/5] 레이블 추출 및 필터링 ...')
    raw['failure_type'] = raw.failureType.apply(extract_label)
    labeled = raw[raw['failure_type'] != 'Unlabeled'][['waferMap', 'failure_type']].copy()
    del raw
    gc.collect()
    print(f'      레이블 보유 {len(labeled):,}개')

    print('[3/5] 학습 분할 재현 (random_state=42) ...')
    defects = labeled[labeled['failure_type'] != 'none']
    none_used = labeled[labeled['failure_type'] == 'none'].sample(
        n=len(defects), random_state=42)
    balanced = pd.concat([defects, none_used]).reset_index(drop=True)
    print(f'      균형 데이터 {len(balanced):,}개', end='  ')
    if len(balanced) == EXPECTED_BALANCED:
        print(f'— 학습 로그({EXPECTED_BALANCED:,})와 일치')
    else:
        print(f'— 경고: 학습 로그({EXPECTED_BALANCED:,})와 다릅니다')

    _, val = train_test_split(balanced, test_size=0.2,
                              stratify=balanced['failure_type'], random_state=42)
    print(f'      검증 분할 {len(val):,}개')

    # 균형 맞추기에서 빠진 'none' — 학습이 한 번도 보지 않은 샘플
    unused_none = labeled[(labeled['failure_type'] == 'none')
                          & (~labeled.index.isin(none_used.index))]
    holdout = unused_none.sample(n=min(args.max_holdout, len(unused_none)), random_state=7)
    print(f"      미사용 'none' {len(unused_none):,}개 중 {len(holdout):,}개 보관")

    print('[4/5] 배열 묶는 중 ...')
    val_flat, val_shapes = pack(val['waferMap'].tolist())
    val_labels = np.array([LABEL_TO_INDEX[name] for name in val['failure_type']], dtype=np.int8)
    holdout_flat, holdout_shapes = pack(holdout['waferMap'].tolist())
    holdout_labels = np.full(len(holdout), LABEL_TO_INDEX['none'], dtype=np.int8)
    del labeled, balanced, val, holdout, defects, none_used, unused_none
    gc.collect()

    print('[5/5] 저장 중 ...')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        val_flat=val_flat, val_shapes=val_shapes, val_labels=val_labels,
        holdout_flat=holdout_flat, holdout_shapes=holdout_shapes,
        holdout_labels=holdout_labels,
        class_names=np.array(CLASS_NAMES),
    )
    print(f'\n완료: {output} ({output.stat().st_size / 1024 ** 2:.1f} MB)')


if __name__ == '__main__':
    main()
