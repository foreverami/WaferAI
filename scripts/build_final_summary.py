"""최종 결과물 정리본 PDF — 프로젝트가 끝난 시점의 산출물 · 성능 · 검증 · 한계 · 남은 일을 한 권으로.

    python3 -m scripts.build_final_summary      # → docs/WaferAI_최종결과물_정리.pdf

판정 수치는 docs/calibration_report.json 에서 읽고, 나머지는 README · deploy/README.md 의 실측값을
옮긴다. 모양은 build_improvement_report.py 와 같다.
"""
import json

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate,
                                CondPageBreak, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

FONT = 'AppleGothic'
FONT_PATH = '/System/Library/Fonts/Supplemental/AppleGothic.ttf'
if not Path(FONT_PATH).is_file():
    raise SystemExit(f'한글 폰트를 찾을 수 없습니다: {FONT_PATH}')
pdfmetrics.registerFont(TTFont(FONT, FONT_PATH))

BRAND = colors.HexColor('#6D28D9')
GREEN = colors.HexColor('#15803D')
AMBER = colors.HexColor('#B45309')
INK = colors.HexColor('#0F172A')
MUTED = colors.HexColor('#64748B')
LINE = colors.HexColor('#CBD5E1')
PANEL = colors.HexColor('#F1F5F9')

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs/WaferAI_최종결과물_정리.pdf'
REPORT = json.loads((ROOT / 'docs/calibration_report.json').read_text())
UI = ROOT / 'docs/figures/ui'
GRADCAM = ROOT / 'docs/figures/gradcam_examples.png'
URL = 'https://waferai-demo.eastasia.cloudapp.azure.com'

styles = getSampleStyleSheet()


def style(name, size, leading=None, color=INK, space_before=0, space_after=4, **kw):
    return ParagraphStyle(name, parent=styles['Normal'], fontName=FONT, fontSize=size,
                          leading=leading or size * 1.55, textColor=color,
                          spaceBefore=space_before, spaceAfter=space_after, **kw)


S = {
    'title': style('t', 24, space_after=6, alignment=TA_CENTER),
    'subtitle': style('st', 11, color=MUTED, space_after=2, alignment=TA_CENTER),
    'h1': style('h1', 15, color=BRAND, space_before=14, space_after=8),
    'h2': style('h2', 11.5, space_before=10, space_after=5),
    'body': style('b', 9.5, space_after=6),
    'note': style('n', 8.5, color=MUTED, space_after=6),
    'cell': style('c', 8.5, space_after=0),
    'cellhead': style('ch', 8.5, color=colors.white, space_after=0),
    'kpi': style('k', 17, color=BRAND, space_after=0, alignment=TA_CENTER),
    'kpilabel': style('kl', 8.5, color=MUTED, space_after=0, alignment=TA_CENTER),
}
W = 160 * mm


def P(text, key='body'):
    return Paragraph(text, S[key])


def bullet(items, key='body'):
    return [Paragraph(f'•&nbsp;&nbsp;{item}', S[key]) for item in items]


def table(rows, widths, header=True, aligns=None):
    data = []
    for index, row in enumerate(rows):
        key = 'cellhead' if (header and index == 0) else 'cell'
        data.append([cell if isinstance(cell, Paragraph) else Paragraph(str(cell), S[key])
                     for cell in row])
    commands = [
        ('GRID', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    if header:
        commands += [('BACKGROUND', (0, 0), (-1, 0), BRAND),
                     ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PANEL])]
    for column, align in (aligns or {}).items():
        commands.append(('ALIGN', (column, 0), (column, -1), align))
    return Table(data, colWidths=widths, style=TableStyle(commands), hAlign='LEFT',
                 repeatRows=1 if header else 0, spaceAfter=7)


def say(text, title='말할 것'):
    """발표자가 그 쪽에서 입으로 말할 내용."""
    inner = [Paragraph(f'<b>{title}</b>', style('ct', 9.5, color=BRAND, space_after=3)),
             Paragraph(text, S['body'])]
    return Table([[inner]], colWidths=[W], style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F5F3FF')),
        ('BOX', (0, 0), (-1, -1), 0.8, BRAND),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]), hAlign='LEFT', spaceBefore=4, spaceAfter=8)


