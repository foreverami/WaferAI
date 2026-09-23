"""WaferAI Vision API.

Phase 1 범위: 업로드 → 전처리 → 추론 → 판정 → 기록 → 검토.
인증과 PostgreSQL 은 Phase 2, Grad-CAM 은 Phase 3 에서 붙인다.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from waferai.backends import CLASSES
from waferai.decision import Thresholds
from waferai.image_adapter import UnsupportedImage, image_to_wafer_map
from waferai.inference import DEFAULT_CHECKPOINT, DEFAULT_ONNX, Predictor
from waferai.preprocess import validate_map

ROOT = Path(__file__).resolve().parent.parent

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_MAP_SIDE = 512
ARRAY_SUFFIXES = {'.npy', '.csv', '.json'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg'}
RECORD_LIMIT = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_array(raw: bytes, suffix: str) -> np.ndarray:
    if suffix == '.npy':
        return np.load(io.BytesIO(raw), allow_pickle=False)
    if suffix == '.csv':
        return np.loadtxt(io.BytesIO(raw), delimiter=',', ndmin=2)
    return np.asarray(json.loads(raw))


class Review(BaseModel):
    """검토 결과 본문.

    모듈 최상위에 두어야 한다. `from __future__ import annotations` 로 애노테이션이
    문자열이 되기 때문에, FastAPI 가 `get_type_hints` 로 모듈 전역에서 이 이름을
    찾을 수 있어야 한다. 함수 안에 두면 해석에 실패해 본문이 쿼리 파라미터로 취급된다.
    """

    label: Literal[tuple(CLASSES)]               # type: ignore[valid-type]
    note: str = Field(default='', max_length=2000)


def _read_upload(file: UploadFile) -> tuple[np.ndarray, dict]:
    """업로드 → (0/1/2 맵, 입력 진단 정보). 실패는 모두 422 로 올린다."""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f'파일은 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 이하여야 합니다')

    suffix = Path(file.filename or '').suffix.lower()
    try:
        if suffix in IMAGE_SUFFIXES:
            return image_to_wafer_map(raw)
        if suffix in ARRAY_SUFFIXES:
            wafer_map = _parse_array(raw, suffix)
            if wafer_map.ndim != 2 or max(wafer_map.shape, default=0) > MAX_MAP_SIDE:
                raise ValueError(f'맵은 최대 {MAX_MAP_SIDE}x{MAX_MAP_SIDE} 의 2차원 배열이어야 합니다')
            return validate_map(wafer_map), {'source': 'array', 'warnings': []}
        raise ValueError('NPY, CSV, JSON, PNG, JPG 형식만 지원합니다')
    except HTTPException:
        raise
    except (UnsupportedImage, ValueError) as error:
        raise HTTPException(422, f'입력 오류: {error}') from error
    except Exception as error:                      # 손상된 파일 등
        raise HTTPException(422, f'입력을 읽을 수 없습니다: {error}') from error


def create_app(db_path=None, checkpoint=None, onnx_path=None, backend: str = 'auto',
               thresholds: Thresholds | None = None) -> FastAPI:
    db_path = Path(db_path or ROOT / 'data/waferai.sqlite3')
    checkpoint = Path(checkpoint or ROOT / DEFAULT_CHECKPOINT)
    onnx_path = Path(onnx_path or ROOT / DEFAULT_ONNX)
    thresholds = thresholds or Thresholds()
    lock = Lock()

    @contextmanager
    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(connection) -> None:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS records ('
            'id TEXT PRIMARY KEY, created TEXT, filename TEXT, map TEXT, '
            'result TEXT, model_version TEXT)')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS reviews ('
            'id INTEGER PRIMARY KEY, record_id TEXT, created TEXT, label TEXT, note TEXT)')
        # 기존 개발 DB 에도 새 컬럼을 더한다. Phase 2 에서 Alembic 으로 대체한다.
        existing = {row['name'] for row in connection.execute('PRAGMA table_info(records)')}
        for column in ('input_type', 'input_info', 'backend'):
            if column not in existing:
                connection.execute(f'ALTER TABLE records ADD COLUMN {column} TEXT')

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect() as connection:
            migrate(connection)
        app.state.predictor = Predictor.from_paths(checkpoint, onnx_path, backend, thresholds)
        source = app.state.predictor.backend.source_path
        app.state.version = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        yield

    app = FastAPI(title='WaferAI Vision API', lifespan=lifespan)

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'waferai/static/index.html')

    @app.get('/healthz')
    def healthz():
        return {'status': 'ok', 'backend': app.state.predictor.backend.name}

    @app.get('/api/status')
    def status():
        return {
            'model_ready': True,
            'metadata': app.state.predictor.metadata,
            'model_version': app.state.version,
            'classes': CLASSES,
            'thresholds': app.state.predictor.thresholds.as_dict(),
            'accepted_formats': sorted(ARRAY_SUFFIXES | IMAGE_SUFFIXES),
        }

    @app.get('/api/records')
    def records():
        with connect() as connection:
            rows = connection.execute(
                'SELECT id, created, filename, result, model_version, input_type '
                'FROM records ORDER BY created DESC LIMIT ?', (RECORD_LIMIT,)).fetchall()
            output = []
            for row in rows:
                item = dict(row)
                item['result'] = json.loads(item['result'])
                latest = connection.execute(
                    'SELECT * FROM reviews WHERE record_id=? ORDER BY id DESC LIMIT 1',
                    (item['id'],)).fetchone()
                item['review'] = dict(latest) if latest else None
                output.append(item)
            return output

    @app.get('/api/records/{record_id}')
    def detail(record_id: str):
        with connect() as connection:
            row = connection.execute('SELECT * FROM records WHERE id=?', (record_id,)).fetchone()
            if not row:
                raise HTTPException(404, '기록이 없습니다')
            item = dict(row)
            for key in ('map', 'result'):
                item[key] = json.loads(item[key])
            item['input_info'] = json.loads(item['input_info']) if item.get('input_info') else None
            item['reviews'] = [dict(review) for review in connection.execute(
                'SELECT * FROM reviews WHERE record_id=? ORDER BY id DESC', (record_id,))]
            return item

    @app.post('/api/predict')
    def inference(file: UploadFile):
        wafer_map, input_info = _read_upload(file)
        with lock:
            result = app.state.predictor.predict(wafer_map)
        result['input'] = input_info

        record_id = str(uuid.uuid4())
        with connect() as connection:
            connection.execute(
                'INSERT INTO records (id, created, filename, map, result, model_version, '
                'input_type, input_info, backend) VALUES (?,?,?,?,?,?,?,?,?)',
                (record_id, _now(), file.filename,
                 json.dumps(wafer_map.astype(int).tolist()), json.dumps(result),
                 app.state.version, input_info.get('source'), json.dumps(input_info),
                 app.state.predictor.backend.name))
        return detail(record_id)

    @app.post('/api/records/{record_id}/review')
    def review(record_id: str, body: Review):
        with connect() as connection:
            if not connection.execute('SELECT id FROM records WHERE id=?',
                                      (record_id,)).fetchone():
                raise HTTPException(404, '기록이 없습니다')
            connection.execute(
                'INSERT INTO reviews (record_id, created, label, note) VALUES (?,?,?,?)',
                (record_id, _now(), body.label, body.note))
        return detail(record_id)

    return app


app = create_app()
