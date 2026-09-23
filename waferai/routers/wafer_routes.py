"""웨이퍼 업로드·조회·검토."""
from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from waferai.auth import current_user, get_session, require_engineer
from waferai.decision import Thresholds
from waferai.heatmap import top_class
from waferai.image_adapter import UnsupportedImage, image_to_wafer_map
from waferai.models import ReviewResult, Setting, THRESHOLDS_KEY, User, WaferResult
from waferai.preprocess import validate_map
from waferai.schemas import (ApproveRequest, ReviewRequest, WaferDetail,
                              WaferSummary)

router = APIRouter(prefix='/api', tags=['wafers'])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_MAP_SIDE = 512
ARRAY_SUFFIXES = {'.npy', '.csv', '.json'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg'}
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def load_thresholds(session: Session) -> Thresholds:
    """설정 테이블의 임계값. 없으면 코드 기본값."""
    row = session.get(Setting, THRESHOLDS_KEY)
    if row is None:
        return Thresholds()
    stored = dict(row.value)
    stored.pop('updated_at', None)
    stored.pop('updated_by', None)
    return Thresholds(**stored)


def _parse_array(raw: bytes, suffix: str) -> np.ndarray:
    if suffix == '.npy':
        return np.load(io.BytesIO(raw), allow_pickle=False)
    if suffix == '.csv':
        return np.loadtxt(io.BytesIO(raw), delimiter=',', ndmin=2)
    return np.asarray(json.loads(raw))


def read_upload(file: UploadFile) -> tuple[np.ndarray, dict]:
    """업로드 → (0/1/2 맵, 입력 진단). 형식·크기 오류는 모두 4xx 로 올린다."""
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
    except Exception as error:
        raise HTTPException(422, f'입력을 읽을 수 없습니다: {error}') from error


def _detail(session: Session, wafer_id: str) -> WaferDetail:
    wafer = session.execute(
        select(WaferResult)
        .options(selectinload(WaferResult.reviews), selectinload(WaferResult.model))
        .where(WaferResult.wafer_id == wafer_id)).scalar_one_or_none()
    if wafer is None:
        raise HTTPException(404, '기록이 없습니다')
    detail = WaferDetail.model_validate(wafer)
    detail.model_version = wafer.model.file_sha256 if wafer.model else None
    return detail


@router.post('/predict', response_model=WaferDetail)
def predict(request: Request, file: UploadFile,
            user: User = Depends(require_engineer),
            session: Session = Depends(get_session)):
    wafer_map, input_info = read_upload(file)
    predictor = request.app.state.predictor

    with request.app.state.predict_lock:
        result = predictor.predict(wafer_map, load_thresholds(session))

    wafer = WaferResult(
        wafer_id=str(uuid.uuid4()),
        filename=file.filename,
        input_type=input_info.get('source', 'array'),
        input_info=input_info,
        wafer_map=wafer_map.astype(int).tolist(),
        probabilities=result['probabilities'],
        final_class=result['final_class'],
        decision_path=result['decision_path'],
        confidence=result['confidence'],
        defect_ratio=result['defect_ratio'],
        requires_human_review=result['requires_human_review'],
        model_id=request.app.state.model_id,
        uploaded_by=user.employee_id,
    )
    session.add(wafer)
    session.flush()
    return _detail(session, wafer.wafer_id)


@router.get('/records', response_model=list[WaferSummary])
def records(session: Session = Depends(get_session),
            _: User = Depends(current_user),
            review_only: bool = Query(False, description='검토 대기 건만'),
            limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
            offset: int = Query(0, ge=0)):
    statement = (select(WaferResult)
                 .options(selectinload(WaferResult.reviews))
                 .order_by(WaferResult.processed_at.desc())
                 .limit(limit).offset(offset))
    if review_only:
        statement = statement.where(WaferResult.requires_human_review.is_(True))
    return [WaferSummary.model_validate(row) for row in session.execute(statement).scalars()]


@router.get('/records/{wafer_id}', response_model=WaferDetail)
def detail(wafer_id: str, session: Session = Depends(get_session),
           _: User = Depends(current_user)):
    return _detail(session, wafer_id)


def _record_review(session: Session, wafer: WaferResult, label: str,
                   reviewer_id: str, memo: str) -> None:
    """검토 한 건을 쌓는다.

    원래 AI 예측은 건드리지 않는다. 나중에 모델 성능을 되짚으려면 AI 가 원래
    뭐라고 했는지가 남아 있어야 한다. 검토가 끝났으므로 대기열에서만 내린다.
    """
    session.add(ReviewResult(wafer_id=wafer.wafer_id, final_class=label,
                             reviewer_id=reviewer_id, review_memo=memo))
    wafer.requires_human_review = False
    session.add(wafer)
    session.flush()


@router.post('/records/{wafer_id}/review', response_model=WaferDetail)
def review(wafer_id: str, body: ReviewRequest,
           user: User = Depends(require_engineer),
           session: Session = Depends(get_session)):
    """수동 라벨링 — UIUX 문서의 드롭다운 경로."""
    wafer = session.get(WaferResult, wafer_id)
    if wafer is None:
        raise HTTPException(404, '기록이 없습니다')
    _record_review(session, wafer, body.label, user.employee_id, body.memo)
    return _detail(session, wafer_id)


@router.post('/records/{wafer_id}/approve', response_model=WaferDetail)
def approve(wafer_id: str, body: ApproveRequest | None = None,
            user: User = Depends(require_engineer),
            session: Session = Depends(get_session)):
    """AI 순위를 그대로 확정 — UIUX 문서의 '1순위 승인' 대형 버튼과 '2순위 수정' 링크.

    클라이언트가 클래스명을 다시 보내지 않아도 되도록 서버가 확률에서 직접 고른다.
    화면에 보이는 값과 저장되는 값이 어긋날 여지를 없앤다.
    """
    wafer = session.get(WaferResult, wafer_id)
    if wafer is None:
        raise HTTPException(404, '기록이 없습니다')

    rank = (body.rank if body else 1) or 1
    ordered = sorted(wafer.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    if rank > len(ordered):
        raise HTTPException(422, f'{rank}순위가 없습니다')

    _record_review(session, wafer, ordered[rank - 1][0], user.employee_id,
                   body.memo if body else '')
    return _detail(session, wafer_id)


@router.get('/records/{wafer_id}/heatmap')
def heatmap(request: Request, wafer_id: str,
            class_name: str | None = Query(None, description='생략하면 AI 1순위'),
            _: User = Depends(current_user),
            session: Session = Depends(get_session)):
    """Grad-CAM 히트맵 PNG.

    지연 생성한다(ERD·플로우차트의 Lazy Eval). 실제로 열어보는 건 검토 대상
    5% 남짓이라 전부 미리 만들면 서버가 낭비된다. 한 번 만든 뒤에는 디스크에서 낸다.
    """
    wafer = session.get(WaferResult, wafer_id)
    if wafer is None:
        raise HTTPException(404, '기록이 없습니다')
    if class_name is not None and class_name not in wafer.probabilities:
        raise HTTPException(422, f'알 수 없는 클래스입니다: {class_name}')

    service = request.app.state.heatmaps
    target = class_name or top_class(wafer.probabilities)
    try:
        path = service.generate(wafer_id, np.asarray(wafer.wafer_map, dtype=np.uint8),
                                target)
    except Exception as error:
        raise HTTPException(500, f'히트맵 생성에 실패했습니다: {error}') from error

    # ERD 의 heatmap_path — 1순위 히트맵만 기록한다.
    if class_name is None and wafer.heatmap_path != str(path):
        wafer.heatmap_path = str(path)
        session.add(wafer)
        session.flush()

    return FileResponse(path, media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=3600'})