def kpis(items):
    data = [[Paragraph(v, S['kpi']) for v, _ in items], [Paragraph(l, S['kpilabel']) for _, l in items]]
    width = W / len(items)
    return Table(data, colWidths=[width] * len(items), style=TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.4, LINE), ('INNERGRID', (0, 0), (-1, -1), 0.4, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), PANEL), ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 8),
    ]), hAlign='LEFT', spaceAfter=8)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(25 * mm, 12 * mm, 'WaferAI · Fab AI Inspector — 최종 결과물 정리 (2026-11-17) · 팀 Wafer-Eye')
    canvas.drawRightString(A4[0] - 25 * mm, 12 * mm, str(doc.page))
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(25 * mm, 16 * mm, A4[0] - 25 * mm, 16 * mm)
    canvas.restoreState()


def blank(canvas, doc):
    pass


def ok(text):
    return f'<font color="#15803D"><b>{text}</b></font>'


def figure(name, caption, width=160 * mm):
    path = UI / name
    from PIL import Image as PILImage

    w, h = PILImage.open(path).size
    return KeepTogether([Image(str(path), width=width, height=width * h / w), P(caption, 'note')])


def pct(value, digits=2):
    return f'{value * 100:.{digits}f}%'


def mono(text):
    return f'<font face="Courier" size="8">{text}</font>'


cal = REPORT['calibration']
before = REPORT['effect']['before']['natural']
after = REPORT['effect']['after']['natural']
ood = REPORT['ood']
done = ok('완료')
S['kpi'] = style('k2', 14, color=BRAND, space_after=0, alignment=TA_CENTER)

story = []

# ── 표지 ──────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 42 * mm),
    P('SW 캡스톤디자인 · 2학기', 'subtitle'),
    P('WaferAI 최종 결과물 정리', 'title'),
    Spacer(1, 3 * mm),
    P('웨이퍼 결함 분류 서비스 · Fab AI Inspector', 'subtitle'),
    P(URL, 'subtitle'),
    Spacer(1, 14 * mm),
]
story.append(table([
    ['항목', '내용'],
    ['팀', '팀 Wafer-Eye · 조원곤, 변지민'],
    ['기준일', '2026년 11월 17일 · 저장소 태그 v1.0 (기능 동결)'],
    ['한 줄 요약', 'AI 가 먼저 판정하고 애매한 웨이퍼만 사람이 확정하는 웹 서비스. HTTPS 로 운영 중'],
    ['이 문서', '최종 산출물의 위치와 상태, 성능과 검증 결과, 설계 대비 구현, 한계, 발표 전 남은 일'],
    ['발표 일정', '11/18 – 19 전시회 · 12/03 최종 발표'],
], [30 * mm, 130 * mm]))
story.append(NextPageTemplate('body'))
story.append(PageBreak())

# ── 1. 한 장 요약 ─────────────────────────────────────────────────────────
story.append(P('1. 한 장 요약', 'h1'))
story.append(kpis([
    ('97.74%', '테스트 정확도 (학습에 안 쓴 17,504건)'),
    ('0.891', '테스트 macro-F1 (실제 분포)'),
    (f"{before['missed_defect']}→{after['missed_defect']}건", '결함을 정상으로 내보냄 (보정 전→후)'),
    ('263건', '자동 테스트 · 두 DB 에서 통과'),
    ('8 / 8', '설계한 화면 · API 31개'),
]))
story += bullet([
    '<b>무엇</b> — WM-811K 웨이퍼 맵(0/1/2)을 CoAtNet-0 으로 9개 클래스로 분류하고, Grad-CAM 으로 근거를 보여 주며, '
    '확신이 낮은 건은 엔지니어 검토로 보낸다. 검토 결과는 재학습 데이터가 된다.',
    '<b>어디까지</b> — 1학기의 모델 실험을 실제 서비스로 만들었다. FastAPI + ONNX Runtime, PostgreSQL, React, '
    'Docker Compose + Nginx 로 Azure 에 배포했고 HTTPS 주소로 누구나 가입 신청할 수 있다.',
    '<b>수치의 성격</b> — 모든 성능 수치는 학습에도, 기준을 맞추는 데에도 쓰지 않은 고정 테스트 셋(17,504건)에서 쟀다. '
    '1학기의 96.45% 는 학습 로트가 섞인 검증 값이었다.',
    '<b>상태</b> — 기능 개발은 끝냈다(태그 v1.0). 남은 것은 운영 서버 설정 한 건 반영, 전시회 시연, 최종 발표 자료다 (12절).',
])

