"""WaferAI Vision API.

Phase 2 범위: 인증·권한, SQLAlchemy 모델, 설정 가능한 임계값.
Grad-CAM 은 Phase 3, React 화면은 Phase 4 에서 붙인다.
"""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import select

from waferai.auth import AuthContext, current_user, get_session
from waferai.backends import CLASSES
from waferai.config import Settings, settings as default_settings
from waferai.db import create_all, create_db_engine, create_session_factory
from waferai.heatmap import HeatmapService
from waferai.inference import Predictor
from waferai.models import AiModel, User
from waferai.routers import admin_routes, auth_routes, wafer_routes

ROOT = Path(__file__).resolve().parent.parent


def _register_model(session_factory, predictor: Predictor, checkpoint: Path) -> int:
    """돌고 있는 모델을 ai_model 에 등록하고 model_id 를 돌려준다.

    파일 SHA-256 으로 식별해, 같은 가중치를 재기동해도 행이 늘지 않는다.
    어떤 예측이 어느 가중치에서 나왔는지 추적하려면 이 연결이 필요하다.
    """
    digest = hashlib.sha256(Path(predictor.backend.source_path).read_bytes()).hexdigest()
    metadata = predictor.metadata

    with session_factory() as session:
        existing = session.execute(
            select(AiModel).where(AiModel.file_sha256 == digest)).scalar_one_or_none()
        if existing:
            # 백엔드가 바뀌었을 수 있으니 최신 상태로 맞춘다.
            existing.backend = predictor.backend.name
            existing.is_active = True
            session.add(existing)
            session.commit()
            return existing.model_id

        # 새 가중치가 올라오면 이전 활성 모델을 내린다(ERD: 동시 1개만 활성).
        for row in session.execute(select(AiModel).where(AiModel.is_active.is_(True))).scalars():
            row.is_active = False
            session.add(row)

        model = AiModel(
            model_name=checkpoint.name, version=f'epoch-{metadata.get("epoch") or "?"}',
            file_sha256=digest, backend=predictor.backend.name,
            val_accuracy=metadata.get('val_acc'), epoch=metadata.get('epoch'),
            is_active=True)
        session.add(model)
        session.commit()
        return model.model_id


def create_app(config: Settings | None = None, *, database_url: str | None = None,
               create_schema: bool = True) -> FastAPI:
    config = config or default_settings
    database_url = database_url or config.database_url

    problems = config.check_production_safety()
    if problems:
        raise RuntimeError('운영 설정에 문제가 있습니다:\n  - ' + '\n  - '.join(problems))

    secret_key = config.resolved_secret_key()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_db_engine(database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        if create_schema:
            # 개발·테스트용. 운영은 `alembic upgrade head` 로 스키마를 만든다.
            create_all(engine)

        app.state.auth = AuthContext(secret_key, config.cookie_name,
                                     config.access_token_minutes)
        app.state.predict_lock = Lock()

        checkpoint = Path(config.checkpoint_path)
        if not checkpoint.is_absolute():
            checkpoint = ROOT / checkpoint
        onnx_path = Path(config.onnx_path)
        if not onnx_path.is_absolute():
            onnx_path = ROOT / onnx_path

        app.state.predictor = Predictor.from_paths(
            checkpoint, onnx_path, config.backend)
        app.state.model_id = _register_model(app.state.session_factory,
                                             app.state.predictor, checkpoint)
        # PyTorch 모델은 첫 히트맵 요청에서 올린다. 아무도 열지 않으면 102MB 를 아낀다.
        app.state.heatmaps = HeatmapService(checkpoint, config.heatmap_dir, config.device)
        try:
            yield
        finally:
            app.state.heatmaps.release()
            engine.dispose()

    app = FastAPI(title='WaferAI Vision API', lifespan=lifespan)
    app.include_router(auth_routes.router)
    app.include_router(wafer_routes.router)
    app.include_router(admin_routes.router)

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'waferai/static/index.html')

    @app.get('/healthz')
    def healthz():
        """인증 없이 접근 가능. 로드밸런서와 Docker 헬스체크가 부른다."""
        return {'status': 'ok', 'backend': app.state.predictor.backend.name}

    @app.get('/api/status')
    def status(_: User = Depends(current_user), session=Depends(get_session)):
        active = session.execute(
            select(AiModel).where(AiModel.is_active.is_(True))).scalar_one_or_none()
        return {
            'model_ready': True,
            'metadata': app.state.predictor.metadata,
            'model_version': active.file_sha256 if active else None,
            'classes': CLASSES,
            'thresholds': wafer_routes.load_thresholds(session).as_dict(),
            'accepted_formats': sorted(wafer_routes.ARRAY_SUFFIXES
                                       | wafer_routes.IMAGE_SUFFIXES),
        }

    return app


app = create_app()
