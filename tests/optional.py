"""개발 의존성(requirements-dev.txt)에만 있는 모듈을 테스트에서 불러온다.

로컬에서는 없으면 건너뛴다. 하지만 CI(환경변수 CI 가 있을 때 — GitHub Actions 가 설정한다)에서는
오류로 만든다. requirements-dev.txt 에서 docker 가 빠져, .env · 가중치가 이미지에 섞이는지 보는
보안 테스트가 CI 에서 조용히 건너뛰어지고도 초록불이 났던 일이 있었다.

테스트 공용 헬퍼(conftest)와 달리 무거운 모듈을 불러오지 않는다. 프론트엔드 CI 작업이 PyYAML
만 깔고 tests.test_deploy 를 돌리기 때문이다.
"""
from __future__ import annotations

import importlib
import os
import unittest


def optional_dependency(module: str):
    try:
        return importlib.import_module(module)
    except ImportError:
        if os.environ.get('CI'):
            raise
        raise unittest.SkipTest(f'{module} 가 없습니다 (requirements-dev.txt)') from None