story.append(P('산출물 8단계 최종 상태', 'h2'))
story.append(table([
    ['단계', '10/01 발표', '최종 (11/17)'],
    ['01 개발 환경', '완료', ok('완료') + ' — Docker 구성, CI 에서 실제 빌드 · 기동 검증'],
    ['02 DB 구축', '테이블 5개', ok('테이블 8개') + ' — 마이그레이션 6개, 스키마 SQL 문서'],
    ['03 백엔드', 'API 18개 · 설계 9개 중 8개', ok('API 31개') + ' — 설계 9개 모두 + 계정 · 보안 · 통계 · 내보내기'],
    ['04 프론트엔드', '화면 8개 중 6개', ok('8개 모두') + ' — 성능 추이 그래프까지'],
    ['05 시스템 통합', '시나리오 11개 중 8개', ok('전 기능 점검 77항목') + ' — 스크립트로 반복 가능'],
    ['06 테스트', '126건', ok('263건') + ' — SQLite · PostgreSQL 16, push 마다 CI'],
    ['07 디버깅', '버그 7건', '이후 발견 · 수정을 커밋과 README 에 기록 (측정 중 찾은 버그 포함)'],
    ['08 CI/CD · 배포', '예정 (서버 없음)', ok('운영 중') + ' — Azure, HTTPS, 자동 백업, 경고, 배포 스크립트'],
], [30 * mm, 42 * mm, 88 * mm]))

# ── 2. 산출물 목록 ────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('2. 최종 산출물 목록', 'h1'))
story.append(P('경로는 저장소(GitHub foreverami/WaferAI, 비공개) 기준이다.'))
story.append(table([
    ['산출물', '위치', '비고'],
    ['운영 서비스', URL, 'HTTPS · 가입 신청 후 관리자 승인'],
    ['소스 코드', 'GitHub foreverami/WaferAI · 태그 v1.0', '백엔드 waferai/ · 화면 frontend/ · 배포 deploy/'],
    ['모델', 'models/ (서버 · 개발 장비) · 원본은 Drive', '체크포인트 9f11749a764f + ONNX e8b046c79e58 (짝 검증)'],
    ['최종 결과물 정리 (이 문서)', 'docs/WaferAI_최종결과물_정리.pdf', 'scripts/build_final_summary.py 로 다시 생성'],
    ['사용 설명서', 'docs/WaferAI_사용설명서.md', '역할별 · 화면별 사용법, 자주 묻는 것'],
    ['운영 설명서', 'deploy/README.md', '설치 · HTTPS · 백업과 복원 · 업데이트 · 경고 · 문제 해결'],
    ['기술 문서', 'README.md', '설계 결정과 근거, 실측 결과, 한계'],
    ['DB 스키마', 'docs/WaferAI_DB_schema_postgresql.sql · alembic/versions/', '테이블 8개 · 마이그레이션 6개'],
    ['테스트', 'tests/ (263건) · .github/workflows/ci.yml', 'SQLite · PostgreSQL · 프론트 빌드 · 배포 구성'],
    ['전 기능 점검', 'scripts/acceptance.py · samples/', '실제 웨이퍼 12벌 × 4형식 + 특수 입력 6개'],
    ['판정 측정', 'scripts/calibrate.py · docs/calibration_report.json', '보정 · 판정 기준 · 입력 감지 · 색상표 측정 원본'],
    ['보고서', 'docs/WaferAI_진행보고서.pdf · _추가진행보고서_1013 · _발표_1105 · _개선보고_1116', '시점별 기록'],
    ['발표 자료', 'docs/WaferAI_중간발표_1105.pptx · _발표대본_1105.md', '11/05 기준 — 최종 발표용은 갱신 필요 (12절)'],
], [36 * mm, 68 * mm, 56 * mm]))

