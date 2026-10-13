"""AI 모델 관리 — 배포 이력과 재학습 작업 (UIUX 문서 화면 5).

조회는 수석 엔지니어 이상, 재학습 요청·학습 데이터 내려받기·실패 처리는 관리자만.
학습 데이터에는 생산 웨이퍼 맵과 검토자 사번이 들어 있어 관리자로 묶는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from waferai import retraining
from waferai.auth import get_session, require_admin, require_senior
from waferai.models import AiModel, RetrainJob, User
from waferai.schemas import AiModelOut, FailRequest, RetrainJobOut, RetrainOverview

router = APIRouter(prefix='/api/models', tags=['models'])


def _job_or_404(session: Session, job_id: str) -> RetrainJob:
    job = session.get(RetrainJob, job_id)
    if job is None:
        raise HTTPException(404, '재학습 작업이 없습니다')
    return job


@router.get('', response_model=list[AiModelOut])
def list_models(session: Session = Depends(get_session), _: User = Depends(require_senior)):
    return list(session.execute(
        select(AiModel).order_by(AiModel.is_active.desc(), AiModel.deployed_at.desc())).scalars())


@router.get('/retrain', response_model=RetrainOverview)
def overview(request: Request, session: Session = Depends(get_session),
             _: User = Depends(require_senior)):
    state = retraining.progress(session, request.app.state.retrain_threshold)
    active = retraining.active_job(session)
    completed = retraining.last_completed(session)
    return RetrainOverview(
        **state,
        active_job=RetrainJobOut.model_validate(active) if active else None,
        last_completed=RetrainJobOut.model_validate(completed) if completed else None)


@router.get('/retrain/jobs', response_model=list[RetrainJobOut])
def list_jobs(session: Session = Depends(get_session), _: User = Depends(require_senior)):
    return list(session.execute(
        select(RetrainJob).order_by(RetrainJob.created_at.desc()).limit(100)).scalars())


@router.post('/retrain', response_model=RetrainJobOut, status_code=201)
def request_retrain(request: Request, session: Session = Depends(get_session),
                    admin: User = Depends(require_admin)):
    """관리자 수동 요청. 기준(500건)에 못 미쳐도 만들 수 있다."""
    if retraining.active_job(session) is not None:
        raise HTTPException(409, '이미 진행 중인 재학습 작업이 있습니다')
    count = retraining.progress(session, request.app.state.retrain_threshold)['new_reviews']
    if count == 0:
        raise HTTPException(422, '직전 재학습 이후 새로 검토된 웨이퍼가 없습니다')
    return retraining.create_job(session, admin.employee_id, count)


@router.get('/retrain/jobs/{job_id}/dataset')
def download_dataset(job_id: str, session: Session = Depends(get_session),
                     _: User = Depends(require_admin)):
    """학습 데이터(.npz). 내려받는 순간 작업은 '학습 중'이 된다."""
    job = _job_or_404(session, job_id)
    if job.status not in retraining.ACTIVE_STATES:
        raise HTTPException(409, f'{job.status} 상태의 작업은 데이터를 내려받을 수 없습니다')
    payload = retraining.export_dataset(session, job)
    retraining.mark_running(session, job)
    return Response(payload, media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="waferai-reviews-{job_id[:8]}.npz"',
        'Cache-Control': 'no-store'})


@router.post('/retrain/jobs/{job_id}/fail', response_model=RetrainJobOut)
def fail_job(job_id: str, body: FailRequest, session: Session = Depends(get_session),
             _: User = Depends(require_admin)):
    """학습이 실패했거나 새 모델이 승격 기준을 넘지 못했을 때."""
    job = _job_or_404(session, job_id)
    if job.status not in retraining.ACTIVE_STATES:
        raise HTTPException(409, f'이미 끝난 작업입니다 ({job.status})')
    retraining.mark_failed(session, job, body.note)
    return job
