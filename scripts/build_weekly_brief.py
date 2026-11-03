"""이번 주 발표 자료 PDF — 10/01 발표 이후 진행과 현재 상태를 발표 순서대로 정리한다.

    python3 -m scripts.build_weekly_brief          # → docs/WaferAI_발표_1105.pdf

슬라이드 대신 손에 들고 말할 수 있는 자료다. 쪽마다 "보여줄 것 · 말할 것" 을 두고, 수치는
scripts/acceptance.py 와 README 의 실측값을 그대로 옮긴다. 모양은 build_update_report.py 와 같다.
"""
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
OUT = ROOT / 'docs/WaferAI_발표_1105.pdf'
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
    canvas.drawString(25 * mm, 12 * mm, 'WaferAI · Fab AI Inspector — 11월 1주 발표 자료 · 팀 Wafer-Eye')
    canvas.drawRightString(A4[0] - 25 * mm, 12 * mm, str(doc.page))
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(25 * mm, 16 * mm, A4[0] - 25 * mm, 16 * mm)
    canvas.restoreState()


def blank(canvas, doc):
    pass


def ok(text):
    return f'<font color="#15803D"><b>{text}</b></font>'


story = []

# ── 표지 ──────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 48 * mm),
    P('SW 캡스톤디자인 · 11월 1주 발표', 'subtitle'),
    P('WaferAI 배포 완료 보고', 'title'),
    Spacer(1, 3 * mm),
    P('웨이퍼 결함 분류 서비스가 인터넷에 떠 있고, 실제 데이터로 전 기능을 검증했습니다', 'subtitle'),
    P(URL, 'subtitle'),
    Spacer(1, 18 * mm),
]
story.append(table([
    ['항목', '내용'],
    ['팀', '팀 Wafer-Eye · 조원곤, 변지민'],
    ['기준 발표', '10/01 5주차 (Phase 0 – 4, 테스트 126건, 서버 없음)'],
    ['이번 보고 범위', '10/02 – 11/03 · 커밋 19개 · Phase 5 – 6, 재학습, 배포, 계정 기능, 실서버 점검'],
    ['작성일', '2026년 11월 3일'],
    ['발표 시간', '약 8분 (쪽마다 "말할 것" 상자 기준, 시연 3분 포함)'],
], [35 * mm, 125 * mm]))
story.append(NextPageTemplate('body'))
story.append(PageBreak())

# ── 1. 한 장 요약 ─────────────────────────────────────────────────────────
story.append(P('1. 한 장 요약 — 지금 어디까지 왔나', 'h1'))
story.append(kpis([('97.74%', '테스트 정확도 (학습에 안 쓴 17,504건)'), ('0.891', '테스트 macro-F1 (실제 분포)'),
                   ('214건', '자동 테스트 · CI 통과'), ('65 / 65', '실서버 기능 점검'), ('27개', 'API (설계 9개 모두 구현)')]))
story.append(table([
    ['산출물 8단계', '10/01 발표', '지금'],
    ['01 개발 환경', '완료 · Docker 는 08단계로', ok('완료') + ' — Docker 구성, CI 에서 실제 빌드 · 기동 검증'],
    ['02 DB 구축', '테이블 5개', ok('테이블 6개') + ' — 재학습 작업, 모델 출처, 가입 승인 열'],
    ['03 백엔드', 'API 18개 · 설계 9개 중 8개', ok('API 27개 · 설계 9개 모두')],
    ['04 프론트엔드', '화면 8개 중 6개', ok('8개 중 7개') + ' — 모델 관리, 계정(가입 · 승인 · 초기화). 추이 그래프만 보류'],
    ['05 시스템 통합', '시나리오 11개 중 8개', ok('실서버 65항목 점검 통과') + ' — 업로드부터 재학습 요청까지'],
    ['06 테스트', '126건', ok('214건') + ' — SQLite · PostgreSQL 16, push 마다 CI'],
    ['07 디버깅', '버그 7', ok('이후 14건 추가 수정')],
    ['08 CI/CD · 배포', '예정 (서버 확보 후)', ok('배포 완료') + ' — Azure, HTTPS, 자동 갱신, 배포 구성도 CI 검증'],
], [28 * mm, 42 * mm, 90 * mm]))
story.append(say(
    '10월 1일에는 서버도, 깨끗한 테스트 정확도도 없었습니다. 한 달 사이에 모델을 3분할로 다시 학습해 '
    '학습에 쓰지 않은 데이터로 97.74%를 확인했고, 서비스를 클라우드에 올려 HTTPS 주소로 누구나 접속할 수 '
    '있게 했습니다. 오늘은 ① 재학습 결과, ② 배포, ③ 새로 붙은 계정 기능, ④ 실제 데이터로 한 전 기능 점검을 '
    '순서대로 말씀드리고 마지막에 직접 시연하겠습니다.'))

