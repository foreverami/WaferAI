"""11/16 성능 개선 보고 PDF — 무엇을 바꿨고, 얼마나 좋아졌고, 어떻게 확인하는지.

    python3 -m scripts.build_improvement_report      # → docs/WaferAI_개선보고_1116.pdf

수치는 docs/calibration_report.json (scripts/calibrate.py 가 만든 측정 결과)에서 읽는다.
화면 그림은 docs/figures/ui/improve_*.png. 모양은 build_weekly_brief.py 와 같다.
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
OUT = ROOT / 'docs/WaferAI_개선보고_1116.pdf'
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
    canvas.drawString(25 * mm, 12 * mm, 'WaferAI · Fab AI Inspector — 성능 개선 보고 (11/16) · 팀 Wafer-Eye')
    canvas.drawRightString(A4[0] - 25 * mm, 12 * mm, str(doc.page))
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(25 * mm, 16 * mm, A4[0] - 25 * mm, 16 * mm)
    canvas.restoreState()


def blank(canvas, doc):
    pass


def ok(text):
    return f'<font color="#15803D"><b>{text}</b></font>'


def say_box(text, title='확인할 것'):
    return say(text, title)


def figure(name, caption, width=160 * mm):
    path = UI / name
    from PIL import Image as PILImage

    w, h = PILImage.open(path).size
    return KeepTogether([Image(str(path), width=width, height=width * h / w),
                         P(caption, 'note')])


def pct(value, digits=2):
    return f'{value * 100:.{digits}f}%'


cal = REPORT['calibration']
before = REPORT['effect']['before']['natural']
after = REPORT['effect']['after']['natural']
same_global = REPORT['effect']['calibrated_same_review_global']['natural']
ood = REPORT['ood']
pal = REPORT['palettes']

story = []

# ── 표지 ──────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 45 * mm),
    P('SW 캡스톤디자인 · 개선 작업 보고', 'subtitle'),
    P('WaferAI 성능 개선 보고', 'title'),
    Spacer(1, 3 * mm),
    P('판정 보정 · 엉뚱한 입력 감지 · 색상표 지원 · 화면 · 운영 준비', 'subtitle'),
    Spacer(1, 16 * mm),
]
story.append(table([
    ['항목', '내용'],
    ['작성일', '2026년 11월 16일'],
    ['범위', '11/04 "디벨롭할 부분" 목록 전체 — 반영한 것, 준비만 한 것, 결정이 필요한 것을 나눠 적었다'],
    ['측정 원칙', '맞추는 것은 검증 분할(17,309건), 효과는 학습에도 보정에도 쓰지 않은 테스트 셋(17,504건)에서만'],
    ['운영 서버', '아직 반영 전 — 7쪽의 명령 한 줄로 반영한다 (자동 모드에서 서버 배포가 막혀 있음)'],
], [30 * mm, 130 * mm]))
story.append(NextPageTemplate('body'))
story.append(PageBreak())

# ── 1. 한 장 요약 ─────────────────────────────────────────────────────────
story.append(P('1. 한 장 요약', 'h1'))
S['kpi'] = style('k2', 13, color=BRAND, space_after=0, alignment=TA_CENTER)
story.append(kpis([
    (f"{before['missed_defect']}→{after['missed_defect']}", '결함을 정상으로 내보냄 (건, 테스트 17,504)'),
    (f"{before['escaped']}→{after['escaped']}", '틀린 채 자동 통과 (건)'),
    (f"{cal['ece']['test_before']:.2f}→{cal['ece']['test_after']:.2f}", '확신도 보정 오차 (ECE)'),
    ('600/600', '가짜 입력 감지 (실제 맵 오탐 0.02%)'),
    ('4종', '알려진 색상표 100% 복원'),
]))
done = ok('반영')
story.append(table([
    ['11/04 목록', '상태', '내용'],
    ['로그인 보호 패치 서버 반영', '준비', '코드 · 테스트 완료. 7쪽 명령으로 반영 (모델 파일도 함께 올라감)'],
    ['DB 자동 백업', done, 'compose 의 backup 서비스가 24시간마다 덤프, 14개 보관. 화면에서 마지막 백업 확인'],
    ['프론트엔드 경고', done, '경고 7건 → 0건 (상태 갱신 경고 · 안 쓰는 import · 빠른 새로고침 경고)'],
    ['결함 누락 줄이기 · 클래스별 임계값', done, f"결함 누락 {before['missed_defect']} → {after['missed_defect']}건. 단, 클래스별 기준 자체의 몫은 없었음(2쪽)"],
    ['확신도 보정', done, f"온도 T = {cal['temperature']} — 확신도 0.98 이 실제로 98% 맞게 됨"],
    ['약한 클래스 보강 (재학습)', '준비', '학습 옵션 --oversample 추가. GPU(Colab) 학습은 아직 안 돌림'],
    ['엉뚱한 입력 감지', done, '웨이퍼 모양이 아니면 "판정 불가" 로 사람에게. 가짜 600장 전부 감지'],
    ['성능 추이 그래프 (화면 5)', done, '모델 관리 화면 — 주별 판정 경로 + 검토 결과와 AI 일치율'],
    ['다른 색상표 이미지', done, 'viridis · 회색조 · 흰 배경 회색조는 바로, 처음 보는 3색은 추정 후 검토'],
    ['일괄 업로드 · CSV 내보내기', done, '여러 파일 한 번에 올리고 결과 요약. 기록 · 대기열 CSV (엑셀 한글 OK)'],
    ['감사 로그 화면', done, 'audit_events 테이블 + 계정 › 보안 기록 (관리자)'],
    ['재학습 자동화 (유료 GPU)', '결정 필요', '비용이 드는 일이라 하지 않음. 9쪽'],
    ['모니터링 · 알림', '준비', '화면의 서버 상태 카드는 반영. Azure 경고 규칙은 스크립트만 (메일 주소 필요)'],
    ['크레딧 이후 · Sensor AI · 실물 사진', '결정 필요', '9쪽'],
], [44 * mm, 18 * mm, 98 * mm]))

# ── 2. 판정 보정 ──────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('2. 확률 보정과 판정 기준 — 결함 누락 절반', 'h1'))
story.append(P(
    'Focal Loss 로 학습한 모델은 확신도를 낮게 말해 1순위 확신도가 0.90 – 0.92 에 몰려 있었다. 확률 p 를 '
    f"p^(1/T) 로 다시 정규화하는 온도 보정(T = {cal['temperature']})을 넣었다. 1순위가 그대로라 정확도는 "
    "변하지 않고, '확신도 0.98' 이 실제로 98% 맞는다는 뜻이 된다. 그 위에서 판정 기준을 검증 분할로 다시 "
    '맞췄다 — 결함 누락 1건을 유형 오류 10건, 검토 1건을 유형 오류 0.2건으로 놓고 비용을 최소로 하는 점이다.'))
story.append(table([
    ['테스트 셋 17,504건', '보정 전 (0.80)', '지금 (보정 + 권장 기준)'],
    ['검토로 가는 비율', pct(before['review_rate']), pct(after['review_rate'])],
    ['틀린 채 자동 통과', f"{before['escaped']}건", ok(f"{after['escaped']}건")],
    ['결함을 정상으로 내보냄', f"{before['missed_defect']}건", ok(f"{after['missed_defect']}건")],
    ['자동 통과의 정확도', pct(before['unattended_accuracy']), pct(after['unattended_accuracy'])],
    ['확신도 보정 오차 (ECE)', str(cal['ece']['test_before']), str(cal['ece']['test_after'])],
], [56 * mm, 46 * mm, 58 * mm], aligns={1: 'RIGHT', 2: 'RIGHT'}))
story.append(P('고를 수 있는 운영점', 'h2'))
story.append(table([
    ['운영점', '검토 비율', '틀린 자동 통과', '결함 누락', '비고'],
    ['보정 전 0.80 (지난주까지)', '3.58%', '130건', '19건', ''],
    ['보정 후, 같은 검토량 (0.94)', '3.36%', '134건', '20건', '보정만으로는 줄지 않는다'],
    ['권장 (지금 기본값)', pct(after['review_rate']), f"{after['escaped']}건", f"{after['missed_defect']}건", '검토 +약 385건 / 17,504건'],
    ['엄격', '9.60%', '46건', '2건', '--review-cost 0.1'],
], [46 * mm, 24 * mm, 28 * mm, 22 * mm, 40 * mm], aligns={1: 'RIGHT', 2: 'RIGHT', 3: 'RIGHT'}))
story.append(say_box(
    f"솔직한 해석 — 개선은 '검토를 약 2%p 더 하고, 틀린 무인 통과와 결함 누락을 절반으로 줄인' 운영점 이동이다. "
    f"같은 검토량에서 단일 임계값(보정 후 {REPORT['same_review_global_threshold']})을 써도 결과가 같았다 "
    f"({same_global['escaped']}건 · {same_global['missed_defect']}건). 즉 클래스별 기준 자체의 몫은 이 모델에서는 "
    '없었다(권장값이 대부분 0.98 로 같다). 보정이 한 일은 그 운영점을 해석 가능한 숫자로 만든 것이다. '
    '검토량을 더 감수할지는 운영 정책이라, 설정 화면에서 클래스별 기준을 끄고 단일 임계값으로 돌아갈 수 있게 두었다.',
    '해석'))

# ── 3. 입력 감지 ──────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('3. 웨이퍼처럼 생기지 않은 입력 — "판정 불가"', 'h1'))
story.append(P(
    '모델은 무엇을 넣든 9개 중 하나를 고른다. 체크무늬 배열을 Random 98% 로 판정하는 식이다. 그래서 모델 앞에서 '
    '모양을 본다 — 내용 영역에 내접한 타원과 다이 영역의 일치도, 다이 비율, 다이 수. 실제 웨이퍼 맵은 이 값이 아주 '
    '좁게 모여 있다(타원 일치도 99.95% 가 0.905 이상). 걸린 입력은 거부하지 않고 사람에게 보낸다 — 형식은 맞으니 '
    '사람이 보고 판단할 수 있다.'))
rows = [['입력', '감지', '검사가 없었다면 자동 통과']]
for name, r in ood['synthetic'].items():
    rows.append([name, f"{r['caught']} / {r['n']}", f"{r['auto_pass_without_check']}장"])
rows.append(['실제 웨이퍼 맵 (학습 · 검증 · 테스트 전체)', f"{ood['real_flagged']} / {ood['real_maps']:,}",
             f"오탐 {ood['real_flagged'] / ood['real_maps']:.2%} · 테스트 셋에서 {ood['real_flagged_test']}장"])
story.append(table(rows, [70 * mm, 35 * mm, 55 * mm], aligns={1: 'RIGHT', 2: 'RIGHT'}))
story.append(figure('improve_out_of_scope.png', '체크무늬 배열 — 모델은 Random 98.4% 로 판정했지만 "판정 불가" 로 사람에게 넘어가고, 이유가 빨간 상자에 보인다.', 150 * mm))

# ── 4. 색상표 ─────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('4. 다른 색상표 이미지', 'h1'))
story.append(P(
    '예전에는 학습 색(검정/초록/노랑)이 아니면 모두 거절했다. 이제 확신의 정도에 따라 셋으로 나눈다. 알려진 '
    '색상표는 표의 순서대로 바꿔 읽고, 처음 보는 3색은 배경 = 네 모서리 색, 결함 = 다이 중 적은 쪽으로 추정한 '
    '뒤 반드시 사람 검토로 보낸다. 세 색으로 설명되지 않는 이미지(사진, 그라데이션)는 여전히 거절한다.'))
names = {'training': '학습 색', 'viridis': 'viridis', 'gray': '회색조 (검정 배경)', 'gray_r': '회색조 (흰 배경)',
         'random': '처음 보는 3색 (무작위)'}
rows = [['테스트 맵 400장을 이 색으로 그리면', '정확 복원', '추정 → 검토', '거부', '잘못 읽고 검토도 안 감']]
for key, r in pal.items():
    rows.append([names.get(key, key), str(r['restored_exactly']), str(r['guessed']), str(r['rejected']),
                 ok(str(r.get('wrong_unflagged', 0)))])
story.append(table(rows, [58 * mm, 24 * mm, 26 * mm, 16 * mm, 36 * mm], aligns={1: 'RIGHT', 2: 'RIGHT', 3: 'RIGHT', 4: 'RIGHT'}))
story.append(say_box(
    '측정 중 버그 두 개를 찾아 고쳤다. ① 흰 배경 회색조는 검정 배경 회색조와 같은 세 색을 반대 순서로 써서 0/400 이 '
    '거꾸로 읽혔다 → 배경 위치(모서리)로 가른다. ② 무작위 색 중 4장이 우연히 학습 색과 비슷해 배경을 결함으로 읽고도 '
    '검토로 가지 않았다 → 학습 색과의 평균 차이가 크면 색상표 해석으로 넘긴다. 지금은 잘못 읽은 이미지가 모두 '
    '사람 검토로 간다(마지막 열 0).', '찾아서 고친 것'))

# ── 5. 화면 ───────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('5. 새 화면', 'h1'))
story.append(figure('improve_batch_upload.png', '대시보드 — 파일 5개를 한 번에 올린 결과 요약. 자동 통과 · 검토 필요 · 판정 불가 · 거절(이유 포함)이 한눈에 보인다. 오른쪽 위 "기록 CSV".', 155 * mm))
story.append(figure('improve_models.png', '모델 관리 — 성능 추이(주별 경로 + AI 일치율), 확률 보정 효과, 서버 상태(관리자). 그래프는 로컬 미리보기 데이터라 한 주뿐이다.', 155 * mm))
story.append(PageBreak())
story.append(figure('improve_settings.png', '설정 — 모델 권장 클래스별 기준. 켜 두면 아래 단일 임계값 슬라이더는 쓰이지 않는다.', 155 * mm))
story.append(figure('improve_audit.png', '계정 › 보안 기록 (관리자) — 로그인 실패 · 잠금 · 임시 비밀번호 발급 · 가입 승인. 실패와 잠금은 빨간 글씨.', 155 * mm))

# ── 6. 운영 ───────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(P('6. 운영 준비', 'h1'))
story.append(table([
    ['항목', '내용', '상태'],
    ['자동 DB 백업', 'compose 에 backup 서비스 추가 — 24시간마다 pg_dump, 최근 14개 보관(.env 로 조정). 서버 cron 불필요', done],
    ['서버 상태 화면', '모델 관리 › 서버 상태 — 디스크 남은 공간, 마지막 백업 시각 · 크기, 36시간 넘으면 "확인 필요"', done],
    ['감사 기록', 'audit_events 테이블(마이그레이션 c4e8a1b3d5f7). 요청 세션이 끝난 뒤 같은 연결로 써서, 실패한 로그인도 남고 SQLite 잠금도 없다', done],
    ['배포 스크립트', 'deploy/deploy_update.sh — 코드 + (바뀐 경우) 모델 파일을 임시 이름으로 올려 바꾸고 다시 띄움', '준비'],
    ['Azure 경고', 'deploy/azure_alerts.sh 메일주소 — 서버 꺼짐 · CPU 85% · 메모리 300MB 미만이면 메일', '준비'],
    ['재학습 옵션', 'scripts/train.py --oversample Loc=2,Scratch=2,Donut=3,Edge-Loc=1.5 — 약한 클래스를 더 자주 보여 줌', '준비'],
    ['모델 파일', f"보정값을 심어 새 해시 9f11749a764f (가중치 동일 확인). 이전 파일은 models/backup_2d1559ce7d73.pth 로 보관", done],
], [32 * mm, 108 * mm, 20 * mm]))

# ── 7. 검증과 반영 ─────────────────────────────────────────────────────────
story.append(P('7. 검증과 운영 서버 반영', 'h1'))
story.append(table([
    ['검증', '결과'],
    ['자동 테스트 (SQLite)', '262건 통과 (235 → 262, 새 기능 27건)'],
    ['자동 테스트 (PostgreSQL 16 · GitHub Actions)', 'push 후 CI 결과로 확인 — 보고 메시지에 적음'],
    ['프론트엔드 lint · 빌드', '경고 0 · 빌드 성공'],
    ['로컬 미리보기 전 기능 점검', '76 / 76 통과 (운영에서는 화면 CSP 1항목이 더해져 77)'],
    ['브라우저 확인', '대시보드 · 판정 불가 상세 · 설정 · 모델 관리 · 보안 기록 — 5쪽 그림'],
], [70 * mm, 90 * mm]))
story.append(say_box(
    '운영 서버에는 아직 반영하지 않았다 — 자동 모드에서 서버 배포 명령이 막혀 있다. 맥 터미널에서 '
    '<b>sh deploy/deploy_update.sh</b> 한 줄이면 코드와 새 모델 파일이 올라가고 마이그레이션 두 개(로그인 보호 · '
    '감사 기록)가 자동 적용된다. 반영 뒤 점검 스크립트(scripts/acceptance.py)를 다시 돌리면 77항목을 확인한다.',
    '반영 방법'))

# ── 8. 직접 확인하는 법 ───────────────────────────────────────────────────
story.append(P('8. 직접 확인하는 법', 'h1'))
story += bullet([
    '<b>로컬</b> — 터미널 두 개: <font face="Courier">python3 -m scripts.serve_preview</font> 와 '
    '<font face="Courier">npm --prefix frontend run dev</font> → http://localhost:5173 (계정은 tests/conftest.py)',
    '<b>판정 불가</b> — samples/oos_checkerboard.json 업로드 → 리뷰 대기열에 "판정 불가 · 확인"',
    '<b>색상표</b> — samples/palette_viridis.png 업로드 → 상세의 "색 체계 viridis" · 경고. samples/bad_photo_like.png 는 거절',
    '<b>일괄 업로드</b> — 대시보드에서 파일 여러 개 선택 → 결과 요약 상자. "기록 CSV" 를 엑셀로 열어 한글 확인',
    '<b>보정 효과</b> — 모델 관리 › 확률 보정 · 판정 기준 표. 숫자의 원본은 docs/calibration_report.json',
    '<b>다시 재기</b> — <font face="Courier">python3 -m scripts.calibrate</font> (확률 캐시가 있으면 2분 안팎)',
])

# ── 9. 결정이 필요한 것 ───────────────────────────────────────────────────
story.append(P('9. 하지 않은 것과 결정이 필요한 것', 'h1'))
story.append(table([
    ['항목', '왜 하지 않았나', '필요한 결정'],
    ['약한 클래스 재학습 실행', '8GB 맥에서 학습은 예전에 메모리 부족으로 멈춘 적이 있다. Colab GPU 가 필요하고 Drive 업로드 등 사용자 작업이 든다',
     '돌릴지 — 돌리면 승격 기준을 넘을 때만 교체'],
    ['재학습 완전 자동화', 'GPU 를 상시 쓰려면 유료 클라우드 GPU 가 필요하다', '비용을 쓸지'],
    ['Azure 경고 규칙 생성', '사용자의 클라우드 계정에 규칙을 만들고 메일 주소가 필요하다', '받을 메일 주소'],
    ['1월 중순 크레딧 이후', '운영을 이어갈지는 비용 문제', '계속 운영 / 백업 후 정리'],
    ['Sensor AI', '1학기 설계에 있었지만 이번 학기 범위에서 뺐다', '교수님 확인'],
    ['실물 웨이퍼 사진', 'WM-811K 는 전기 검사 맵이라 사진은 데이터부터 새로 필요', '별도 과제로 둘지'],
], [38 * mm, 78 * mm, 44 * mm]))

doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                      topMargin=22 * mm, bottomMargin=22 * mm,
                      title='WaferAI 성능 개선 보고 (11/16)', author='팀 Wafer-Eye')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
doc.addPageTemplates([PageTemplate(id='cover', frames=[frame], onPage=blank),
                      PageTemplate(id='body', frames=[frame], onPage=footer)])
doc.build(story)
print(f'생성 완료: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)')
