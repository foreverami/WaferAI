import unittest

from tests.conftest import ADMIN, ENGINEER, SENIOR, ApiTestCase
from waferai.auth import (create_access_token, decode_access_token, hash_password,
                          verify_password)
from waferai.models import Role


class PasswordHashingTests(unittest.TestCase):
    def test_round_trip(self):
        digest = hash_password('correct horse battery')
        self.assertTrue(verify_password('correct horse battery', digest))
        self.assertFalse(verify_password('wrong password', digest))

    def test_hash_is_salted(self):
        """같은 비밀번호라도 해시가 달라야 레인보우 테이블이 무력해진다."""
        self.assertNotEqual(hash_password('same-password'), hash_password('same-password'))

    def test_plaintext_never_appears_in_hash(self):
        self.assertNotIn('supersecret', hash_password('supersecret-1234'))

    def test_long_korean_password_is_not_truncated(self):
        """bcrypt 72바이트 한계. 한글은 글자당 3바이트라 24자면 닿는다.

        자르고 넘기면 뒤쪽이 검증에 쓰이지 않아 비밀번호가 사실상 짧아진다.
        """
        base = '비밀번호를아주길게설정하는경우에도반드시안전해야만합니다'    # 29자 = 87바이트
        self.assertGreater(len(base.encode('utf-8')), 72)
        digest = hash_password(base)
        self.assertTrue(verify_password(base, digest))
        self.assertFalse(verify_password(base + '다른뒷부분', digest))

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            hash_password('short')

    def test_malformed_hash_does_not_raise(self):
        self.assertFalse(verify_password('anything', 'not-a-bcrypt-hash'))


class TokenTests(unittest.TestCase):
    SECRET = 'unit-test-secret-key-at-least-32-bytes'

    def test_round_trip(self):
        token = create_access_token('E0001', self.SECRET, 60)
        self.assertEqual(decode_access_token(token, self.SECRET), 'E0001')

    def test_wrong_secret_rejected(self):
        token = create_access_token('E0001', self.SECRET, 60)
        self.assertIsNone(decode_access_token(token, 'different-secret'))

    def test_expired_token_rejected(self):
        self.assertIsNone(decode_access_token(
            create_access_token('E0001', self.SECRET, -1), self.SECRET))

    def test_garbage_rejected(self):
        self.assertIsNone(decode_access_token('not.a.token', self.SECRET))


class RoleTests(unittest.TestCase):
    def test_higher_roles_cover_lower(self):
        self.assertTrue(Role.ADMIN.covers(Role.ENGINEER))
        self.assertTrue(Role.ADMIN.covers(Role.SENIOR_ENGINEER))
        self.assertTrue(Role.SENIOR_ENGINEER.covers(Role.ENGINEER))

    def test_lower_roles_do_not_cover_higher(self):
        self.assertFalse(Role.ENGINEER.covers(Role.SENIOR_ENGINEER))
        self.assertFalse(Role.SENIOR_ENGINEER.covers(Role.ADMIN))


class LoginTests(ApiTestCase):
    def test_login_sets_httponly_cookie(self):
        response = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': ENGINEER['password']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['employee_id'], ENGINEER['employee_id'])

        header = response.headers.get('set-cookie', '')
        self.assertIn('httponly', header.lower())
        self.assertIn('samesite', header.lower())

    def test_password_never_returned(self):
        """해시도 평문도 응답에 실려서는 안 된다."""
        response = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': ENGINEER['password']})
        self.assertNotIn(ENGINEER['password'], response.text)
        self.assertNotIn('password_hash', response.text)
        self.assertNotIn('$2b$', response.text)          # bcrypt 해시 접두사

    def test_wrong_password_rejected(self):
        response = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': 'wrong-password'})
        self.assertEqual(response.status_code, 401)

    def test_unknown_and_wrong_password_are_indistinguishable(self):
        """어느 쪽이 틀렸는지 알려주면 사번을 열거할 수 있다."""
        unknown = self.client.post('/api/auth/login', json={
            'employee_id': 'NOBODY', 'password': 'whatever-1234'})
        wrong = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': 'wrong-password'})
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.json()['detail'], wrong.json()['detail'])

    def test_deactivated_account_cannot_log_in(self):
        """비밀번호까지 맞은 본인에게는 403 으로 상태를 알려준다. 틀리면 여느 때처럼 401 이다."""
        self.login(ADMIN)
        self.client.post(f"/api/users/{ENGINEER['employee_id']}/deactivate")
        self.logout()
        response = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': ENGINEER['password']})
        self.assertEqual(response.status_code, 403)
        self.assertIn('사용할 수 없는 계정', response.json()['detail'])
        response = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': 'wrong-password-1'})
        self.assertEqual(response.status_code, 401)

    def test_me_requires_login(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_logout_clears_session(self):
        self.login(ENGINEER)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_tampered_cookie_rejected(self):
        self.login(ENGINEER)
        # 유효한 쿠키를 비우고 변조 쿠키만 보낸다. 같은 이름으로 set 만 하면 httpx 버전에 따라
        # 두 쿠키가 함께 전송되어 서버가 유효한 쪽을 먼저 읽을 수 있다 (CI 에서만 실패했던 원인).
        self.client.cookies.clear()
        self.client.cookies.set('waferai_session', 'forged.token.value')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)