# ── 2. 재학습 ────────────────────────────────────────────────────────────
story.append(P('2. 3분할 재학습 — "검증 정확도" 에서 "테스트 정확도" 로', 'h1'))
story.append(P(
    '10/01 발표의 96.45%는 학습과 섞인 검증 정확도였습니다(질문 Q1). 로트 단위로 train 80 / val 10 / test 10 을 '
    '나눠 ImageNet 가중치에서 새로 학습하고, 학습에 전혀 쓰지 않은 테스트 셋으로 쟀습니다.'))
story.append(table([
    ['', '10/01 발표 (1학기 모델)', '지금 (재학습 모델, 10/13 교체)'],
    ['수치의 성격', '검증 정확도 96.45% — 학습과 로트가 섞임', ok('테스트 정확도 97.74%') + ' · macro-F1 0.891 (17,504건)'],
    ['균형 표본', '—', '정확도 96.24% · macro-F1 0.918 (4,844건)'],
    ['학습 환경', '1학기 Colab', 'Colab T4 · 15에폭 78분 · 14에폭 선택 (검증 96.85%)'],
    ['약한 클래스', 'Loc 0.868 · Donut 0.866', 'Loc 0.786 · Scratch 0.820 · Donut 0.839 (표본 32건)'],
    ['교체 판정', '—', '승격 스크립트가 직접 재서 통과 → ONNX 재생성 · 이전 모델 보관'],
], [30 * mm, 60 * mm, 70 * mm]))
story.append(P('판정 로직 효과 (새 모델 · 테스트 셋 · 확신도 0.80)', 'h2'))
story.append(table([
    ['', '실제 분포 17,504건', '균형 4,844건'],
    ['사람 검토 없이 나감', '96.42% (그 안 정확도 99.23%)', '94.65%'],
    ['그중 틀린 건 / 전체', '0.74% (130건)', '1.51%'],
    ['결함을 정상으로 내보냄', '19건 (Edge-Loc 8 · Loc 5 · Scratch 3 · Center 3)', '19건'],
    ['검토 대기 (AI 정답률)', '3.58% (57.7%)', '5.35%'],
], [40 * mm, 70 * mm, 50 * mm]))
story.append(say(
    '숫자가 10/01 때보다 좋아 보이지만 성격이 다릅니다. 그때는 학습에 쓴 로트가 검증에도 섞인 값이었고, 지금은 '
    '한 번도 보지 않은 웨이퍼로 잰 값입니다. 발표의 "95% 통과 · 1.4% 오류" 도 같은 조건으로 다시 재니 94.65% · '
    '1.51% 로 거의 같아서, 1학기 수치가 틀린 건 아니었다는 것까지 확인됐습니다. 모델의 확신도가 0.90 – 0.92 에 '
    '몰려 있다는 것도 이때 알았고, 그래서 설정 화면이 모델별 상한을 알도록 고쳤습니다.'))

