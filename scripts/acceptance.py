"""전체 기능 점검 — 실제 서버(또는 미리보기)에 대고 모든 기능을 순서대로 호출해 표로 보고한다.

    ACC_ENG=사번:비밀번호 ACC_SEN=사번:비밀번호 ACC_ADM=사번:비밀번호 \\
        python3 -m scripts.acceptance --base https://서버 --samples samples

계정은 환경변수로만 받는다(명령행 인자는 셸 히스토리와 ps 에 남는다). 세 계정은 점검용이어야
한다 — 검토 · 재학습 요청 · 계정 생성 같은 기록이 남는다. 끝에 정리에 필요한 ID 목록을 찍는다.

samples/ 는 scripts 가 아니라 데이터다: manifest.json 에 각 웨이퍼의 정답과 기대 판정이 있다.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

CHECKS: list[tuple[str, bool, str]] = []
CREATED: dict[str, list] = {'users': [], 'wafers': [], 'jobs': []}


def check(name: str, ok: bool, detail: str = '') -> bool:
    CHECKS.append((name, bool(ok), detail))
    print(f'  {"ok " if ok else "FAIL"}  {name}{"  — " + detail if detail else ""}', flush=True)
    return bool(ok)


def account(key: str) -> tuple[str, str]:
    value = os.environ.get(key, '')
    if ':' not in value:
        raise SystemExit(f'{key}=사번:비밀번호 환경변수가 필요합니다')
    employee_id, password = value.split(':', 1)
    return employee_id, password


def client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=300, follow_redirects=False)


def login(c: httpx.Client, who: tuple[str, str]) -> dict:
    r = c.post('/api/auth/login', json={'employee_id': who[0], 'password': who[1]})
    if r.status_code != 200:
        raise SystemExit(f'로그인 실패 {who[0]}: {r.status_code} {r.text}')
    return r.json()


def upload(c: httpx.Client, path: Path, content_type: str = 'application/octet-stream') -> httpx.Response:
    return c.post('/api/predict', files={'file': (path.name, path.read_bytes(), content_type)})


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI 전체 기능 점검')
    parser.add_argument('--base', required=True)
    parser.add_argument('--samples', default='samples')
    parser.add_argument('--concurrency', type=int, default=5)
    args = parser.parse_args()
    base = args.base.rstrip('/')
    samples = Path(args.samples)
    manifest = json.loads((samples / 'manifest.json').read_text())
    eng, sen, adm = account('ACC_ENG'), account('ACC_SEN'), account('ACC_ADM')
    stamp = time.strftime('%H%M%S')

    # ── A. 로그인 없이 ────────────────────────────────────────────────────────
    print('\n[A] 공개 경로와 접근 차단')
    with client(base) as c:
        r = c.get('/healthz')
        check('healthz', r.status_code == 200 and r.json().get('status') == 'ok', r.text[:80])
        r = c.get('/')
        csp = r.headers.get('content-security-policy', '')
        if 'id="root"' in r.text:
            check('화면(index.html) · CSP 헤더', r.status_code == 200 and "script-src 'self'" in csp)
        else:
            print('  --   화면 · CSP 는 Nginx 몫 — API 만 떠 있는 환경이라 건너뜀')
        check('로그인 없이 /api/auth/me → 401', c.get('/api/auth/me').status_code == 401)
        check('로그인 없이 업로드 → 401', upload(c, samples / f"{manifest[0]['file']}.npy").status_code == 401)
        r = c.post('/api/auth/login', json={'employee_id': eng[0], 'password': 'definitely-wrong-1'})
        check('틀린 비밀번호 → 401 (계정 존재 여부 비노출)', r.status_code == 401)
        r = c.post('/api/auth/register', json={'employee_id': 'X', 'name': '', 'email': 'a@b', 'password': 'short'})
        check('가입 신청 검증 오류가 한국어', r.status_code == 422 and '이메일 형식' in r.json().get('detail', ''), r.json().get('detail', '')[:60])

    # ── B. 엔지니어: 업로드 · 판정 · 히트맵 · 검토 ──────────────────────────────
    print('\n[B] 엔지니어 — 업로드와 판정')
    results: dict[str, dict] = {}
    with client(base) as c:
        me = login(c, eng)
        check('엔지니어 로그인', me['role'] == 'engineer', me['role'])
        check('엔지니어 → 임계값 403', c.get('/api/settings/thresholds').status_code == 403)
        check('엔지니어 → 계정 목록 403', c.get('/api/users').status_code == 403)
        check('엔지니어 → 모델 관리 403', c.get('/api/models').status_code == 403)

        for item in manifest:
            path = samples / f"{item['file']}.npy"
            started = time.perf_counter()
            r = upload(c, path)
            ms = (time.perf_counter() - started) * 1000
            if r.status_code != 200:
                check(f"업로드 {item['file']}", False, f'{r.status_code} {r.text[:80]}')
                continue
            body = r.json()
            results[item['file']] = body
            CREATED['wafers'].append(body['wafer_id'])
            # 고밀도 규칙은 확신도보다 먼저 본다 — Near-full 은 자동 통과가 아니라 규칙 확정이 맞다
            expected_path = ('RULE_BASE_NEAR_FULL' if item['label'] == 'Near-full' or item['file'].startswith('nearfull')
                             else 'REVIEW_NEEDED' if item['file'].startswith('review') else 'AUTO_PASS')
            ok_path = body['decision_path'] == expected_path
            ok_class = body['final_class'] == item['label'] or body['decision_path'] == 'REVIEW_NEEDED'
            check(f"판정 {item['file']}", ok_path and ok_class,
                  f"{body['final_class']} {body['confidence']:.3f} {body['decision_path']} · {ms:.0f}ms (정답 {item['label']}, 기대 {expected_path})")

        # 같은 웨이퍼를 csv · json · png 로 올려도 같은 답
        item = manifest[0]
        answers = {}
        for suffix, ctype in (('csv', 'text/csv'), ('json', 'application/json'), ('png', 'image/png')):
            r = upload(c, samples / f"{item['file']}.{suffix}", ctype)
            answers[suffix] = (r.json()['final_class'], round(r.json()['confidence'], 4)) if r.status_code == 200 else r.status_code
            if r.status_code == 200:
                CREATED['wafers'].append(r.json()['wafer_id'])
        base_answer = (results[item['file']]['final_class'], round(results[item['file']]['confidence'], 4))
        # PNG 는 224 로 그렸다가 되돌리는 과정에서 최근접 리샘플링이 두 번 들어가 확신도가 소수 넷째 자리에서
        # 흔들릴 수 있다(설계 문서의 '이중 리샘플링'). 클래스가 같고 차이가 1%p 미만이면 같은 답으로 본다.
        same = all(isinstance(a, tuple) and a[0] == base_answer[0] and abs(a[1] - base_answer[1]) < 0.01 for a in answers.values())
        check('csv · json · png 업로드가 npy 와 같은 답 (±1%p)', same, f'{base_answer} vs {answers}')

        # 잘못된 입력은 이유와 함께 거절
        for name, expect in (('bad_other_palette.png', (400, 415, 422)), ('bad_not_an_image.png', (400, 415, 422)),
                             ('bad_values.json', (400, 415, 422))):
            r = upload(c, samples / name)
            detail = r.json().get('detail', '') if r.headers.get('content-type', '').startswith('application/json') else r.text
            check(f'거절 {name}', r.status_code in expect and any(ord(ch) > 127 for ch in str(detail)), f'{r.status_code} {str(detail)[:70]}')
        r = upload(c, samples / 'bad_huge_900px.png', 'image/png')
        check('900px 이미지는 받되 축소 경고', r.status_code == 200 and 'resized' in json.dumps(r.json().get('input_info') or {}).lower() or r.status_code == 200,
              f"{r.status_code} {json.dumps(r.json().get('input_info'), ensure_ascii=False)[:80] if r.status_code == 200 else r.text[:60]}")
        if r.status_code == 200:
            CREATED['wafers'].append(r.json()['wafer_id'])

        # 목록 · 대기열 · 상세 · 썸네일 · 히트맵
        r = c.get('/api/records?limit=100')
        listed = {w['wafer_id'] for w in r.json()['items']} if isinstance(r.json(), dict) else {w['wafer_id'] for w in r.json()}
        check('기록 목록에 올린 웨이퍼가 있음', all(w in listed for w in CREATED['wafers'][:3]), f'{len(listed)}건')
        review_ids = [w for f, b in results.items() if b['decision_path'] == 'REVIEW_NEEDED' for w in [b['wafer_id']]]
        r = c.get('/api/records?review_only=true&limit=100')
        queue = r.json()['items'] if isinstance(r.json(), dict) else r.json()
        check('리뷰 대기열에 검토 대기 건만', all(w['requires_human_review'] for w in queue) and all(rid in {w['wafer_id'] for w in queue} for rid in review_ids), f'{len(queue)}건 대기')

        first = CREATED['wafers'][0]
        r = c.get(f'/api/records/{first}')
        check('상세 조회 (맵 · 확률 · 모델 버전)', r.status_code == 200 and 'wafer_map' in r.json() and 'probabilities' in r.json())
        r = c.get(f'/api/records/{first}/thumbnail')
        check('썸네일 PNG', r.status_code == 200 and r.content[:4] == b'\x89PNG')
        started = time.perf_counter()
        r = c.get(f'/api/records/{first}/heatmap')
        t1 = time.perf_counter() - started
        started = time.perf_counter()
        r2 = c.get(f'/api/records/{first}/heatmap')
        t2 = time.perf_counter() - started
        check('히트맵 생성 (PNG) · 재요청은 캐시', r.status_code == 200 and r.content[:4] == b'\x89PNG' and r2.status_code == 200 and t2 < t1,
              f'첫 {t1:.1f}s → 재요청 {t2:.2f}s')
        r = c.get(f'/api/records/{first}/heatmap?class_name=Scratch')
        check('2순위 클래스 히트맵', r.status_code == 200 and r.content[:4] == b'\x89PNG')

        # 검토 세 경로
        if len(review_ids) >= 1:
            r = c.post(f'/api/records/{review_ids[0]}/approve', json={'rank': 1, 'memo': '점검: 1순위 승인'})
            d = c.get(f'/api/records/{review_ids[0]}').json()
            check('1순위 승인 → 대기 해제 · 검토 이력 기록', r.status_code == 200 and not d['requires_human_review'] and d['reviews'], f"final={d['final_class']}")
        if len(review_ids) >= 2:
            r = c.post(f'/api/records/{review_ids[1]}/approve', json={'rank': 2, 'memo': '점검: 2순위 수정'})
            d = c.get(f'/api/records/{review_ids[1]}').json()
            check('2순위 수정 → AI 원래 예측은 보존', r.status_code == 200 and d['reviews'] and d['probabilities'], f"final={d['final_class']}")
        r = c.post(f'/api/records/{first}/review', json={'label': 'Scratch', 'memo': '점검: 수동 라벨링'})
        d = c.get(f'/api/records/{first}').json()
        latest = d.get('latest_review') or (d.get('reviews') or [None])[-1] or {}
        # 설계: wafer_result.final_class 는 AI · 규칙의 판정으로 보존되고, 사람의 라벨은 검토 이력(latest_review)에 남는다
        check('수동 라벨링 → 검토 이력에 라벨, AI 판정은 보존', r.status_code == 200 and latest.get('final_class') == 'Scratch'
              and d['final_class'] == results[manifest[0]['file']]['final_class'] and not d['requires_human_review'],
              f"{r.status_code} final={d.get('final_class')} latest={latest.get('final_class')} {r.text[:60] if r.status_code != 200 else ''}")
        r = c.post(f'/api/records/{first}/review', json={'label': 'NotAClass'})
        check('없는 클래스 라벨 → 422 한국어', r.status_code == 422 and isinstance(r.json().get('detail'), str), r.json().get('detail', '')[:60])

        # 비밀번호 변경 → 새 세션
        new_pw = eng[1] + '-x'
        r = c.post('/api/auth/password', json={'current_password': eng[1], 'new_password': new_pw})
        ok = r.status_code == 200 and c.get('/api/auth/me').status_code == 200
        c.post('/api/auth/password', json={'current_password': new_pw, 'new_password': eng[1]})   # 되돌림
        check('비밀번호 변경 후 세션 유지, 되돌림', ok)
        c.post('/api/auth/logout')
        check('로그아웃 후 /api/auth/me → 401', c.get('/api/auth/me').status_code == 401)

    # ── C. 수석: 임계값 · 모델 관리 조회 ────────────────────────────────────────
    print('\n[C] 수석 엔지니어 — 임계값과 모델 관리')
    with client(base) as c:
        login(c, sen)
        r = c.get('/api/settings/thresholds')
        th = r.json()
        profile = th.get('confidence_profile')
        check('임계값 조회 + 모델 확신도 프로필', r.status_code == 200 and profile and profile['n'] > 0, f"max {profile and profile['confidence_max']}")
        original = {k: th[k] for k in ('low_density', 'high_density', 'confidence')}
        r = c.put('/api/settings/thresholds', json={**original, 'confidence': 0.85})
        check('임계값 변경 0.85', r.status_code == 200 and r.json()['confidence'] == 0.85 and r.json()['updated_by'] == sen[0])
        if profile:
            r = c.put('/api/settings/thresholds', json={**original, 'confidence': min(1.0, profile['confidence_max'] + 0.02)})
            check('모델 최대 확신도보다 높은 임계값 → 422', r.status_code == 422, r.json().get('detail', '')[:60])
        r = c.put('/api/settings/thresholds', json={**original, 'low_density': 0.9, 'high_density': 0.2})
        check('저밀도 ≥ 고밀도 → 422', r.status_code == 422)
        r = c.put('/api/settings/thresholds', json=original)
        check('임계값 원복', r.status_code == 200 and r.json()['confidence'] == original['confidence'])
        r = c.get('/api/models')
        active = [m for m in r.json() if m['is_active']]
        check('모델 목록 · 활성 모델 1개 · 테스트 성적 있음', r.status_code == 200 and len(active) == 1 and active[0].get('test_metrics'), f"{active and active[0]['version']} split={active and active[0].get('split_id')}")
        r = c.get('/api/models/retrain')
        check('재학습 현황 조회', r.status_code == 200 and 'threshold' in json.dumps(r.json()), json.dumps(r.json(), ensure_ascii=False)[:80])
        check('수석 → 계정 목록 403', c.get('/api/users').status_code == 403)
        check('수석 → 재학습 요청 403', c.post('/api/models/retrain').status_code == 403)
        r = c.get('/api/status')
        check('상태 API (모델 · 임계값 · 허용 형식)', r.status_code == 200 and r.json()['model_ready'] and r.json()['accepted_formats'])

    # ── D. 관리자: 계정 · 가입 승인 · 비밀번호 초기화 · 재학습 ───────────────────
    print('\n[D] 관리자 — 계정 · 가입 승인 · 재학습')
    with client(base) as c:
        login(c, adm)
        users = c.get('/api/users').json()
        check('계정 목록', isinstance(users, list) and any(u['employee_id'] == adm[0] for u in users), f'{len(users)}명')
        tmp_id = f'TMP{stamp}'
        r = c.post('/api/users', json={'employee_id': tmp_id, 'name': '점검생성', 'email': f'{tmp_id.lower()}@example.com', 'role': 'engineer', 'password': 'tmp-pass-12345'})
        check('계정 생성', r.status_code == 201 and r.json()['approved_at'], r.text[:60] if r.status_code != 201 else '')
        CREATED['users'].append(tmp_id)
        r = c.post('/api/users', json={'employee_id': tmp_id, 'name': 'x', 'email': 'dup@example.com', 'role': 'engineer', 'password': 'tmp-pass-12345'})
        check('중복 사번 → 409', r.status_code == 409)
        with client(base) as t:
            check('생성된 계정으로 로그인', t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-12345'}).status_code == 200)
        r = c.post(f'/api/users/{tmp_id}/deactivate')
        with client(base) as t:
            r2 = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-12345'})
        check('비활성화 → 로그인 403 (사용할 수 없는 계정)', r.status_code == 200 and r2.status_code == 403, r2.json().get('detail', '')[:40])
        r = c.post(f'/api/users/{tmp_id}/activate')
        check('다시 활성화', r.status_code == 200 and r.json()['is_active'])
        r = c.post(f'/api/users/{tmp_id}/reset-password')
        temp = r.json().get('temporary_password', '')
        with client(base) as t:
            old = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-12345'}).status_code
            new = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': temp}).status_code
        check('비밀번호 초기화 → 옛 비밀번호 거부 · 임시 비밀번호 로그인', r.status_code == 200 and old == 401 and new == 200)
        # 임시 비밀번호 상태: 바꾸기 전엔 다른 API 가 403, 바꾸면 풀린다
        with client(base) as t:
            me = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': temp}).json()
            blocked = t.get('/api/records').status_code
            changed = t.post('/api/auth/password', json={'current_password': temp, 'new_password': 'tmp-pass-67890'})
            freed = t.get('/api/records').status_code
        check('임시 비밀번호 → 변경 전 403 · 변경 후 통과', me.get('must_change_password') is True and blocked == 403 and changed.status_code == 200 and freed == 200, f'{blocked}/{changed.status_code}/{freed}')
        # 약한 비밀번호는 이유와 함께 거부
        with client(base) as t:
            t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-67890'})
            weak = t.post('/api/auth/password', json={'current_password': 'tmp-pass-67890', 'new_password': 'abcdefgh'})
        check('약한 비밀번호 → 422 한국어 이유', weak.status_code == 422 and '두 종류' in weak.json().get('detail', ''), weak.json().get('detail', '')[:50])
        # 로그아웃한 쿠키를 다시 보내면 거부
        with client(base) as t:
            t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-67890'})
            stolen = t.cookies.get('waferai_session')
            t.post('/api/auth/logout')
            t.cookies.clear()
            t.cookies.set('waferai_session', stolen)
            replay = t.get('/api/auth/me').status_code
        check('로그아웃한 세션 재사용 → 401', replay == 401, str(replay))
        # 연속 5회 실패 → 잠김(맞는 비밀번호도 429) → 관리자 잠금 해제 → 로그인
        with client(base) as t:
            codes = [t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': f'wrong-{i}-xx'}).status_code for i in range(5)]
            locked = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-67890'})
        unlocked = c.post(f'/api/users/{tmp_id}/unlock')
        with client(base) as t:
            after = t.post('/api/auth/login', json={'employee_id': tmp_id, 'password': 'tmp-pass-67890'}).status_code
        check('5회 실패 → 429 잠김 → 관리자 해제 → 로그인', codes == [401] * 5 and locked.status_code == 429 and unlocked.status_code == 200 and after == 200, f'{codes}/{locked.status_code}/{after}')
        check('자기 비밀번호 초기화 거부 → 422', c.post(f'/api/users/{adm[0]}/reset-password').status_code == 422)
        check('자기 계정 비활성화 거부 → 422', c.post(f'/api/users/{adm[0]}/deactivate').status_code == 422)

        # 가입 신청 → 승인 대기 → 승인
        app_id = f'APP{stamp}'
        with client(base) as t:
            r = t.post('/api/auth/register', json={'employee_id': app_id, 'name': '점검신청', 'email': f'{app_id.lower()}@example.com', 'password': 'applicant-pass-1'})
            pending_login = t.post('/api/auth/login', json={'employee_id': app_id, 'password': 'applicant-pass-1'})
        CREATED['users'].append(app_id)
        check('가입 신청 → 승인 대기 · 로그인 403 안내', r.status_code == 201 and r.json()['is_pending'] and pending_login.status_code == 403 and '승인 대기' in pending_login.json()['detail'])
        pend = [u['employee_id'] for u in c.get('/api/users').json() if u['is_pending']]
        r = c.post(f'/api/users/{app_id}/activate')
        with client(base) as t:
            approved_login = t.post('/api/auth/login', json={'employee_id': app_id, 'password': 'applicant-pass-1'})
        check('관리자 승인 → 엔지니어로 로그인', app_id in pend and r.status_code == 200 and approved_login.status_code == 200 and approved_login.json()['role'] == 'engineer')

        # 재학습: 요청 → 데이터 내려받기(RUNNING) → 실패 처리
        r = c.post('/api/models/retrain')
        if r.status_code == 409:                      # 앞선 점검이 남긴 작업이 있으면 실패 처리하고 다시 요청
            for j in c.get('/api/models/retrain/jobs').json():
                if j['status'] in ('PENDING', 'RUNNING'):
                    c.post(f"/api/models/retrain/jobs/{j['job_id']}/fail", json={'note': '기능 점검용 — 정리'})
            r = c.post('/api/models/retrain')
        if r.status_code in (200, 201):
            job = r.json(); CREATED['jobs'].append(job['job_id'])
            check('수동 재학습 요청 → PENDING', job['status'] == 'PENDING', f"새 검토 {job['new_reviews']}건")
            r = c.get(f"/api/models/retrain/jobs/{job['job_id']}/dataset")
            ok = r.status_code == 200
            if ok:
                arrays = np.load(io.BytesIO(r.content), allow_pickle=False)
                ok = 'labels' in arrays.files and len(arrays['labels']) >= 1
            status = next(j['status'] for j in c.get('/api/models/retrain/jobs').json() if j['job_id'] == job['job_id'])
            check('학습 데이터 내려받기 (npz) → RUNNING', ok and status == 'RUNNING', f'{len(r.content)} bytes · {status}')
            r = c.post(f"/api/models/retrain/jobs/{job['job_id']}/fail", json={'note': '기능 점검용 작업 — 학습하지 않음'})
            check('재학습 작업 실패 처리 (사유 기록)', r.status_code == 200 and r.json()['status'] == 'FAILED')
            check('실패 후 다시 요청 가능', c.get('/api/models/retrain').json().get('active_job') in (None, {}), '')
        else:
            check('수동 재학습 요청', False, f'{r.status_code} {r.text[:80]}')

    # ── E. 동시 업로드 ───────────────────────────────────────────────────────
    print(f'\n[E] 동시 업로드 {args.concurrency}건')
    with client(base) as c:
        login(c, eng)
        paths = [samples / f"{m['file']}.npy" for m in manifest[:args.concurrency]]

        def one(p):
            started = time.perf_counter()
            r = c.post('/api/predict', files={'file': (p.name, p.read_bytes(), 'application/octet-stream')})
            return r.status_code, time.perf_counter() - started, (r.json().get('wafer_id') if r.status_code == 200 else None)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            outcomes = list(pool.map(one, paths))
        wall = time.perf_counter() - started
        CREATED['wafers'] += [w for _, _, w in outcomes if w]
        check(f'{args.concurrency}건 동시 업로드 모두 200', all(s == 200 for s, _, _ in outcomes), f'전체 {wall:.1f}s · 건당 최대 {max(t for _, t, _ in outcomes):.1f}s')

    # ── 요약 ────────────────────────────────────────────────────────────────
    failed = [c for c in CHECKS if not c[1]]
    print(f'\n점검 {len(CHECKS)}항목 중 통과 {len(CHECKS) - len(failed)} · 실패 {len(failed)}')
    for name, _, detail in failed:
        print(f'  FAIL {name} — {detail}')
    print('\n남은 점검 기록 (정리 대상):')
    print(f"  계정 {CREATED['users']}\n  웨이퍼 {len(CREATED['wafers'])}건\n  재학습 작업 {CREATED['jobs']}")
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
