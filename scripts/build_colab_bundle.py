"""Colab 재학습용 묶음을 만든다 — Drive 에 이 zip 하나만 올리면 된다.

    python3 -m scripts.build_colab_bundle          # → build/WaferAI_colab_bundle.zip
                                                   #   build/colab_upload/ (나눠 올리기용)

학습에 필요한 코드(waferai/, 학습 스크립트)와 고정 분할 데이터(data/training_set.npz)를 담는다.
데이터를 Colab 에서 다시 만들지 않고 그대로 가져가는 이유: 분할이 한 샘플이라도 달라지면
split_id 가 바뀌어 기존 결과와 비교할 수 없게 된다. 같은 파일을 쓰는 것이 가장 확실하다.

build/colab_upload/ 에는 같은 묶음을 9MB 조각으로 나눈 파일, 원본 해시, 노트북을 둔다.
한 번에 올릴 수 있는 크기가 제한된 업로드 경로용이다. 노트북이 조각을 이어 붙이고
해시로 원본과 같은지 확인한다.
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'build/WaferAI_colab_bundle.zip'
UPLOAD_DIR = ROOT / 'build/colab_upload'
NOTEBOOK = 'notebooks/retrain_colab.ipynb'
PART_BYTES = 9 * 1024 ** 2
FILES = [
    'scripts/__init__.py', 'scripts/train.py', 'scripts/training_common.py',
    'data/training_set.npz', NOTEBOOK,
]


def split_for_upload(bundle: Path, folder: Path, part_bytes: int = PART_BYTES) -> list[Path]:
    """묶음을 조각내고 원본 해시와 노트북을 함께 둔다. 조각 이름은 정렬 순서가 곧 순서다."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    data = bundle.read_bytes()
    written = []
    for number, start in enumerate(range(0, len(data), part_bytes)):
        part = folder / f'{bundle.name}.part{number:02d}'
        part.write_bytes(data[start:start + part_bytes])
        written.append(part)
    checksum = folder / f'{bundle.name}.sha256'
    checksum.write_text(f'{hashlib.sha256(data).hexdigest()}  {bundle.name}\n')
    notebook = folder / Path(NOTEBOOK).name
    shutil.copy2(ROOT / NOTEBOOK, notebook)
    return written + [checksum, notebook]


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
    uploads = split_for_upload(OUTPUT, UPLOAD_DIR)
    print(f'나눠 올리기용: {UPLOAD_DIR.relative_to(ROOT)}/ ({len(uploads)}개 파일, '
          f'조각당 {PART_BYTES // 1024 ** 2}MB 이하)')
    print('둘 중 하나를 Drive 의 MyDrive/WaferAI/ 에 올리고 retrain_colab.ipynb 를 Colab 에서 연다.')


if __name__ == '__main__':
    main()