# ── 3. 배포 ───────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('3. 배포 — 인터넷에 떠 있는 서비스', 'h1'))
story.append(table([
    ['항목', '내용'],
    ['주소', URL + ' (HTTPS, Let\'s Encrypt 인증서 · 매주 자동 갱신)'],
    ['서버', 'Azure for Students 크레딧(무료) · 홍콩 리전 · 2 vCPU · 4GB · Ubuntu 24.04'],
    ['구성', 'Docker Compose 3컨테이너 — Nginx(화면 · 보안 헤더 · 프록시) / FastAPI(추론 · Grad-CAM) / PostgreSQL 16'],
    ['실측', '세 서비스 healthy 22초 · 예측 170 – 340ms · 첫 히트맵 1.0초 · API 메모리 1.05GB · 5건 동시 업로드 0.7초'],
    ['검증', '배포 절차서 7단계 · 사전 점검 스크립트 · 배포 후 확인 스크립트 8단계 — CI 가 push 마다 실제 Docker 로 같은 절차를 돌림'],
    ['비용', '크레딧 $100 에서 월 약 $30 — 1월 중순까지 운영 가능, 카드 등록 없음'],
], [25 * mm, 135 * mm]))
story.append(P('왜 이 구성인가', 'h2'))
story += bullet([
    '<b>서버는 학교 답을 기다리지 않고 학생 크레딧으로</b> — 카드 없이 받을 수 있고 발표일을 넘겨 쓸 수 있는 유일한 무료 경로였습니다. '
    '한국 리전은 학생 구독에서 막혀 있어 가장 가까운 홍콩을 썼습니다(지연 50ms 안팎).',
    '<b>HTTPS 가 필수</b> — 로그인 쿠키에 Secure 속성을 두어 HTTP 로는 브라우저가 쿠키를 저장하지 않습니다. Azure 의 무료 DNS 이름으로 인증서를 받았습니다.',
    '<b>모델 파일은 이미지에 넣지 않고 볼륨으로</b> — 재학습으로 모델을 바꿀 때 이미지를 다시 만들지 않습니다. 서버가 기동하며 새 모델을 등록하고 재학습 작업을 자동 완료합니다.',
])
story.append(say(
    '이 주소는 지금 열립니다. 서버는 학교 지원 대신 Azure 학생 크레딧으로 확보했고 카드 없이 1월까지 돌아갑니다. '
    '배포 절차는 GitHub Actions 가 push 할 때마다 실제 Docker 에서 똑같이 돌려 보기 때문에, 서버에서 처음 올릴 때 '
    '구성이 틀릴 가능성을 미리 없앴습니다. 실제로 서버 당일 막힌 것은 학생 구독의 리전 제한 하나뿐이었습니다.'))

# ── 4. 새 기능 ────────────────────────────────────────────────────────────
story.append(P('4. 10/01 이후 추가된 기능', 'h1'))
story.append(table([
    ['기능', '내용', '설계 근거'],
    ['재학습 루프 (화면 5)', '검토 500건 누적 시 자동 작업 · 관리자 수동 요청 · 학습 데이터 내려받기 · Colab 학습 · 승격 판정 · 교체 시 자동 완료',
     '플로우차트 §5 재학습 트리거 — 설계 API 9개 중 마지막'],
    ['계정 화면 (화면 8)', '권한 배지 · 잠긴 사번 · 마지막 비밀번호 변경일(90일 경고) · 비밀번호 변경 · (관리자) 사용자 관리', 'UIUX 화면 8 명세 그대로'],
    ['가입 신청 → 승인', '로그인 화면에서 신청 → 승인 대기 → 관리자 승인. 승인 전 로그인하면 안내. 권한은 엔지니어로 시작',
     '주소만 알면 누구나 들어오는 구조를 피함'],
    ['비밀번호 찾기', '관리자가 임시 비밀번호 발급(한 번만 표시) · 관리자 본인은 서버 명령', '메일 발송 없이 쓰는 내부 시스템 방식'],
    ['설정 상한', '모델별 확신도 프로필 — 슬라이더 상한 = 모델 최대 확신도, 임계값별 예상 검토율 표시, 20% 넘으면 경고',
     '0.92 를 넘기면 전부 검토로 가는 것을 측정으로 발견'],
    ['오류 안내', '입력 검증 실패를 항목 이름과 함께 한국어로 ("이메일 형식이 올바르지 않습니다")', '사용자 피드백'],
], [30 * mm, 80 * mm, 50 * mm]))
story.append(say(
    '기능 하나하나보다 공통점을 말씀드리면, 전부 "사람이 최종 확정한다" 는 이 시스템의 원칙을 따릅니다. 가입은 관리자가 '
    '승인하고, 비밀번호도 관리자가 초기화하고, 재학습 모델도 기준을 넘어야만 교체됩니다. 그리고 설정 상한처럼 '
    '측정에서 발견한 위험은 화면이 미리 막습니다.'))