# ── 3. 시스템 구성 ────────────────────────────────────────────────────────
story.append(P('3. 시스템 구성', 'h1'))
story.append(table([
    ['구성', '기술', '역할'],
    ['화면', 'React 19 · Vite · Tailwind 4', '화면 8개. 토큰은 자바스크립트가 다루지 않는다 (httpOnly 쿠키)'],
    ['관문', 'Nginx', 'HTTPS, 보안 헤더(CSP · HSTS), 로그인 IP 속도 제한, 정적 파일'],
    ['서버', 'FastAPI · ONNX Runtime · PyTorch', '추론은 ONNX(CPU), Grad-CAM 만 PyTorch 를 지연 적재. API 31개'],
    ['저장', 'PostgreSQL 16 · Alembic', '판정 · 검토 · 계정 · 재학습 작업 · 보안 기록'],
    ['배포', 'Docker Compose (db · api · web · backup)', 'Azure VM 한 대(2 vCPU · 4GB). 모델 파일은 볼륨'],
    ['검증', 'GitHub Actions', 'push 마다 테스트 263건 × 2 DB, 프론트 빌드, 실제 Docker 기동과 확인 스크립트'],
], [22 * mm, 50 * mm, 88 * mm]))
story.append(P(
    '판정 흐름 — 업로드 → 형식 · 값 검사 → 모양 검사(웨이퍼가 아니면 판정 불가) → 전처리(학습과 비트 일치) → '
    'CoAtNet-0 → 확률 보정 → 고밀도 규칙(Near-full) → 확신도 기준 → 자동 통과 또는 검토 대기 → 사람 검토 → '
    '500건마다 재학습 작업.'))

# ── 4. 모델과 판정 성능 ───────────────────────────────────────────────────
story.append(CondPageBreak(90 * mm))
story.append(P('4. 모델과 판정 성능', 'h1'))
story.append(table([
    ['항목', '값', '설명'],
    ['모델', 'CoAtNet-0 · 9클래스', 'ImageNet 가중치에서 시작 · Colab T4 15에폭 78분 · 14에폭 선택'],
    ['데이터 분할', '로트 단위 80 / 10 / 10', '같은 로트가 학습과 평가에 섞이지 않게 고정 (split 6685ab33cec9096d)'],
    ['테스트 정확도', '97.74%', '실제 분포 17,504건 · macro-F1 0.891'],
    ['균형 표본', '96.24%', '4,844건 · macro-F1 0.918 — 1학기 수치와 같은 조건'],
    ['약한 클래스 (F1)', 'Loc 0.786 · Scratch 0.820 · Donut 0.839', 'Donut 은 테스트 표본 32건, Near-full 은 14건'],
    ['확률 보정', f"T = {cal['temperature']}", f"보정 오차(ECE) {cal['ece']['test_before']} → {cal['ece']['test_after']} · 정확도는 그대로"],
], [32 * mm, 52 * mm, 76 * mm]))
story.append(P('판정 로직의 효과 (테스트 셋 17,504건)', 'h2'))
story.append(table([
    ['', '보정 전 (확신도 0.80)', '최종 (보정 + 권장 기준)'],
    ['사람 검토 없이 나감', pct(before['unattended_rate']), pct(after['unattended_rate'])],
    ['그 안에서 정확도', pct(before['unattended_accuracy']), ok(pct(after['unattended_accuracy']))],
    ['틀린 채 자동 통과', f"{before['escaped']}건", ok(f"{after['escaped']}건")],
    ['결함을 정상으로 내보냄', f"{before['missed_defect']}건", ok(f"{after['missed_defect']}건")],
    ['검토로 가는 비율', pct(before['review_rate']), pct(after['review_rate'])],
], [56 * mm, 50 * mm, 54 * mm], aligns={1: 'RIGHT', 2: 'RIGHT'}))
story.append(say(
    '기준은 검증 분할(17,309건)에서만 맞추고 효과는 테스트 셋에서만 쟀다. 개선은 검토를 약 2%p 더 하는 대가로 '
    '오류를 절반으로 줄인 운영점 이동이다. 같은 검토량에서는 보정만으로 오류가 줄지 않았고, 클래스별 기준도 단일 '
    '임계값보다 낫지 않았다 — 보정이 한 일은 확신도를 믿을 수 있는 숫자로 만든 것이다. 검토 9.6% 를 감수하면 '
    '결함 누락을 2건까지 줄이는 더 엄격한 점도 있다.', '수치를 읽는 법'))
story.append(P('입력을 지키는 장치', 'h2'))
story.append(table([
    ['장치', '측정 결과'],
    ['웨이퍼 모양 검사', f"가짜 입력 600장 모두 감지 — 검사가 없었다면 268장이 자동 통과. 실제 맵 {ood['real_maps']:,}장 중 오탐 {ood['real_flagged']}장"],
    ['색상표 해석', '학습 색 · viridis · 회색조 2종은 400장씩 모두 정확 복원. 처음 보는 3색은 추정 후 검토 강제 (잘못 읽고 통과한 것 0장)'],
    ['전처리 일치', '서버 전처리로 1학기 검증 정확도 96.4538% 를 그대로 재현 (차이 0.0000%p)'],
    ['모델 짝 검사', 'ONNX 가 체크포인트 해시를 싣고 다녀, 옛 ONNX 로 새 모델을 내는 사고를 기동 때 막는다'],
], [36 * mm, 124 * mm]))