class PasswordChangeTests(ApiTestCase):
    def test_change_password_then_login_with_new_one(self):
        self.login(ENGINEER)
        response = self.client.post('/api/auth/password', json={
            'current_password': ENGINEER['password'], 'new_password': 'brand-new-pass-99'})
        self.assertEqual(response.status_code, 200, response.text)

        self.logout()
        old = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': ENGINEER['password']})
        self.assertEqual(old.status_code, 401)
        new = self.client.post('/api/auth/login', json={
            'employee_id': ENGINEER['employee_id'], 'password': 'brand-new-pass-99'})
        self.assertEqual(new.status_code, 200)

    def test_wrong_current_password_rejected(self):
        self.login(ENGINEER)
        response = self.client.post('/api/auth/password', json={
            'current_password': 'not-the-right-one', 'new_password': 'brand-new-pass-99'})
        self.assertEqual(response.status_code, 401)

    def test_reusing_same_password_rejected(self):
        self.login(ENGINEER)
        response = self.client.post('/api/auth/password', json={
            'current_password': ENGINEER['password'], 'new_password': ENGINEER['password']})
        self.assertEqual(response.status_code, 422)

    def test_short_new_password_rejected(self):
        self.login(ENGINEER)
        response = self.client.post('/api/auth/password', json={
            'current_password': ENGINEER['password'], 'new_password': 'short'})
        self.assertEqual(response.status_code, 422)


class RoleEnforcementTests(ApiTestCase):
    def test_engineer_cannot_read_thresholds(self):
        self.login(ENGINEER)
        self.assertEqual(self.client.get('/api/settings/thresholds').status_code, 403)

    def test_senior_can_read_and_write_thresholds(self):
        self.login(SENIOR)
        self.assertEqual(self.client.get('/api/settings/thresholds').status_code, 200)
        response = self.client.put('/api/settings/thresholds',
                                   json={'confidence': 0.9, 'high_density': 0.8})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['confidence'], 0.9)
        self.assertEqual(response.json()['updated_by'], SENIOR['employee_id'])

    def test_senior_cannot_manage_users(self):
        self.login(SENIOR)
        self.assertEqual(self.client.get('/api/users').status_code, 403)

    def test_admin_can_manage_users(self):
        self.login(ADMIN)
        self.assertEqual(self.client.get('/api/users').status_code, 200)
        response = self.client.post('/api/users', json={
            'employee_id': 'N0001', 'name': '신입', 'email': 'new@example.com',
            'role': 'engineer', 'password': 'new-user-pass-1'})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn('new-user-pass-1', response.text)
        self.assertNotIn('password_hash', response.text)
        self.assertNotIn('$2b$', response.text)

    def test_admin_covers_lower_role_endpoints(self):
        """상위 등급은 하위 등급 기능도 쓸 수 있어야 한다."""
        self.login(ADMIN)
        self.assertEqual(self.client.get('/api/settings/thresholds').status_code, 200)

    def test_duplicate_employee_id_rejected(self):
        self.login(ADMIN)
        payload = {'employee_id': ENGINEER['employee_id'], 'name': '중복',
                   'email': 'dup@example.com', 'role': 'engineer',
                   'password': 'another-pass-123'}
        self.assertEqual(self.client.post('/api/users', json=payload).status_code, 409)

    def test_admin_cannot_lock_themselves_out(self):
        self.login(ADMIN)
        response = self.client.post(f"/api/users/{ADMIN['employee_id']}/deactivate")
        self.assertEqual(response.status_code, 422)

    def test_deactivated_account_can_be_reactivated(self):
        """비활성화는 되돌릴 수 있어야 한다. 그래야 화면에서 한 번 눌러도 사고가 아니다."""
        self.login(ADMIN)
        target = ENGINEER['employee_id']
        self.assertEqual(self.client.post(f'/api/users/{target}/deactivate').status_code, 200)
        self.logout()
        response = self.client.post('/api/auth/login', json={
            'employee_id': target, 'password': ENGINEER['password']})
        self.assertEqual(response.status_code, 403)

        self.login(ADMIN)
        response = self.client.post(f'/api/users/{target}/activate')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['is_active'])
        self.logout()
        self.login(ENGINEER)                      # 다시 로그인된다 (login 이 200 을 확인한다)

    def test_senior_cannot_reactivate(self):
        self.login(SENIOR)
        response = self.client.post(f"/api/users/{ENGINEER['employee_id']}/activate")
        self.assertEqual(response.status_code, 403)

    def test_invalid_thresholds_rejected(self):
        self.login(SENIOR)
        response = self.client.put('/api/settings/thresholds',
                                   json={'low_density': 0.9, 'high_density': 0.2,
                                         'confidence': 0.8})
        self.assertEqual(response.status_code, 422)