# ── 5. 실서버 점검 ────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('5. 실제 데이터로 전 기능 점검 — 65항목 전부 통과', 'h1'))
story.append(P(
    '학습에 쓰지 않은 테스트 분할에서 실제 웨이퍼 12벌을 골라(클래스별 자동 통과 9 · 검토 대기 2 · Near-full 규칙 1) '
    '네 가지 형식으로, 거절돼야 하는 입력 4개와 함께 운영 서버에 올렸습니다. 점검 스크립트(scripts/acceptance.py)가 '
    '로그인 없이 되는 것부터 재학습 요청까지 호출해 표로 보고합니다.'))
story.append(table([
    ['영역', '확인한 것', '결과'],
    ['공개 경로', '헬스체크 · CSP 헤더 · 비로그인 401 · 계정 존재 비노출 · 한국어 검증 메시지', '6 / 6'],
    ['업로드 · 판정', '12벌 모두 정답 클래스 · 기대한 경로(자동 통과 / 검토 대기 / Near-full 규칙) · 170 – 340ms', '12 / 12'],
    ['입력 형식', 'npy · csv · json · png 같은 답 · 다른 색상표 · 깨진 파일 · 잘못된 값 거절 · 900px 축소 경고', '5 / 5'],
    ['결과 보기', '목록 · 대기열 · 상세 · 썸네일 · 히트맵(1.0초 → 캐시 0.55초) · 2순위 히트맵', '6 / 6'],
    ['검토', '1순위 승인 · 2순위 수정(AI 판정 보존) · 수동 라벨링 · 없는 클래스 거부', '4 / 4'],
    ['수석 · 관리자', '임계값 · 상한 422 · 모델 목록 · 계정 생성 · 비활성화 · 초기화 · 가입 승인 · 권한 차단', '21 / 21'],
    ['재학습 · 동시성', '요청 → 데이터 내려받기 → 실패 처리 · 5건 동시 업로드', '5 / 5'],
], [28 * mm, 112 * mm, 20 * mm], aligns={2: 'CENTER'}))
if GRADCAM.is_file():
    story.append(KeepTogether([
        Image(str(GRADCAM), width=120 * mm, height=120 * mm * 0.55),
        P('Grad-CAM — 합성 패턴(가운데 · 도넛 · 가장자리 · 스크래치)에서 히트맵이 결함 위치를 가리킨다', 'note'),
    ]))
story.append(say(
    '점검 중 틀어진 것은 다섯 건이었는데 모두 점검 스크립트의 기대값 실수였고 제품 결함은 없었습니다. 예를 들어 '
    'Near-full 웨이퍼는 확신도 0.91 이라 자동 통과를 기대했지만, 설계대로 밀도 규칙이 먼저 잡아 "규칙 확정" 으로 '
    '나왔습니다. 이 점검은 스크립트로 남겨 두어 다음에 무엇을 고쳐도 10분 안에 다시 돌릴 수 있습니다.'))

# ── 6. 시연 ───────────────────────────────────────────────────────────────
story.append(CondPageBreak(70 * mm))
story.append(P('6. 시연 순서 (3분)', 'h1'))
story.append(table([
    ['#', '화면', '할 것', '보여줄 것'],
    ['1', '로그인', '관리자로 로그인', 'HTTPS 주소, 가입 신청 링크, 비밀번호 안내'],
    ['2', '대시보드', 'samples/auto_Scratch_22185.png 업로드', '이미지가 0/1/2 맵으로 복원되어 Scratch 93% 자동 통과'],
    ['3', '대시보드', 'samples/review_Loc_21258.npy 업로드', '확신도 45% → 검토 필요 · 대기열 카운터 증가'],
    ['4', '상세', '검토 필요 건 열기 → 히트맵 → 1순위 승인', '원본 / 히트맵 / 겹쳐보기, 승인 후 대기 해제'],
    ['5', '대시보드', 'samples/bad_other_palette.png 업로드', '다른 색상표는 이유와 함께 거절 (잘못 해석하지 않음)'],
    ['6', '설정', '확신도 슬라이더를 92% 로', '"검토 대기 약 98.7%" 빨간 경고 — 모델별 상한'],
    ['7', '모델 관리', '운영 모델 · 테스트 성적 · 재학습 현황', '분할 지문, 테스트 정확도, 500건까지 남은 수'],
    ['8', '계정', '사용자 목록 · 승인 대기 · 초기화 버튼', '가입 승인과 비밀번호 초기화'],
], [7 * mm, 22 * mm, 60 * mm, 71 * mm]))
story.append(P('예비: 전시장 인터넷이 막히면 노트북에서 `python3 -m scripts.serve_preview` + `npm run dev` 로 같은 화면을 로컬에서 보여준다. '
               'samples/ 의 파일은 저장소에 있다.', 'note'))