# ── 5. 기능 ───────────────────────────────────────────────────────────────
story.append(CondPageBreak(70 * mm))
story.append(P('5. 기능 — 화면 8개', 'h1'))
story.append(table([
    ['화면', '주요 기능', '최소 등급'],
    ['로그인', 'httpOnly 쿠키 세션, 연속 실패 잠금 안내', '—'],
    ['가입 신청', '신청 → 승인 대기 → 관리자 승인. 입력 오류는 한국어 한 줄로', '—'],
    ['대시보드', '여러 파일 업로드와 결과 요약, 처리 경로 배지, 기록 CSV', '엔지니어'],
    ['상세 팝업', '원본 / 히트맵 / 겹쳐보기, 1순위 승인 · 2순위 수정 · 수동 라벨링, 검토 이유', '엔지니어'],
    ['리뷰 대기열', '검토 필요 · 판정 불가 건, 클래스 필터, 대기열 CSV', '엔지니어'],
    ['설정', '클래스별 권장 기준, 단일 임계값과 예상 검토율, 밀도 규칙', '수석 엔지니어'],
    ['모델 관리', '운영 모델 성적, 성능 추이 그래프, 보정 효과, 재학습 작업, 서버 상태(관리자)', '수석 엔지니어'],
    ['계정', '권한 · 비밀번호 변경, (관리자) 사용자 관리 · 가입 승인 · 초기화 · 잠금 해제 · 보안 기록', '엔지니어'],
], [26 * mm, 108 * mm, 26 * mm]))
story.append(figure('improve_batch_upload.png', '대시보드 — 파일 5개를 한 번에 올린 결과. 자동 통과 · 검토 필요 · 판정 불가 · 거절(이유 포함)이 한 상자에 보인다.', 150 * mm))
story.append(PageBreak())
story.append(figure('improve_out_of_scope.png', '상세 팝업 — 체크무늬 배열을 모델은 Random 98.4% 로 판정했지만 "판정 불가" 로 사람에게 넘어간다.', 150 * mm))
story.append(figure('improve_models.png', '모델 관리 — 성능 추이, 확률 보정 효과, 서버 상태. (로컬 미리보기 화면이라 그래프가 한 주뿐이다)', 150 * mm))

# ── 6. 보안 ───────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('6. 보안 — OWASP 인증 체크리스트 기준', 'h1'))
story.append(table([
    ['항목', '구현'],
    ['계정 존재 비노출', '없는 사번과 틀린 비밀번호가 같은 응답 · 같은 응답 시간'],
    ['비밀번호', 'bcrypt + 자동 솔트. 8자 이상, 짧으면 두 종류 섞기, 사번 포함 금지'],
    ['세션', 'HS256 고정 · 8시간 만료 · httpOnly · Secure · SameSite 쿠키'],
    ['무효화', '로그아웃한 토큰은 만료까지 거부. 비밀번호 변경 · 초기화 · 비활성화 시 다른 기기 세션 종료'],
    ['무차별 대입', '계정: 5회 실패 시 60초~15분 잠금. IP: Nginx 분당 30회 제한 (운영 반영은 12절 1번)'],
    ['임시 비밀번호', '관리자가 발급(한 번만 표시), 바꾸기 전에는 다른 기능 차단'],
    ['권한', '세 등급. 모든 API 가 서버에서 등급을 확인 (화면 숨김은 방어가 아님)'],
    ['전송', 'HTTPS(Let\'s Encrypt 자동 갱신) · HSTS · CSP · X-Frame-Options'],
    ['기록', '로그인 성공 · 실패 · 잠금 · 발급 · 승인 · 설정 변경을 로그와 DB 에. 관리자 화면에서 조회'],
], [34 * mm, 126 * mm]))