class SignupTests(ApiTestCase):
    """가입 신청 → 승인 대기 → 관리자 승인 → 로그인."""

    NEW = {'employee_id': 'N0100', 'name': '신청자', 'email': 'n0100@example.com',
           'department': '품질팀', 'password': 'applicant-pass-1'}

    def test_signup_creates_pending_account_that_cannot_log_in(self):
        response = self.client.post('/api/auth/register', json=self.NEW)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertFalse(body['is_active'])
        self.assertTrue(body['is_pending'])
        self.assertEqual(body['role'], 'engineer')
        self.assertNotIn(self.NEW['password'], response.text)

        response = self.client.post('/api/auth/login', json={
            'employee_id': 'N0100', 'password': self.NEW['password']})
        self.assertEqual(response.status_code, 403)
        self.assertIn('승인 대기', response.json()['detail'])
        # 비밀번호가 틀리면 승인 대기 여부도 알려주지 않는다
        response = self.client.post('/api/auth/login', json={
            'employee_id': 'N0100', 'password': 'wrong-password-1'})
        self.assertEqual(response.status_code, 401)

    def test_signup_cannot_choose_a_role(self):
        response = self.client.post('/api/auth/register', json={**self.NEW, 'role': 'admin'})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['role'], 'engineer')

    def test_admin_approval_enables_login(self):
        self.client.post('/api/auth/register', json=self.NEW)
        self.login(ADMIN)
        pending = [u['employee_id'] for u in self.client.get('/api/users').json() if u['is_pending']]
        self.assertEqual(pending, ['N0100'])
        response = self.client.post('/api/users/N0100/activate')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['is_pending'])
        self.assertIsNotNone(response.json()['approved_at'])
        self.logout()

        self.login({'employee_id': 'N0100', 'password': self.NEW['password']})
        self.assertEqual(self.client.get('/api/auth/me').json()['role'], 'engineer')

    def test_deactivated_account_is_not_pending(self):
        """관리자가 만든 뒤 비활성화한 계정은 승인 대기가 아니다. 승인 목록에 섞이면 안 된다."""
        self.login(ADMIN)
        self.client.post(f"/api/users/{ENGINEER['employee_id']}/deactivate")
        users = {u['employee_id']: u for u in self.client.get('/api/users').json()}
        self.assertFalse(users[ENGINEER['employee_id']]['is_pending'])
        self.assertFalse(users[ENGINEER['employee_id']]['is_active'])

    def test_duplicate_signup_rejected(self):
        taken_id = {**self.NEW, 'employee_id': ENGINEER['employee_id']}
        self.assertEqual(self.client.post('/api/auth/register', json=taken_id).status_code, 409)
        taken_email = {**self.NEW, 'email': f"{ENGINEER['employee_id']}@example.com"}
        self.assertEqual(self.client.post('/api/auth/register', json=taken_email).status_code, 409)


class ValidationMessageTests(ApiTestCase):
    """입력 검증 실패는 어느 항목이 왜 틀렸는지 한국어 한 줄로 알려줘야 한다."""

    def test_invalid_email_and_short_password_are_explained(self):
        response = self.client.post('/api/auth/register', json={
            **SignupTests.NEW, 'email': 'not-an-email', 'password': 'short'})
        self.assertEqual(response.status_code, 422)
        detail = response.json()['detail']
        self.assertIsInstance(detail, str)
        self.assertIn('이메일 형식', detail)
        self.assertIn('비밀번호은(는) 8자 이상', detail)

    def test_missing_field_is_named(self):
        payload = {k: v for k, v in SignupTests.NEW.items() if k != 'name'}
        response = self.client.post('/api/auth/register', json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertIn('이름을(를) 입력하세요', response.json()['detail'])

    def test_login_validation_uses_korean_too(self):
        response = self.client.post('/api/auth/login', json={'employee_id': '', 'password': ''})
        self.assertEqual(response.status_code, 422)
        self.assertIn('사번', response.json()['detail'])

    def test_reapplying_while_pending_says_so(self):
        self.client.post('/api/auth/register', json=SignupTests.NEW)
        response = self.client.post('/api/auth/register', json=SignupTests.NEW)
        self.assertEqual(response.status_code, 409)
        self.assertIn('승인을 기다리는 중', response.json()['detail'])


class SignupDisabledTests(ApiTestCase):
    settings_overrides = {'allow_signup': False}

    def test_signup_refused_when_disabled(self):
        response = self.client.post('/api/auth/register', json=SignupTests.NEW)
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
