"""최종 코드 정리본 — 소스 압축 파일, 코드 구성 안내서, 전체 코드 목록을 한 폴더에 만든다.

    python3 -m scripts.build_code_package                 # 가장 최근 태그 기준
    python3 -m scripts.build_code_package --ref v1.0.1    # 특정 태그 · 커밋 기준

결과 (기본 위치: 저장소 옆 WaferAI_최종코드_<태그>/)
    WaferAI_<태그>_소스코드.zip      git archive — 저장소에 올라간 파일 전부 (모델 · 데이터 · .env 제외)
    WaferAI_소스코드_구성.pdf        폴더 · 파일별 역할, 실행 · 검증 방법, 빠진 것과 받는 곳
    WaferAI_소스코드_목록.pdf        애플리케이션 · 학습 · 배포 · 테스트 코드 전문 (줄 번호 포함)
    SHA256SUMS.txt                   위 세 파일의 해시

파일 내용은 작업 폴더가 아니라 git 의 해당 시점(--ref)에서 읽는다. 그래서 정리본은 태그와 정확히
같고, 작업 중인 변경이 섞이지 않는다. 파일 설명은 각 파일 첫머리의 설명문(docstring · 주석)에서
뽑는다 — 코드와 설명이 따로 놀지 않게 하려는 것이다.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
import subprocess
from collections import OrderedDict
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle, XPreformatted)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent

FONT, FONT_PATH = 'AppleGothic', '/System/Library/Fonts/Supplemental/AppleGothic.ttf'
MONO, MONO_PATH = 'Menlo', '/System/Library/Fonts/Menlo.ttc'
for name, path, extra in ((FONT, FONT_PATH, {}), (MONO, MONO_PATH, {'subfontIndex': 0})):
    if not Path(path).is_file():
        raise SystemExit(f'글꼴을 찾을 수 없습니다: {path}')
    pdfmetrics.registerFont(TTFont(name, path, **extra))

BRAND = colors.HexColor('#6D28D9')
INK = colors.HexColor('#0F172A')
MUTED = colors.HexColor('#64748B')
LINE = colors.HexColor('#CBD5E1')
PANEL = colors.HexColor('#F1F5F9')


def style(name, size, color=INK, **kw):
    kw.setdefault('leading', size * 1.45)
    return ParagraphStyle(name, fontName=FONT, fontSize=size, textColor=color, **kw)


S = {
    'title': style('t', 24, alignment=TA_CENTER, spaceAfter=6),
    'subtitle': style('st', 11, MUTED, alignment=TA_CENTER, spaceAfter=2),
    'h1': style('h1', 15, BRAND, spaceBefore=12, spaceAfter=7),
    'h2': style('h2', 11.5, spaceBefore=9, spaceAfter=5),
    'body': style('b', 9.5, spaceAfter=6),
    'note': style('n', 8.5, MUTED, spaceAfter=6),
    'cell': style('c', 8.2, spaceAfter=0),
    'cellhead': style('ch', 8.2, colors.white, spaceAfter=0),
    'file': style('f', 10.5, BRAND, spaceBefore=4, spaceAfter=3),
    'filemeta': style('fm', 8, MUTED, spaceAfter=4),
    'toc1': style('toc1', 9.5, BRAND, spaceBefore=6),
    'toc2': style('toc2', 8, leftIndent=10, leading=11),
}
CODE = ParagraphStyle('code', fontName=MONO, fontSize=6.6, leading=8.4, textColor=INK)


# ── git 에서 읽기 ───────────────────────────────────────────────────────────

def git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True).stdout


def tracked(ref: str) -> list[str]:
    return [line for line in git('ls-tree', '-r', '--name-only', '-z', ref).split('\0') if line]


def read(ref: str, path: str) -> str | None:
    data = git_bytes('show', f'{ref}:{path}')
    if b'\0' in data[:4096]:
        return None                                   # 바이너리
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


# ── 파일 설명 ───────────────────────────────────────────────────────────────

#: 첫머리 설명문이 없는 파일 · 코드가 아닌 파일
MANUAL = {
    'README.md': '기술 문서 — 설계 결정과 근거, 실측 결과, 한계',
    'Dockerfile': 'API 서버 이미지 (CPU torch · 비 root 사용자 · 빌드 때 import 확인)',
    '.dockerignore': '이미지에 넣지 않을 파일 (.env · 모델 · 데이터 · 캐시)',
    '.env.example': '로컬 개발용 환경변수 예시',
    '.gitignore': '저장소에 올리지 않을 파일 (모델 · 데이터 · .env · 백업)',
    'alembic.ini': 'DB 마이그레이션 설정',
    'requirements.txt': '서버 실행에 필요한 파이썬 패키지',
    'requirements-dev.txt': '개발 · 테스트용 추가 패키지',
    'training_reference.py': '1학기 Colab 학습 코드 원본 — 하이퍼파라미터 기준',
    'notebooks/retrain_colab.ipynb': 'Colab GPU 재학습 노트북 (번들 재조립 · 학습 · 승격)',
    '.github/workflows/ci.yml': 'GitHub Actions — 백엔드 테스트 2종 DB · 프론트 빌드 · 배포 구성 검증',
    '.claude/launch.json': '개발 미리보기 서버 실행 설정',
    'waferai/__init__.py': '백엔드 패키지',
    'scripts/__init__.py': '스크립트 패키지',
    'frontend/src/main.jsx': '화면 진입점 — 라우터와 로그인 상태 제공자를 붙인다',
    'frontend/src/App.jsx': '화면 라우팅과 로그인 문지기 (권한 · 임시 비밀번호 상태)',
    'frontend/src/pages/Login.jsx': '로그인 화면',
    'frontend/package.json': '화면 의존성과 명령 (dev · build · lint)',
    'frontend/package-lock.json': '화면 의존성 고정 버전',
    'frontend/vite.config.js': '개발 서버 설정 — /api 를 백엔드로 넘긴다',
    'frontend/index.html': '화면 HTML 틀',
    'frontend/Dockerfile': '화면 이미지 — 빌드 후 Nginx 로 제공',
    'frontend/.dockerignore': '화면 이미지에서 뺄 파일',
    'frontend/eslint.config.js': '화면 lint 설정',
    'frontend/.oxlintrc.json': '화면 lint 규칙',
    'frontend/src/index.css': '색 토큰과 공통 스타일 (UIUX 문서 §5)',
    'tests/test_auth.py': '인증 · 계정 — 로그인, 가입 승인, 비밀번호 규칙 · 초기화, 잠금, 세션 무효화',
    'tests/test_decision.py': '판정 로직의 경계값과 임계값 검증',
    'tests/test_heatmap_api.py': '히트맵 API — 지연 생성, 캐시, 2순위 클래스',
    'tests/test_image_adapter.py': '이미지 입력 — 색 복원, 색상표, 거부, 축소',
    'tests/test_server.py': 'API 전반 — 업로드 · 판정 · 검토 · 임계값 · 권한',
    'deploy/nginx/default.conf': 'Nginx HTTP 설정 — 정적 파일, /api 프록시, 로그인 속도 제한',
    'deploy/nginx/https.conf.example': 'Nginx HTTPS 설정 예시 (DOMAIN 을 바꿔 https.conf 로 쓴다)',
    'deploy/nginx/security-headers.conf': '보안 헤더 (CSP · X-Frame-Options · nosniff 등)',
    'deploy/compose.yaml': 'Docker Compose — db · api · web · backup 네 서비스',
    'deploy/compose.https.yaml': 'HTTPS 전환용 덧씌움 설정',
    'deploy/.env.example': '운영 환경변수 예시 (비밀값은 서버에서 새로 만든다)',
    'deploy/README.md': '운영 설명서 — 설치, HTTPS, 백업, 업데이트, 경고, 문제 해결',
    'docs/calibration_report.json': '판정 측정 원본 — 보정 · 판정 기준 · 입력 감지 · 색상표',
    'docs/WaferAI_DB_schema_postgresql.sql': 'DB 스키마 SQL (마이그레이션 head 기준)',
    'samples/manifest.json': '점검용 실제 웨이퍼 12벌의 정답 · 기대 경로',
}

SHELL_COMMENT = re.compile(r'^#(?!!)\s?(.*)$')


def describe(path: str, text: str | None) -> str:
    if path in MANUAL:
        return MANUAL[path]
    if text is None:
        return ''
    if path.endswith('.py'):
        try:
            doc = ast.get_docstring(ast.parse(text))
        except SyntaxError:
            doc = None
        if doc:
            return doc.strip().split('\n')[0].strip().rstrip('.')
    if path.endswith(('.js', '.jsx')):
        match = re.match(r'\s*/\*\*(.*?)\*/', text, re.S)
        if match:
            lines = [re.sub(r'^\s*\*\s?', '', line).strip() for line in match.group(1).split('\n')]
            lines = [line for line in lines if line]
            return lines[0].rstrip('.') if lines else ''
    if path.endswith(('.sh', '.yaml', '.yml', '.conf')) or path.endswith('.example'):
        for line in text.split('\n')[:6]:
            match = SHELL_COMMENT.match(line.strip())
            if match and match.group(1).strip():
                return match.group(1).strip().rstrip('.')
    if path.startswith('alembic/versions/'):
        return ''
    return ''


# ── 분류 ───────────────────────────────────────────────────────────────────

GROUPS = OrderedDict([
    ('waferai', ('백엔드 (FastAPI)', '판정 · 보정 · 입력 처리 · 인증 · API')),
    ('frontend', ('화면 (React)', '화면 8개와 공통 부품')),
    ('alembic', ('DB 마이그레이션', '스키마 변경 이력 6개')),
    ('deploy', ('배포', 'Docker Compose · Nginx · 백업 · 배포 · 경고 스크립트')),
    ('scripts', ('스크립트', '학습 · 측정 · 운영 도구 · 문서 생성')),
    ('tests', ('자동 테스트', '263건 — SQLite · PostgreSQL 양쪽')),
    ('notebooks', ('노트북', 'Colab 재학습')),
    ('docs', ('문서', '보고서 · 설명서 · 발표 자료 · 측정 결과')),
    ('samples', ('점검 샘플', '실제 웨이퍼 12벌 × 4형식 + 특수 입력')),
    ('', ('최상위', '설치 · 이미지 · CI · 설정')),
])


def group_of(path: str) -> str:
    top = path.split('/')[0]
    if top in GROUPS:
        return top
    return ''


#: 전체 코드 목록에 넣는 파일 (순서대로). 문서 · 샘플 · 생성 보고서 도구는 뺀다.
LISTING_ORDER = [
    ('백엔드 (waferai/)', lambda p: p.startswith('waferai/') and p.endswith('.py')),
    ('DB 마이그레이션 (alembic/)', lambda p: p.startswith('alembic/') and p.endswith('.py')),
    ('화면 (frontend/)', lambda p: p.startswith('frontend/') and p.endswith(('.jsx', '.js', '.css', '.html'))
     and 'package-lock' not in p),
    ('배포 (deploy/ · Dockerfile · CI)', lambda p: (p.startswith('deploy/') and not p.endswith('.md'))
     or p in ('Dockerfile', '.github/workflows/ci.yml', 'requirements.txt', 'requirements-dev.txt',
              'frontend/Dockerfile', 'alembic.ini')),
    ('학습 · 측정 · 운영 스크립트 (scripts/)', lambda p: p.startswith('scripts/') and p.endswith('.py')
     and not re.search(r'scripts/(build_|capture_screens)', p)),
    ('자동 테스트 (tests/)', lambda p: p.startswith('tests/') and p.endswith('.py')),
]


# ── PDF 공통 ───────────────────────────────────────────────────────────────

def P(text, key='body'):
    return Paragraph(text, S[key])


def table(rows, widths, aligns=None):
    data = [[cell if isinstance(cell, Paragraph) else Paragraph(escape(str(cell)) if i else str(cell),
                                                                 S['cellhead' if i == 0 else 'cell'])
             for cell in row] for i, row in enumerate(rows)]
    commands = [('GRID', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
                ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('BACKGROUND', (0, 0), (-1, 0), BRAND),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PANEL])]
    for column, align in (aligns or {}).items():
        commands.append(('ALIGN', (column, 0), (column, -1), align))
    return Table(data, colWidths=widths, style=TableStyle(commands), hAlign='LEFT', repeatRows=1, spaceAfter=7)


def make_footer(label):
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 10 * mm, label)
        canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, str(doc.page))
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.restoreState()
    return footer


def blank(canvas, doc):
    pass


# ── 코드 목록 ──────────────────────────────────────────────────────────────

def mixed(text: str) -> str:
    """한 줄을 XPreformatted 마크업으로 — 한글 등 Menlo 에 없는 글자는 AppleGothic 으로."""
    out, run, run_font = [], [], None
    for ch in text:
        font = MONO if ord(ch) < 0x2600 else FONT
        if font != run_font and run:
            out.append(segment(''.join(run), run_font))
            run = []
        run_font = font
        run.append(ch)
    if run:
        out.append(segment(''.join(run), run_font))
    return ''.join(out)


def segment(text: str, font: str) -> str:
    body = escape(text)
    return body if font == MONO else f'<font name="{font}">{body}</font>'


def width_of(text: str) -> float:
    total = 0.0
    for ch in text:
        font = MONO if ord(ch) < 0x2600 else FONT
        total += pdfmetrics.stringWidth(ch, font, CODE.fontSize)
    return total


def wrap(line: str, limit: float) -> list[str]:
    """너비를 넘는 줄을 글자 단위로 자른다 (이어지는 줄은 ↳ 로 표시)."""
    if width_of(line) <= limit:
        return [line]
    pieces, current = [], ''
    for ch in line:
        if width_of(current + ch) > limit:
            pieces.append(current)
            current = '    '
        current += ch
    pieces.append(current)
    return pieces


class ListingDoc(BaseDocTemplate):
    """목차에 파일을 싣고, PDF 책갈피도 만든다."""

    def afterFlowable(self, flowable):
        kind = getattr(flowable, '_toc', None)
        if not kind:
            return
        level, text, key = kind
        self.notify('TOCEntry', (level, text, self.page, key))
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level == 0)


def tagged(flowable, level, text, key):
    flowable._toc = (level, text, key)
    return flowable


def build_listing(ref: str, files: list[str], out: Path, meta: dict) -> tuple[int, int]:
    width = A4[0] - 30 * mm
    limit = width - width_of('0000  ')
    story = [Spacer(1, 50 * mm), P('WaferAI 소스코드 목록', 'title'),
             P(f"{meta['ref']} · 커밋 {meta['commit']} · {meta['date']}", 'subtitle'),
             Spacer(1, 6 * mm),
             P('애플리케이션 · 학습 · 배포 · 테스트 코드 전문이다. 줄 번호는 파일 안의 실제 줄 번호다. '
               '문서 · 샘플 데이터 · 보고서 생성 도구는 소스 압축 파일에만 있다. 너비를 넘는 줄은 '
               '다음 줄에 이어 적었다(번호 없음).', 'note'),
             NextPageTemplate('body'), PageBreak(), P('목차', 'h1')]
    toc = TableOfContents()
    toc.levelStyles = [S['toc1'], S['toc2']]
    story += [toc, PageBreak()]

    total_lines = listed = 0
    for section_index, (title, keep) in enumerate(LISTING_ORDER):
        chosen = [f for f in files if keep(f)]
        chosen = [f for f in chosen if read(ref, f) is not None]
        if not chosen:
            continue
        story.append(tagged(P(title, 'h1'), 0, title, f's{section_index}'))
        for file_index, path in enumerate(chosen):
            text = read(ref, path)
            lines = text.rstrip('\n').split('\n')
            total_lines += len(lines)
            listed += 1
            key = f's{section_index}f{file_index}'
            story.append(tagged(P(escape(path), 'file'), 1, f'{path}  ({len(lines)}줄)', key))
            desc = describe(path, text)
            story.append(P(escape(f"{len(lines)}줄" + (f' · {desc}' if desc else '')), 'filemeta'))
            rendered = []
            for number, line in enumerate(lines, 1):
                for part_index, part in enumerate(wrap(line.replace('\t', '    '), limit)):
                    prefix = f'{number:4d}  ' if part_index == 0 else '   ↳  '
                    rendered.append(f'<font color="#94A3B8">{prefix}</font>' + mixed(part))
            # 한 덩어리가 너무 크면 쪽 나눔이 느려 60줄씩 나눈다
            for start in range(0, len(rendered), 60):
                story.append(XPreformatted('\n'.join(rendered[start:start + 60]), CODE))
            story.append(Spacer(1, 4 * mm))

    doc = ListingDoc(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                     topMargin=15 * mm, bottomMargin=20 * mm, title='WaferAI 소스코드 목록',
                     author='팀 Wafer-Eye')
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
    doc.addPageTemplates([PageTemplate(id='cover', frames=[frame], onPage=blank),
                          PageTemplate(id='body', frames=[frame],
                                       onPage=make_footer(f"WaferAI 소스코드 목록 · {meta['ref']}"))])
    doc.multiBuild(story)
    return listed, total_lines


# ── 구성 안내서 ─────────────────────────────────────────────────────────────

def count_lines(text: str | None) -> int:
    return len(text.rstrip('\n').split('\n')) if text else 0


def build_guide(ref: str, files: list[str], out: Path, meta: dict, listing: tuple[int, int]) -> None:
    info = {}
    for path in files:
        text = read(ref, path)
        info[path] = (count_lines(text), describe(path, text), text is None)

    story = [Spacer(1, 45 * mm), P('WaferAI 소스코드 구성', 'title'),
             P('웨이퍼 결함 분류 서비스 · 최종 코드', 'subtitle'),
             P(f"{meta['ref']} · 커밋 {meta['commit']} · {meta['date']}", 'subtitle'), Spacer(1, 12 * mm)]
    story.append(table([
        ['항목', '내용'],
        ['저장소', 'GitHub foreverami/WaferAI (비공개)'],
        ['기준', f"태그 {meta['ref']} — 커밋 {meta['commit']} ({meta['commit_date']})"],
        ['함께 주는 파일', f"WaferAI_{meta['ref']}_소스코드.zip · WaferAI_소스코드_목록.pdf · SHA256SUMS.txt"],
        ['규모', f"파일 {len(files)}개 · 코드 목록에 실은 파일 {listing[0]}개 · {listing[1]:,}줄"],
        ['검증', '이 커밋의 기능은 v1.0 과 같다 — 자동 테스트 263건(SQLite · PostgreSQL), 프론트 빌드, 배포 구성 CI 통과'],
    ], [32 * mm, 128 * mm]))
    story += [NextPageTemplate('body'), PageBreak()]

    # 1. 개요
    story.append(P('1. 폴더 구성', 'h1'))
    rows = [['폴더', '내용', '파일', '줄']]
    for key, (title, summary) in GROUPS.items():
        members = [f for f in files if group_of(f) == key]
        if not members:
            continue
        lines = sum(info[f][0] for f in members if not info[f][2])
        rows.append([(key + '/') if key else '(최상위)', f'{title} — {summary}', str(len(members)), f'{lines:,}'])
    story.append(table(rows, [24 * mm, 104 * mm, 12 * mm, 20 * mm], aligns={2: 'RIGHT', 3: 'RIGHT'}))
    story.append(P('줄 수는 텍스트 파일만 센다. docs/ · samples/ 의 PDF · 이미지 · npy 는 0 으로 셌다.', 'note'))

    story.append(P('구조 한눈에', 'h2'))
    tree = [
        'WaferAI/',
        '├── waferai/            백엔드 — server.py(앱) · routers/(API) · decision.py(판정) · inference.py(추론)',
        '│                       calibration.py(보정) · ood.py(입력 감지) · image_adapter.py(이미지) · auth.py · models.py',
        '├── frontend/src/       화면 — pages/(화면) · components/(공통) · api.js(API 호출)',
        '├── alembic/versions/   DB 마이그레이션 6개',
        '├── deploy/             compose.yaml · nginx/ · backup-loop.sh · deploy_update.sh · azure_alerts.sh',
        '├── scripts/            train.py · calibrate.py · acceptance.py · export_onnx.py · promote_model.py …',
        '├── tests/              자동 테스트 263건',
        '├── samples/            점검 · 시연용 실제 웨이퍼 파일',
        '├── docs/               보고서 · 설명서 · 발표 자료 · 측정 결과 · DB 스키마',
        '└── Dockerfile · requirements.txt · .github/workflows/ci.yml · README.md',
    ]
    story.append(XPreformatted('\n'.join(mixed(line) for line in tree),
                               ParagraphStyle('tree', parent=CODE, fontSize=7.2, leading=10.5)))

    # 2. 실행
    story.append(P('2. 실행 · 검증 방법', 'h1'))
    story.append(table([
        ['목적', '명령'],
        ['의존성 설치', 'pip install -r requirements-dev.txt · npm --prefix frontend ci'],
        ['로컬 미리보기', 'python3 -m scripts.serve_preview  +  npm --prefix frontend run dev  → localhost:5173'],
        ['자동 테스트', 'python3 -m unittest discover -s tests -t .'],
        ['화면 검사 · 빌드', 'npm --prefix frontend run lint · npm --prefix frontend run build'],
        ['운영 배포 (처음)', 'deploy/README.md "처음 배포" — cd deploy && docker compose up -d --build'],
        ['운영 업데이트', 'sh deploy/deploy_update.sh'],
        ['전 기능 점검', 'ACC_ENG=ID:PW ACC_SEN=ID:PW ACC_ADM=ID:PW python3 -m scripts.acceptance --base <주소>'],
        ['판정 측정', 'python3 -m scripts.calibrate (결과 docs/calibration_report.json)'],
        ['재학습', 'python3 -m scripts.train → scripts.promote_model --apply (GPU 필요, README "재학습")'],
        ['DB 스키마 문서', 'python3 -m scripts.export_schema_sql'],
    ], [30 * mm, 130 * mm]))

    # 3. 빠진 것
    story.append(P('3. 압축 파일에 없는 것과 받는 곳', 'h1'))
    story.append(table([
        ['무엇', '왜 없나', '받는 곳'],
        ['모델 가중치 (.pth 106MB · .onnx 113MB)', '용량 — git 에 올리지 않는다',
         'models/ (개발 장비 · 서버). 원본은 README "원본" 의 Drive 링크. 보정값을 심은 체크포인트 해시 9f11749a764f'],
        ['학습 데이터 (LSWMD.pkl 2.1GB)', '용량', 'README "원본" 의 Drive 링크 → scripts/prepare_training_data.py'],
        ['.env · deploy/.env', '비밀값 (DB 비밀번호 · 서명 키)', '예시 파일(.env.example)을 복사해 새로 만든다'],
        ['deploy/nginx/https.conf', '도메인이 들어간 서버 전용 파일', 'https.conf.example 에서 만든다 (deploy_update.sh 가 자동)'],
        ['node_modules · 빌드 결과', '설치 · 빌드로 다시 만든다', 'npm ci · npm run build'],
    ], [44 * mm, 42 * mm, 74 * mm]))

    # 4. 파일별 역할
    story.append(PageBreak())
    story.append(P('4. 파일별 역할', 'h1'))
    story.append(P('설명은 각 파일 첫머리의 설명문에서 뽑았다. samples/ 는 같은 웨이퍼의 형식별 파일이라 묶어 적었다.', 'note'))
    for key, (title, summary) in GROUPS.items():
        members = [f for f in files if group_of(f) == key]
        if not members:
            continue
        story.append(P(f"{(key + '/') if key else '(최상위)'} — {title}", 'h2'))
        if key == 'samples':
            wafers = sorted({Path(f).stem for f in members if Path(f).suffix in ('.npy', '.csv', '.json', '.png')
                             and not Path(f).name.startswith(('bad_', 'oos_', 'palette_', 'manifest'))})
            rows = [['파일', '내용'],
                    ['manifest.json', MANUAL['samples/manifest.json']],
                    [f'실제 웨이퍼 {len(wafers)}벌 × .npy .csv .json .png',
                     '테스트 분할에서 고른 웨이퍼 — ' + ', '.join(wafers)],
                    ['palette_viridis.png', 'viridis 색상표로 그린 웨이퍼 — 학습 색으로 바꿔 읽어야 한다'],
                    ['oos_checkerboard.json', '웨이퍼가 아닌 체크무늬 — 판정 불가로 가야 한다'],
                    ['bad_photo_like.png · bad_not_an_image.png · bad_values.json', '거절돼야 하는 입력'],
                    ['bad_huge_900px.png', '큰 그림 — 받되 축소 경고']]
            story.append(table(rows, [62 * mm, 98 * mm]))
            continue
        rows = [['파일', '줄', '역할']]
        for path in members:
            lines, desc, binary = info[path]
            shown = path[len(key) + 1:] if key else path
            rows.append([shown, '' if binary else str(lines), desc or ('(바이너리)' if binary else '')])
        story.append(table(rows, [56 * mm, 12 * mm, 92 * mm], aligns={1: 'RIGHT'}))

    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                          topMargin=20 * mm, bottomMargin=22 * mm, title='WaferAI 소스코드 구성',
                          author='팀 Wafer-Eye')
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
    doc.addPageTemplates([PageTemplate(id='cover', frames=[frame], onPage=blank),
                          PageTemplate(id='body', frames=[frame],
                                       onPage=make_footer(f"WaferAI 소스코드 구성 · {meta['ref']}"))])
    doc.build(story)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description='최종 코드 정리본 만들기')
    parser.add_argument('--ref', help='태그 또는 커밋 (기본: 가장 최근 태그)')
    parser.add_argument('--out', help='결과 폴더 (기본: 저장소 옆 WaferAI_최종코드_<태그>)')
    args = parser.parse_args()

    ref = args.ref or git('describe', '--tags', '--abbrev=0').strip()
    commit = git('rev-parse', '--short', f'{ref}^{{commit}}').strip()
    meta = {'ref': ref, 'commit': commit, 'date': date.today().isoformat(),
            'commit_date': git('log', '-1', '--format=%cs', ref).strip()}
    out = Path(args.out) if args.out else ROOT.parent / f'WaferAI_최종코드_{ref}'
    out.mkdir(parents=True, exist_ok=True)
    files = tracked(ref)

    archive = out / f'WaferAI_{ref}_소스코드.zip'
    archive.write_bytes(git_bytes('archive', '--format=zip', f'--prefix=WaferAI/', ref))
    listing_pdf = out / 'WaferAI_소스코드_목록.pdf'
    listing = build_listing(ref, files, listing_pdf, meta)
    guide_pdf = out / 'WaferAI_소스코드_구성.pdf'
    build_guide(ref, files, guide_pdf, meta, listing)

    sums = [f'{sha256(p)}  {p.name}' for p in (archive, guide_pdf, listing_pdf)]
    (out / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n')
    print(f'{out}')
    for p in (archive, guide_pdf, listing_pdf):
        print(f'  {p.name}  {p.stat().st_size / 1024 ** 2:.1f} MB')
    print(f'  코드 목록: 파일 {listing[0]}개 · {listing[1]:,}줄')


if __name__ == '__main__':
    main()