# ── 7. 검증 ───────────────────────────────────────────────────────────────
story.append(P('7. 검증 결과', 'h1'))
story.append(table([
    ['검증', '결과', '시점'],
    ['자동 테스트', '263건 통과 — SQLite 와 PostgreSQL 16 양쪽', '11/16 CI'],
    ['배포 구성', '실제 Docker 로 네 서비스 기동 · 확인 스크립트 8단계', '11/16 CI'],
    ['프론트엔드', 'lint 경고 0 · 빌드 성공', '11/16 CI'],
    ['전 기능 점검 (운영)', '65 / 65 통과 (당시 항목 수)', '11/03'],
    ['전 기능 점검 (로컬)', '76 / 76 통과 — 새 기능 포함. 운영에서는 화면 CSP 1항목이 더해져 77', '11/16'],
    ['운영 서버 반영 확인', '모델 해시 일치 · 마이그레이션 2개 적용 · 네 서비스 healthy · 첫 자동 백업', '11/16'],
    ['운영 공개 경로 점검', '15항목 중 14 통과 — 로그인 IP 속도 제한이 빠져 있는 것을 발견', '11/17'],
    ['판정 측정', '보정 · 판정 기준 · 입력 감지 · 색상표 (docs/calibration_report.json)', '11/16'],
], [38 * mm, 98 * mm, 24 * mm]))
story.append(say(
    '11/17 점검에서 로그인 요청 30회를 연속으로 보내도 429 가 나오지 않았다. 서버의 HTTPS 설정 파일은 11/03 에 예시에서 '
    '한 번 만든 서버 전용 파일이라, 그 뒤 예시에 더한 속도 제한이 들어가 있지 않았다. 계정 단위 잠금(5회 실패)은 앱이 '
    '하므로 정상 동작한다. 배포 스크립트가 이 파일을 매번 다시 만들고 문법 검사 후 반영하도록 고쳤고, 스크립트를 한 번 '
    '실행하면 반영된다 (12절 1번). 점검 스크립트가 없었다면 발표 때까지 몰랐을 문제다.', '마지막 점검에서 찾은 것'))

# ── 8. 운영 ───────────────────────────────────────────────────────────────
story.append(CondPageBreak(80 * mm))
story.append(P('8. 운영', 'h1'))
story.append(table([
    ['항목', '내용'],
    ['서버', 'Azure for Students · East Asia(홍콩) · 2 vCPU · 4GB · Ubuntu 24.04 · 한국 리전은 학생 구독에서 막힘'],
    ['실측', '예측 170 – 340ms · 히트맵 1.0초(캐시 0.55초) · API 메모리 1.05GB · 5건 동시 업로드 0.7초'],
    ['배포', mono('sh deploy/deploy_update.sh') + ' — 코드 · 모델 · HTTPS 설정을 올리고 다시 띄움. 마이그레이션 자동 적용'],
    ['백업', 'backup 서비스가 24시간마다 pg_dump, 14개 보관. 화면에서 마지막 백업 확인. 복원 절차는 운영 설명서'],
    ['경고', 'Azure Monitor 규칙 3개 — 서버 꺼짐 · CPU 85% · 메모리 300MB 미만이면 관리자 메일'],
    ['비용 · 기한', '크레딧 $100 에서 월 약 $30. 2027년 1월 중순쯤 소진되면 서버가 멈춘다 (청구 없음)'],
    ['재학습', '검토 500건마다 작업 생성 → 데이터 내려받기 → GPU 학습 → 승격 기준 통과 시 교체. 한 번 끝까지 실행함'],
], [26 * mm, 134 * mm]))

