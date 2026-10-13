"""재학습용 데이터를 만든다 — 로트 단위 train / val / test 3분할.

    python3 -m scripts.prepare_training_data --source ~/Downloads/LSWMD.pkl

1학기 학습은 웨이퍼 단위로 무작위 8:2 분할만 하고 테스트 셋을 떼지 않았다. 그 결과
결함 샘플이 전부 학습·검증에 쓰여 오염되지 않은 테스트 정확도를 낼 수 없었다.

여기서는 두 가지를 바로잡는다.

  1. 테스트 셋을 따로 뗀다 (train 80 / val 10 / test 10).
  2. 웨이퍼가 아니라 로트(lotName) 단위로 나눈다. 같은 로트의 웨이퍼는 같은 공정
     조건을 거쳐 결함 패턴이 닮는다. 같은 로트가 학습과 테스트에 갈라 들어가면 모델이
     "그 로트의 버릇"을 외워 맞히게 되고, 테스트 정확도가 실제보다 높게 나온다.

분할은 한 번 정하면 바꾸지 않는다. 앞으로의 모든 재학습이 같은 테스트 셋으로 평가돼야
새 모델과 기존 모델을 공정하게 비교할 수 있기 때문이다. split_id 가 그 분할의 지문이다.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
from pathlib import Path

import numpy as np

CLASS_NAMES = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
               'Near-full', 'Random', 'Scratch', 'none']
LABEL_TO_INDEX = {name: i for i, name in enumerate(CLASS_NAMES)}
SPLITS = {'train': 0, 'val': 1, 'test': 2}
N_FOLDS = 10          # 한 폴드 = 10%. 0번 → test, 1번 → val, 나머지 → train
SEED = 42


def extract_label(value):
    """training_reference.py 의 extract_label 과 같다."""
    if value is None or len(value) == 0:
        return 'Unlabeled'
    first = value[0]
    if isinstance(first, (list, np.ndarray)) and len(first) > 0:
        return first[0]
    return first


def pack(maps) -> tuple[np.ndarray, np.ndarray]:
    shapes = np.array([m.shape for m in maps], dtype=np.int32)
    flat = np.concatenate([np.asarray(m, dtype=np.uint8).ravel() for m in maps])
    return flat, shapes


def split_fingerprint(sample_ids: np.ndarray, split: np.ndarray) -> str:
    """어떤 샘플이 어느 분할에 들어갔는지의 지문. 분할이 바뀌면 값이 바뀐다."""
    digest = hashlib.sha256()
    for name, code in SPLITS.items():
        members = np.sort(sample_ids[split == code])
        digest.update(name.encode())
        digest.update('\n'.join(members).encode())
    return digest.hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser(description='재학습용 3분할 데이터 준비')
    parser.add_argument('--source', default='~/Downloads/LSWMD.pkl')
    parser.add_argument('--output', default='data/training_set.npz')
    args = parser.parse_args()

    import pandas as pd
    from sklearn.model_selection import StratifiedGroupKFold

    source = Path(args.source).expanduser()
    if not source.is_file():
        raise SystemExit(f'원본이 없습니다: {source}')

    print(f'[1/5] {source.name} 로드 중 (2GB — 수 분 걸립니다) ...', flush=True)
    raw = pd.read_pickle(source)
    print(f'      전체 {len(raw):,}개 · 열 {list(raw.columns)}', flush=True)

    print('[2/5] 레이블 추출 ...', flush=True)
    raw['failure_type'] = raw.failureType.apply(extract_label)
    raw['official'] = raw.trianTestLabel.apply(extract_label)       # 원 데이터셋의 분할 표기
    labeled = raw[raw['failure_type'] != 'Unlabeled'][
        ['waferMap', 'failure_type', 'lotName', 'waferIndex', 'official']].copy()
    del raw
    gc.collect()
    labeled = labeled.reset_index(drop=True)
    lots = labeled['lotName'].astype(str).to_numpy()
    wafer_index = labeled['waferIndex'].astype(float).astype(int).to_numpy()
    sample_ids = np.array([f'{lot}#{index}' for lot, index in zip(lots, wafer_index)])
    labels = labeled['failure_type'].map(LABEL_TO_INDEX).to_numpy().astype(np.int8)
    duplicates = len(sample_ids) - len(set(sample_ids))
    print(f'      레이블 보유 {len(labeled):,}개 · 로트 {len(set(lots)):,}개 · 중복 ID {duplicates}개',
          flush=True)

    print('[3/5] 로트 단위 층화 분할 (StratifiedGroupKFold) ...', flush=True)
    folds = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    split = np.full(len(labeled), SPLITS['train'], dtype=np.int8)
    for fold, (_, members) in enumerate(folds.split(np.zeros(len(labels)), labels, groups=lots)):
        if fold == 0:
            split[members] = SPLITS['test']
        elif fold == 1:
            split[members] = SPLITS['val']
        else:
            break

    # 로트가 두 분할에 걸치지 않는지 확인한다 — 이 분할의 존재 이유다
    lots_by_split = {name: set(lots[split == code]) for name, code in SPLITS.items()}
    overlap = {f'{a}∩{b}': len(lots_by_split[a] & lots_by_split[b])
               for a, b in (('train', 'val'), ('train', 'test'), ('val', 'test'))}
    if any(overlap.values()):
        raise SystemExit(f'로트가 분할 사이에 겹칩니다: {overlap}')
    fingerprint = split_fingerprint(sample_ids, split)
    print(f'      로트 겹침 {overlap} · split_id {fingerprint}', flush=True)

    print('      분할별 클래스 분포:', flush=True)
    header = '      ' + f'{"":>10s}' + ''.join(f'{n:>10s}' for n in SPLITS)
    print(header, flush=True)
    for index, name in enumerate(CLASS_NAMES):
        counts = [int(((labels == index) & (split == code)).sum()) for code in SPLITS.values()]
        print('      ' + f'{name:>10s}' + ''.join(f'{c:>10,d}' for c in counts), flush=True)
    totals = [int((split == code).sum()) for code in SPLITS.values()]
    print('      ' + f'{"합계":>9s}' + ''.join(f'{c:>10,d}' for c in totals), flush=True)

    # 참고: 원 데이터셋 분할이 로트를 갈라놓았는지
    official = labeled['official'].astype(str).to_numpy()
    official_lots = {name: set(lots[official == name]) for name in set(official)}
    if {'Training', 'Test'} <= set(official_lots):
        shared = len(official_lots['Training'] & official_lots['Test'])
        print(f'      (참고) 원 데이터셋 Training/Test 분할의 로트 겹침: {shared:,}개', flush=True)

    print('[4/5] 배열 묶는 중 ...', flush=True)
    flat, shapes = pack(labeled['waferMap'].tolist())
    del labeled
    gc.collect()

    print('[5/5] 저장 중 ...', flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output, flat=flat, shapes=shapes, labels=labels, split=split,
        sample_ids=sample_ids, lots=lots, official=official,
        class_names=np.array(CLASS_NAMES), split_id=np.array(fingerprint),
        split_names=np.array(list(SPLITS)),
    )
    print(f'\n완료: {output} ({output.stat().st_size / 1024 ** 2:.1f} MB) · split_id {fingerprint}')


if __name__ == '__main__':
    main()
