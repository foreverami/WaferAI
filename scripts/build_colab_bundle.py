"""Colab 재학습용 묶음을 만든다 — Drive 에 이 zip 하나만 올리면 된다.

    python3 -m scripts.build_colab_bundle          # → build/WaferAI_colab_bundle.zip

학습에 필요한 코드(waferai/, 학습 스크립트)와 고정 분할 데이터(data/training_set.npz)를 담는다.
데이터를 Colab 에서 다시 만들지 않고 그대로 가져가는 이유: 분할이 한 샘플이라도 달라지면
split_id 가 바뀌어 기존 결과와 비교할 수 없게 된다. 같은 파일을 쓰는 것이 가장 확실하다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'build/WaferAI_colab_bundle.zip'
FILES = [
    'scripts/__init__.py', 'scripts/train.py', 'scripts/training_common.py',
    'data/training_set.npz', 'notebooks/retrain_colab.ipynb',
]


def main() -> None:
    sources = [path for path in sorted((ROOT / 'waferai').rglob('*.py'))
               if '__pycache__' not in path.parts]
    sources += [ROOT / name for name in FILES]
    missing = [str(path.relative_to(ROOT)) for path in sources if not path.is_file()]
    if missing:
        raise SystemExit(f'없는 파일: {missing}\n'
                         '  데이터가 없으면: python3 -m scripts.prepare_training_data')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sources:
            bundle.write(path, path.relative_to(ROOT))
    print(f'완료: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1024 ** 2:.1f} MB, '
          f'{len(sources)}개 파일)')
    print('Drive 의 MyDrive/WaferAI/ 에 올리고 notebooks/retrain_colab.ipynb 를 Colab 에서 연다.')


if __name__ == '__main__':
    main()