# ── 9. 설계 대비 구현 ─────────────────────────────────────────────────────
story.append(P('9. 1학기 설계 대비 실제 구현', 'h1'))
story.append(P('1학기 산출 문서를 기준으로 구현하면서 확인한 차이다. 대부분 문서 쪽을 고쳐야 하는 항목이고, 일부는 측정으로 설계가 반증됐다.'))
story.append(table([
    ['항목', '1학기 문서', '실제 구현 · 확인된 사실'],
    ['판정 단계', '문서마다 2단계 / 3단계로 다름', '5단계로 통일 (모양 → 저밀도 → 고밀도 → 확신도 → 검토), 정의되지 않은 구간 제거'],
    ['저밀도 규칙', '밀도 5% 미만이면 정상', '측정으로 반증 — 켜면 결함 누락이 19 → 140건. 기본 꺼짐'],
    ['확신도 기준', '임계값 슬라이더 하나', '확률 보정 + 모델이 싣고 다니는 권장 기준. 슬라이더는 모델별 상한과 예상 검토율 표시'],
    ['데이터 분할', 'Train 80 / Val 10 / Test 10', '1학기 모델은 8:2 뿐이었다 → 로트 단위 80/10/10 으로 다시 학습해 실현'],
    ['정확도', '약 95.7%', '1학기 검증 96.45% (로트 섞임) → 고정 테스트 셋 97.74%'],
    ['손실 함수', '기능명세서는 CrossEntropy', '실제는 Focal Loss (γ=2). 플로우차트가 맞다'],
    ['입력 형식', 'PNG/JPG 사진 업로드', '모델은 0/1/2 맵으로 학습 — 맵 파일과 그 맵을 3색으로 그린 그림만 받는다'],
    ['ERD', '7개 테이블, 사용자 테이블 없음', '8개 — Vision 4개 + users · settings · revoked_tokens · audit_events. Sensor 3개는 제외'],
    ['대시보드', '설계는 React', '기존 app.py 는 센서 프로젝트의 Streamlit 이었다 → React 로 새로 구현'],
    ['API 명세서', '다른 프로젝트 내용으로 덮어쓰임', '플로우차트 §5 의 9개를 기준으로 모두 구현, 지금 31개. 명세서 복구 필요'],
    ['재학습', '500건 트리거', '작업 생성 · 데이터 내려받기 · GPU 학습 · 승격 기준 · 교체 시 자동 완료까지'],
    ['Sensor AI · 통합 리포트', '설계에 포함', '만들지 않음 — Vision 을 서비스 수준으로 끝내는 쪽을 택함. 교수님 확인 필요'],
], [30 * mm, 46 * mm, 84 * mm]))

# ── 10. 한계 ──────────────────────────────────────────────────────────────
story.append(CondPageBreak(80 * mm))
story.append(P('10. 한계 — 먼저 말해 둘 것', 'h1'))
story += bullet([
    '<b>판정 개선은 검토를 더 하는 대가다.</b> 검토 3.58% → 5.78%. 같은 검토량에서는 오류가 줄지 않았고, 클래스별 기준의 몫도 없었다.',
    '<b>약한 클래스는 그대로다.</b> Loc 0.786 · Scratch 0.820 · Donut 0.839. 보강 학습 옵션은 준비했지만 GPU 학습은 돌리지 않았다.',
    '<b>표본이 작은 클래스가 있다.</b> 테스트 셋에 Near-full 14건, Donut 32건뿐이라 이 두 클래스의 수치는 한두 건에 흔들린다.',
    '<b>WM-811K 밖의 데이터는 모른다.</b> 실제 공장 데이터에서의 정확도는 운영에서 쌓이는 검토로만 확인할 수 있다.',
    '<b>실물 웨이퍼 사진은 판정하지 못한다.</b> 입력은 전기 검사 맵과 그 맵을 3색으로 그린 그림뿐이다.',
    '<b>입력 감지는 모양만 본다.</b> 웨이퍼 모양을 한 엉뚱한 내용은 통과한다.',
    '<b>서버는 한 대다.</b> 이중화가 없고 추론은 한 번에 한 장씩 돈다. 많은 동시 사용자는 재 보지 않았다.',
    '<b>재학습은 사람이 돌린다.</b> 상시 GPU 가 없어 자동화하지 않았다.',
    '<b>운영 기한이 있다.</b> 학생 크레딧이 끝나는 2027년 1월 중순 이후에는 서버가 멈춘다.',
])