# ── 7. 남은 일 · 일정 ─────────────────────────────────────────────────────
story.append(P('7. 남은 일과 일정', 'h1'))
story.append(table([
    ['시점', '일', '상태'],
    ['11/18 – 19 전시회', '시연 시나리오 확정 · 예비(로컬) 준비 · 동시 접속 부하 확인', '시나리오 준비됨, 예비 미확인'],
    ['12/03 최종 발표 전', '보고서 · 발표 자료 최종본 (수치 확정)', '10/13 보고서 이후 갱신 필요'],
    ['12/03 최종 발표 전', '1학기 설계 문서 정리 — 코드와 다른 부분 수정, 범위 밖(WaferNet · Streamlit · Sensor) 정리', '미착수'],
    ['선택', '다른 색상표 이미지 지원(업로드 시 색 확인) · 화면 5 성능 추이 그래프', '보류'],
    ['결정 필요', 'Sensor AI — "이번 학기 범위 밖" 으로 명시', '교수님 확인'],
    ['발표 후', 'DB 백업 뒤 VM 정리 (크레딧 절약)', '1월 중순 크레딧 소진'],
], [32 * mm, 88 * mm, 40 * mm]))
story.append(say(
    '기능 개발은 여기서 마무리하고, 남은 기간은 전시회 시연과 최종 산출물 정리에 씁니다. Sensor AI 는 1학기 설계에는 '
    '있었지만 Vision 을 서비스 수준으로 끝내는 쪽을 택했고, 범위 밖으로 정리해도 되는지 확인을 받고 싶습니다.'))

# ── 예상 질문 ─────────────────────────────────────────────────────────────
story.append(CondPageBreak(60 * mm))
story.append(P('예상 질문', 'h1'))
story.append(table([
    ['질문', '답'],
    ['97.74% 가 96.45% 보다 높은데 "더 엄격한 수치" 라는 게 무슨 뜻인가?',
     '96.45% 는 학습 로트가 섞인 검증 값, 97.74% 는 한 번도 보지 않은 로트의 테스트 값이다. 같은 테스트 셋에서 1학기 모델은 '
     '98.19% 가 나오지만 그 샘플을 학습에 썼으므로 부풀려진 값이라 비교하지 않는다.'],
    ['실물 웨이퍼 사진도 되나?', 'WM-811K 는 사진이 아니라 전기 검사 0/1/2 맵이다. 그 맵을 그린 이미지는 받지만 사진은 다른 과제다.'],
    ['서버가 멈추면?', '세 컨테이너 모두 자동 재시작, 상태 검사로 감시. 크레딧이 끝나면 멈추되 청구는 없다. 노트북 예비 구성도 있다.'],
    ['회원가입을 왜 승인제로?', '공장 품질 시스템이라 주소만 알면 누구나 들어오면 안 된다. 승인 전 로그인은 비밀번호가 맞을 때만 상태를 알려 계정 존재가 새지 않는다.'],
    ['재학습은 실제로 돌려 봤나?', '그렇다 — 이번 운영 모델이 그 결과다. 500건 누적 → 데이터 내려받기 → Colab 학습 → 승격 판정 → 교체 → 작업 자동 완료까지 끝까지 실행했다.'],
    ['테스트 214건은 무엇을 보나?', '전처리 비트 일치, 판정 경계값, 인증 · 권한, DB 마이그레이션 왕복, Grad-CAM 위치, 배포 구성(.env 가 이미지에 안 들어가는지)까지. SQLite 와 PostgreSQL 양쪽에서 돈다.'],
], [55 * mm, 105 * mm]))

# ── 문서 조립 ─────────────────────────────────────────────────────────────
doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                      topMargin=22 * mm, bottomMargin=22 * mm,
                      title='WaferAI 11월 1주 발표 자료', author='팀 Wafer-Eye')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
doc.addPageTemplates([PageTemplate(id='cover', frames=[frame], onPage=blank),
                      PageTemplate(id='body', frames=[frame], onPage=footer)])
doc.build(story)
print(f'생성 완료: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)')
