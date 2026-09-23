"""화면 스크린샷을 자동으로 찍어 docs/figures/ui/ 에 저장한다.

    # 백엔드와 프론트엔드를 먼저 띄운 뒤
    WAFERAI_CAPTURE_ID=E0001 WAFERAI_CAPTURE_PASSWORD=... python3 -m scripts.capture_screens

보고서(scripts/build_report.py)의 부록 B 가 이 결과를 쓴다. 화면이 바뀌면 다시 돌려
갱신한다.

계정 정보는 인자로 받지 않고 환경변수로만 받는다. 명령행 인자는 셸 히스토리와
프로세스 목록(ps)에 그대로 남는다.

시스템에 설치된 Chrome 을 그대로 쓴다(channel='chrome'). Chromium 을 따로
내려받지 않아도 되고, 실제 사용자가 보는 렌더링과 같다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / 'docs/figures/ui'
VIEWPORT = {'width': 1440, 'height': 900}

#: 검토 대기 건은 화면을 대표하지 못하므로(비어 보임) 결함이 뚜렷한 건을 고른다.
PREFERRED_CARD = 'Scratch'


def capture(base_url: str, employee_id: str, password: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    def shoot(page, name: str, full_page: bool = False) -> None:
        target = OUTPUT_DIR / f'{name}.png'
        page.screenshot(path=str(target), full_page=full_page)
        saved.append(target)
        print(f'  저장 {target.relative_to(ROOT)}')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_context(viewport=VIEWPORT,
                                   device_scale_factor=2).new_page()   # 인쇄용 2배 해상도

        print('[1/5] 로그인 화면')
        page.goto(f'{base_url}/login', wait_until='networkidle')
        shoot(page, '01_login')

        page.fill('#employee-id', employee_id)
        page.fill('#password', password)
        page.click('button[type=submit]')
        page.wait_for_url(f'{base_url}/', timeout=15_000)
        page.wait_for_load_state('networkidle')

        print('[2/5] 대시보드')
        page.wait_for_selector('img[loading=lazy]', timeout=15_000)
        page.wait_for_timeout(1200)          # 썸네일이 다 들어오길 기다린다
        shoot(page, '02_dashboard')

        print('[3/5] 웨이퍼 상세 (Grad-CAM)')
        cards = page.locator('button:has(img)')
        index = 0
        for candidate in range(cards.count()):
            if PREFERRED_CARD.lower() in (cards.nth(candidate).inner_text() or '').lower():
                index = candidate
                break
        cards.nth(index).click()
        page.wait_for_selector('text=웨이퍼 상세 분석', timeout=15_000)
        # 히트맵은 지연 생성이라 첫 요청이 오래 걸린다. 이미지가 실제로 뜰 때까지 기다린다.
        page.wait_for_function(
            """() => {
                 const img = document.querySelector('img[alt="Grad-CAM 히트맵"]')
                 return img && img.complete && img.naturalWidth > 0
               }""", timeout=60_000)
        page.wait_for_timeout(600)           # 페이드인 완료
        shoot(page, '03_wafer_detail')

        page.keyboard.press('Escape')
        page.wait_for_timeout(400)

        print('[4/5] 리뷰 대기열')
        page.goto(f'{base_url}/review', wait_until='networkidle')
        page.wait_for_timeout(800)
        shoot(page, '04_review_queue')

        print('[5/5] 설정')
        page.goto(f'{base_url}/settings', wait_until='networkidle')
        page.wait_for_timeout(800)
        if page.locator('text=판정 임계값').count() == 0:
            print('  건너뜀 — 이 계정은 설정 권한이 없습니다 (senior_engineer 이상 필요)')
        else:
            shoot(page, '05_settings')

        browser.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 화면 캡처')
    parser.add_argument('--base-url', default='http://127.0.0.1:5173')
    args = parser.parse_args()

    employee_id = os.environ.get('WAFERAI_CAPTURE_ID')
    password = os.environ.get('WAFERAI_CAPTURE_PASSWORD')
    if not employee_id or not password:
        raise SystemExit(
            '계정 정보가 없습니다. 환경변수로 넘겨주세요:\n'
            '  WAFERAI_CAPTURE_ID=사번 WAFERAI_CAPTURE_PASSWORD=비밀번호 \\\n'
            '      python3 -m scripts.capture_screens\n'
            '설정 화면까지 담으려면 senior_engineer 이상 계정을 쓰세요.')

    try:
        saved = capture(args.base_url, employee_id, password)
    except Exception as error:
        raise SystemExit(f'캡처에 실패했습니다: {type(error).__name__}: {error}\n'
                         '  백엔드(8000)와 프론트엔드(5173)가 떠 있는지 확인하세요.') from error

    print(f'\n완료: {len(saved)}장')
    if not saved:
        sys.exit(1)


if __name__ == '__main__':
    main()
