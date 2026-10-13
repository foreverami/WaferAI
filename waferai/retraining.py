"""재학습 루프 — 검토 라벨 누적 → 작업 생성 → 학습 데이터 내보내기 → 새 모델 등록 시 완료.

기능상세설명서·플로우차트의 "정답 500개 누적 시 재학습" 을 구현한다. 몇 가지를 정했다.

  * "정답 개수" 는 검토가 끝난 웨이퍼 수다. 같은 웨이퍼를 두 번 고쳐도 하나로 센다.
  * 직전에 *완료된* 작업 이후의 검토만 센다. 실패한 작업은 데이터를 쓰지 못했으므로
    그 사이의 검토도 다시 센다.
  * 진행 중(PENDING·RUNNING)인 작업이 있으면 새로 만들지 않는다.
  * 학습 데이터로는 누적 검토 전체를 내보낸다. 기준은 "새로 500개" 지만, 학습에는 많을수록 낫다.
  * 웨이퍼마다 가장 최근 검토를 정답으로 쓴다.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waferai.models import AiModel, RetrainJob, RetrainStatus, ReviewResult, WaferResult, utcnow

AUTO_TRIGGER = 'AUTO_RETRAIN_500'
ACTIVE_STATES = (RetrainStatus.PENDING.value, RetrainStatus.RUNNING.value)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite 는 시간대를 저장하지 않아 naive 로 돌려준다. 비교 전에 UTC 로 맞춘다."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def last_completed(session: Session) -> RetrainJob | None:
    return session.execute(
        select(RetrainJob).where(RetrainJob.status == RetrainStatus.COMPLETED.value)
        .order_by(RetrainJob.review_cutoff.desc()).limit(1)).scalar_one_or_none()


def active_job(session: Session) -> RetrainJob | None:
    return session.execute(
        select(RetrainJob).where(RetrainJob.status.in_(ACTIVE_STATES))
        .order_by(RetrainJob.created_at.desc()).limit(1)).scalar_one_or_none()


def reviewed_since(session: Session, since: datetime) -> int:
    """since 이후에 검토된 서로 다른 웨이퍼 수."""
    return int(session.execute(
        select(func.count(func.distinct(ReviewResult.wafer_id)))
        .where(ReviewResult.reviewed_at > since)).scalar_one())


def progress(session: Session, threshold: int) -> dict:
    completed = last_completed(session)
    since = _aware(completed.review_cutoff) if completed else EPOCH
    count = reviewed_since(session, since)
    return {'threshold': threshold, 'new_reviews': count,
            'ratio': min(count / threshold, 1.0) if threshold else 1.0,
            'since': None if since == EPOCH else since.isoformat()}


def _active_model_id(session: Session) -> int | None:
    return session.execute(select(AiModel.model_id).where(AiModel.is_active.is_(True))
                           .limit(1)).scalar_one_or_none()


def create_job(session: Session, triggered_by: str, new_reviews: int) -> RetrainJob:
    job = RetrainJob(job_id=str(uuid.uuid4()), triggered_by=triggered_by,
                     status=RetrainStatus.PENDING.value, review_cutoff=utcnow(),
                     new_reviews=new_reviews, base_model_id=_active_model_id(session))
    session.add(job)
    session.flush()
    return job


def maybe_trigger(session: Session, threshold: int) -> RetrainJob | None:
    """검토가 기록될 때마다 부른다. 기준을 넘었고 진행 중인 작업이 없으면 작업을 만든다."""
    if threshold <= 0 or active_job(session) is not None:
        return None
    count = progress(session, threshold)['new_reviews']
    if count < threshold:
        return None
    return create_job(session, AUTO_TRIGGER, count)


def labeled_wafers(session: Session, cutoff: datetime) -> list[tuple[WaferResult, ReviewResult]]:
    """cutoff 까지 검토된 웨이퍼와 각 웨이퍼의 가장 최근 검토."""
    latest = (select(ReviewResult.wafer_id, func.max(ReviewResult.review_id).label('review_id'))
              .where(ReviewResult.reviewed_at <= cutoff)
              .group_by(ReviewResult.wafer_id).subquery())
    rows = session.execute(
        select(WaferResult, ReviewResult)
        .join(latest, latest.c.wafer_id == WaferResult.wafer_id)
        .join(ReviewResult, ReviewResult.review_id == latest.c.review_id)
        .order_by(WaferResult.wafer_id)).all()
    return [(wafer, review) for wafer, review in rows]


def export_dataset(session: Session, job: RetrainJob) -> bytes:
    """학습 데이터 (.npz). scripts/train.py --reviews 가 그대로 읽는 형식이다.

    맵 크기가 제각각이라 이어 붙인 배열(flat)과 모양(shapes)으로 담는다.
    """
    pairs = labeled_wafers(session, _aware(job.review_cutoff))
    maps = [np.asarray(wafer.wafer_map, dtype=np.uint8) for wafer, _ in pairs]
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        flat=np.concatenate([m.ravel() for m in maps]) if maps else np.zeros(0, np.uint8),
        shapes=np.array([m.shape for m in maps], dtype=np.int32).reshape(-1, 2),
        labels=np.array([review.final_class for _, review in pairs]),
        ai_predictions=np.array([wafer.final_class for wafer, _ in pairs]),
        wafer_ids=np.array([wafer.wafer_id for wafer, _ in pairs]),
        reviewers=np.array([review.reviewer_id for _, review in pairs]),
        job_id=np.array(job.job_id),
        review_cutoff=np.array(_aware(job.review_cutoff).isoformat()),
    )
    return buffer.getvalue()


def mark_running(session: Session, job: RetrainJob) -> None:
    if job.status == RetrainStatus.PENDING.value:
        job.status = RetrainStatus.RUNNING.value
        job.started_at = utcnow()
        session.add(job)
        session.flush()


def mark_failed(session: Session, job: RetrainJob, note: str) -> None:
    job.status = RetrainStatus.FAILED.value
    job.completed_at = utcnow()
    job.note = note
    session.add(job)
    session.flush()


def complete_running(session: Session, new_model_id: int) -> RetrainJob | None:
    """새 가중치가 등록되면 부른다. 학습 중이던 작업이 있으면 그 결과로 묶어 완료한다."""
    job = session.execute(
        select(RetrainJob).where(RetrainJob.status == RetrainStatus.RUNNING.value)
        .order_by(RetrainJob.started_at.desc()).limit(1)).scalar_one_or_none()
    if job is None:
        return None
    job.status = RetrainStatus.COMPLETED.value
    job.result_model_id = new_model_id
    job.completed_at = utcnow()
    session.add(job)
    session.flush()
    return job