# ── 11. 시연 ──────────────────────────────────────────────────────────────
story.append(CondPageBreak(105 * mm))
story.append(P('11. 시연 순서 (3분 · 11/16 기능 기준으로 갱신)', 'h1'))
story.append(table([
    ['#', '할 것', '보여줄 것'],
    ['1', '관리자로 로그인', 'HTTPS 주소, 가입 신청 링크'],
    ['2', 'samples/ 의 파일 5개를 한 번에 업로드 — auto_Scratch_22185.png · review_Loc_21258.npy · palette_viridis.png · oos_checkerboard.json · bad_photo_like.png',
     '결과 요약 상자 한 장에 자동 통과 · 검토 필요 · viridis 로 읽은 건 · 판정 불가 · 거절(이유)'],
    ['3', '판정 불가 건 열기', '모델은 Random 98% 라 했지만 사람에게 넘어간 이유 상자'],
    ['4', '검토 필요 건 열기 → 히트맵 → 1순위 승인', '원본 / 히트맵 / 겹쳐보기, 승인 후 대기 해제'],
    ['5', '설정 — 클래스별 기준 끄기', '슬라이더가 살아나고 임계값별 예상 검토율이 보임. 다시 켜기'],
    ['6', '모델 관리', '테스트 성적, 성능 추이, 보정 전후 표, 서버 상태(마지막 백업)'],
    ['7', '계정', '가입 승인, 비밀번호 초기화, 보안 기록(방금 한 로그인이 보임)'],
], [7 * mm, 83 * mm, 70 * mm]))
story.append(P('예비: 인터넷이 막히면 노트북에서 python3 -m scripts.serve_preview 와 npm --prefix frontend run dev 로 같은 화면을 띄운다. '
               '11/05 대본의 "다른 색상표 거절" 장면은 더 이상 맞지 않는다 — 그 그림은 이제 viridis 로 읽힌다.', 'note'))

# ── 12. 남은 일 ───────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('12. 발표 전 남은 일', 'h1'))
story.append(table([
    ['#', '할 일', '누가 · 언제', '상태'],
    ['1', '운영 서버에 HTTPS 설정 반영 — ' + mono('sh deploy/deploy_update.sh') + ' 한 번 실행. 로그인 IP 속도 제한이 켜진다',
     '사용자 · 전시회 전', '스크립트 준비됨'],
    ['2', '운영 서버 전 기능 점검 77항목 — 점검용 계정 3개(엔지니어 · 수석 · 관리자)를 잠시 켜고 scripts/acceptance.py 실행',
     '사용자 또는 계정 전달 후 · 전시회 전', '로컬 76/76'],
    ['3', '전시회 시연 (11절 순서) · 로컬 예비 화면 리허설', '팀 · 11/18 – 19', '시나리오 준비됨'],
    ['4', 'Sensor AI 를 이번 학기 범위 밖으로 확인', '교수님 · 이번 주', '확인 필요'],
    ['5', '최종 발표 자료 · 대본을 11/16 기능과 이 문서의 수치로 갱신, 시연 영상 녹화', '팀 · 11/27 – 12/01', '11/05 판 있음'],
    ['6', '1학기 설계 문서를 9절 표대로 수정 (판정 규칙 · 손실 함수 · 입력 형식 · ERD · API 명세서 복구)', '팀 · 12/03 전', '차이 정리됨'],
    ['7', '운영 서버 최종 점검, 이후 코드 변경 없음', '팀 · 12/02', '태그 v1.0'],
    ['8', 'DB · 모델 백업 후 서버 정리', '팀 · 발표 뒤, 1월 중순 전', ''],
], [7 * mm, 85 * mm, 40 * mm, 28 * mm]))
story.append(P('하지 않기로 한 것', 'h2'))
story.append(table([
    ['항목', '이유'],
    ['약한 클래스 재학습', '개선 폭이 작을 가능성이 크고, 모델이 바뀌면 이 문서의 모든 수치와 점검 기대값을 다시 재야 한다. 옵션(--oversample)과 승격 절차는 남겨 두었다'],
    ['재학습 자동화', '상시 GPU 가 필요해 비용이 든다'],
    ['실물 사진 분류', '데이터부터 새로 필요한 별도 과제'],
], [38 * mm, 122 * mm]))
story.append(P('다시 확인하는 명령', 'h2'))
story += bullet([
    '자동 테스트 — ' + mono('python3 -m unittest discover -s tests -t .'),
    '전 기능 점검 — ' + mono('ACC_ENG=ID:PW ACC_SEN=ID:PW ACC_ADM=ID:PW python3 -m scripts.acceptance --base ' + URL) + ' (ID:PW 자리에 점검용 계정의 사번:비밀번호)',
    '판정 측정 — ' + mono('python3 -m scripts.calibrate') + ' (결과는 docs/calibration_report.json)',
    '이 문서 — ' + mono('python3 -m scripts.build_final_summary'),
])

doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                      topMargin=22 * mm, bottomMargin=22 * mm,
                      title='WaferAI 최종 결과물 정리', author='팀 Wafer-Eye')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
doc.addPageTemplates([PageTemplate(id='cover', frames=[frame], onPage=blank),
                      PageTemplate(id='body', frames=[frame], onPage=footer)])
doc.build(story)
print(f'생성 완료: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)')
