"""성능 추이 · 서버 상태 · 감사 기록.

성능 추이(UIUX 화면 5 의 마지막 남은 부분)는 수석 엔지니어 이상, 서버 상태와 감사 기록은
관리자만 본다. 서버 상태는 따로 감시 도구가 없는 이 배포에서 디스크와 백업을 화면으로 확인하는
최소한의 모니터링이다.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from waferai.auth import get_session, require_admin, require_senior
from waferai.models import AuditEvent, ReviewResult, User, WaferResult, utcnow
from waferai.schemas import AuditEventOut, SystemHealth, TrendOut, TrendWeek

router = APIRouter(prefix='/api', tags=['system'])

ROOT = Path(__file__).resolve().parents[2]


def _week_start(moment: datetime) -> str:
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    monday = (moment - timedelta(days=moment.weekday())).date()
    return monday.isoformat()


@router.get('/stats/trend', response_model=TrendOut)
def trend(session: Session = Depends(get_session), _: User = Depends(require_senior),
          weeks: int = Query(12, ge=1, le=104)):
    """주별 판정 경로와, 사람이 검토한 건 중 AI 최종 판정과 같았던 비율."""
    since = utcnow() - timedelta(weeks=weeks)
    rows = session.execute(
        select(WaferResult).options(selectinload(WaferResult.reviews))
        .where(WaferResult.processed_at >= since)).scalars()

    buckets: dict[str, dict] = {}
    for row in rows:
        key = _week_start(row.processed_at)
        b = buckets.setdefault(key, {'week': key, 'uploads': 0, 'auto_pass': 0, 'rule_base': 0,
                                     'review_needed': 0, 'out_of_scope': 0, 'reviewed': 0,
                                     'ai_agreed': 0})
        b['uploads'] += 1
        path = row.decision_path
        if path == 'AUTO_PASS':
            b['auto_pass'] += 1
        elif path.startswith('RULE_BASE'):
            b['rule_base'] += 1
        elif path == 'OUT_OF_SCOPE':
            b['out_of_scope'] += 1
        else:
            b['review_needed'] += 1
        review = row.latest_review
        if review is not None:
            b['reviewed'] += 1
            b['ai_agreed'] += review.final_class == row.final_class
    return TrendOut(weeks=[TrendWeek(**buckets[k]) for k in sorted(buckets)])


def _backups(directory: str | None) -> tuple[int, datetime | None, float | None]:
    if not directory:
        return 0, None, None
    folder = Path(directory)
    if not folder.is_absolute():
        folder = ROOT / folder
    files = sorted(folder.glob('waferai-*.dump'), key=lambda f: f.stat().st_mtime) if folder.is_dir() else []
    if not files:
        return 0, None, None
    last = files[-1].stat()
    return (len(files), datetime.fromtimestamp(last.st_mtime, tz=timezone.utc),
            round(last.st_size / 1024 ** 2, 2))


@router.get('/system/health', response_model=SystemHealth)
def health(request: Request, session: Session = Depends(get_session),
           _: User = Depends(require_admin)):
    usage = shutil.disk_usage(ROOT)
    count, last_at, last_mb = _backups(getattr(request.app.state, 'backup_dir', None))
    counts = {
        'wafer_result': session.scalar(select(func.count()).select_from(WaferResult)) or 0,
        'review_result': session.scalar(select(func.count()).select_from(ReviewResult)) or 0,
        'audit_events': session.scalar(select(func.count()).select_from(AuditEvent)) or 0,
    }
    return SystemHealth(disk_total_gb=round(usage.total / 1024 ** 3, 1),
                        disk_free_gb=round(usage.free / 1024 ** 3, 1),
                        database_rows=counts, backups=count, last_backup_at=last_at,
                        last_backup_mb=last_mb,
                        last_backup_age_hours=(round((utcnow() - last_at).total_seconds() / 3600, 1)
                                               if last_at else None),
                        backup_dir=getattr(request.app.state, 'backup_dir', None))


@router.get('/audit', response_model=list[AuditEventOut])
def audit_events(session: Session = Depends(get_session), _: User = Depends(require_admin),
                 limit: int = Query(100, ge=1, le=1000),
                 event: str | None = Query(None, max_length=40, description='접두어 (예: login)'),
                 employee_id: str | None = Query(None, max_length=40)):
    statement = select(AuditEvent).order_by(AuditEvent.event_id.desc()).limit(limit)
    if event:
        statement = statement.where(AuditEvent.event.startswith(event))
    if employee_id:
        statement = statement.where(AuditEvent.employee_id == employee_id)
    return list(session.execute(statement).scalars())
