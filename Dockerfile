# WaferAI API 이미지.
#   빌드: deploy/compose.yaml 이 부른다 (docker compose up --build)
#
# 모델 가중치는 이미지에 넣지 않는다. 100MB 가 넘는 파일을 넣으면 이미지가 무거워지고,
# 가중치를 바꿀 때마다 다시 빌드해야 한다. 실행 시 ../models 를 읽기 전용으로 붙인다.

# ── 1단계: 의존성 설치 ─────────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# torch / torchvision 을 CPU 전용 인덱스에서 먼저 받는다. 순서가 중요하다.
# PyPI 기본 휠은 CUDA 라이브러리를 수 GB 끌고 오는데, 이 서버에는 GPU 가 없다.
# 먼저 깔아두면 아래 requirements.txt 설치가 이미 만족된 것으로 보고 건너뛴다.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ── 2단계: 실행 이미지 ─────────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=deps /opt/venv /opt/venv

# 루트로 돌리지 않는다. 컨테이너가 뚫려도 피해 범위를 줄인다.
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin waferai

WORKDIR /app
COPY --chown=waferai:waferai waferai/ waferai/
COPY --chown=waferai:waferai alembic/ alembic/
COPY --chown=waferai:waferai alembic.ini ./
# 서버에서 쓰는 운영 스크립트만 넣는다. 나머지는 개발 의존성이 필요하다.
COPY --chown=waferai:waferai scripts/__init__.py scripts/create_user.py scripts/benchmark.py scripts/
COPY --chown=waferai:waferai deploy/entrypoint.sh /usr/local/bin/entrypoint.sh

# 히트맵 저장 위치. 이름 있는 볼륨은 처음 붙을 때 이 디렉터리의 소유자를 물려받으므로,
# 여기서 만들어 두지 않으면 볼륨이 root 소유가 되어 히트맵을 쓰지 못한다.
RUN mkdir -p /app/data/heatmaps /app/models \
    && chown -R waferai:waferai /app/data \
    && chmod 0755 /usr/local/bin/entrypoint.sh

USER waferai

# 공유 라이브러리가 빠졌으면 실행할 때가 아니라 빌드할 때 실패하게 한다.
# slim 이미지는 시스템 라이브러리가 적어서, 휠이 기대하는 .so 가 없으면 import 에서 터진다.
# waferai.server 까지 불러 앱 조립 단계의 import 오류도 여기서 잡는다
# (모델은 기동 시점에 올리므로 빌드 중에는 로드되지 않는다).
RUN python -W ignore -c "import cv2, onnxruntime, torch, timm, psycopg, bcrypt, waferai.server"

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# 워커는 1개. 워커마다 모델이 메모리에 따로 올라가므로, 늘리면 메모리가 배로 든다.
# 동기 엔드포인트는 uvicorn 스레드풀에서 돌아 동시 요청은 처리된다.
# api 포트는 밖으로 열지 않고 Nginx 만 접근하므로 전달 헤더를 모두 신뢰해도 된다.
CMD ["uvicorn", "waferai.server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
