"""11월 개선 — 확률 보정, 클래스별 임계값, 입력 감지, 색상표, 내보내기, 성능 추이, 감사 기록."""
import csv
import io
import json
import unittest

import numpy as np

from tests.conftest import ADMIN, ENGINEER, NOT_A_WAFER, SENIOR, ApiTestCase
from waferai import ood
from waferai.calibration import (apply_temperature, expected_calibration_error,
                                 fit_temperature)
from waferai.decision import Thresholds, decide
from waferai.image_adapter import encode_png


def round_wafer(r: int = 20) -> np.ndarray:
    yy, xx = np.indices((2 * r + 1, 2 * r + 1))
    return (((yy - r) ** 2 + (xx - r) ** 2) <= r * r).astype(np.uint8)


class DecisionTests(unittest.TestCase):
    PROBS = {'none': 0.86, 'Loc': 0.10, 'Center': 0.04}

    def test_class_threshold_overrides_global(self):
        """'none' 에만 더 높은 기준을 걸면 같은 확신도라도 검토로 간다."""
        base = decide(self.PROBS, 0.01, Thresholds(confidence=0.80))
        strict = decide(self.PROBS, 0.01, Thresholds(confidence=0.80, class_confidence={'none': 0.90}))
        self.assertEqual(base['decision_path'], 'AUTO_PASS')
        self.assertEqual(strict['decision_path'], 'REVIEW_NEEDED')
        self.assertEqual(strict['applied_confidence'], 0.90)

    def test_out_of_scope_goes_to_people_with_reasons(self):
        result = decide(self.PROBS, 0.01, Thresholds(), out_of_scope=['원형이 아닙니다'])
        self.assertEqual(result['decision_path'], 'OUT_OF_SCOPE')
        self.assertTrue(result['requires_human_review'])
        self.assertEqual(result['review_reasons'], ['원형이 아닙니다'])

    def test_force_review_reason_kept_when_already_in_review(self):
        low = {'none': 0.40, 'Loc': 0.35, 'Center': 0.25}
        result = decide(low, 0.01, Thresholds(), force_review='색을 추정했습니다')
        self.assertEqual(result['decision_path'], 'REVIEW_NEEDED')
        self.assertEqual(result['review_reasons'], ['색을 추정했습니다'])

    def test_force_review_blocks_every_unattended_path(self):
        for ratio in (0.01, 0.95):                  # 자동 통과, 고밀도 규칙
            result = decide(self.PROBS, ratio, Thresholds(), force_review='색을 추정했습니다')
            self.assertEqual(result['decision_path'], 'REVIEW_NEEDED')
            self.assertEqual(result['review_reasons'], ['색을 추정했습니다'])

    def test_invalid_class_threshold_rejected(self):
        with self.assertRaises(ValueError):
            Thresholds(class_confidence={'none': 1.5})


class CalibrationTests(unittest.TestCase):
    def test_temperature_keeps_ranking(self):
        probs = np.array([[0.6, 0.3, 0.1], [0.2, 0.5, 0.3]])
        for t in (0.5, 2.0):
            np.testing.assert_array_equal(apply_temperature(probs, t).argmax(1), probs.argmax(1))
        np.testing.assert_allclose(apply_temperature(probs, None), probs, rtol=1e-6)

    def test_sharpening_raises_confidence(self):
        probs = np.array([[0.6, 0.3, 0.1]])
        self.assertGreater(apply_temperature(probs, 0.5)[0, 0], 0.6)

    def test_fit_recovers_known_temperature(self):
        """정답 분포를 T=2 로 흐린 확률에서 시작하면 T≈0.5 로 되돌려야 한다."""
        rng = np.random.default_rng(0)
        logits = rng.normal(size=(4000, 5)) * 3
        sharp = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
        labels = np.array([rng.choice(5, p=p) for p in sharp])
        blurred = apply_temperature(sharp, 2.0)
        t = fit_temperature(blurred, labels)
        self.assertAlmostEqual(t, 0.5, delta=0.08)
        self.assertLess(expected_calibration_error(apply_temperature(blurred, t), labels),
                        expected_calibration_error(blurred, labels))


class ShapeCheckTests(unittest.TestCase):
    def test_real_looking_wafer_passes_and_padding_does_not_matter(self):
        wafer = round_wafer()
        wafer[18:22, 18:22] = 2
        self.assertTrue(ood.check_shape(wafer).in_distribution)
        self.assertTrue(ood.check_shape(np.pad(wafer, 30)).in_distribution)

    def test_non_wafers_are_caught(self):
        rng = np.random.default_rng(1)
        cases = {
            'noise': rng.integers(0, 3, size=(60, 60)),
            'rectangle': np.ones((50, 70), np.uint8),
            'checkerboard': (np.indices((40, 40)).sum(0) % 2 + 1),
            'tiny': round_wafer(5),
        }
        for name, wm in cases.items():
            check = ood.check_shape(wm.astype(np.uint8))
            self.assertFalse(check.in_distribution, name)
            self.assertTrue(check.reasons, name)


class OutOfScopeApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)

    def test_non_wafer_upload_is_held_for_people(self):
        response = self.upload(payload=NOT_A_WAFER)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['decision_path'], 'OUT_OF_SCOPE')
        self.assertTrue(body['requires_human_review'])
        self.assertTrue(body['input_info']['review_reasons'])
        self.assertFalse(body['input_info']['shape_check']['in_distribution'])

    def test_guessed_palette_image_is_forced_to_review(self):
        yy, xx = np.mgrid[0:45, 0:48]
        radius = np.sqrt(((yy - 22) / 22.5) ** 2 + ((xx - 23.5) / 24) ** 2)
        wafer = np.where(radius <= 1.0, 1, 0).astype(np.uint8)
        wafer[(radius < 0.35) & (wafer == 1)] = 2
        palette = np.array([[0, 0, 0], [0, 0, 255], [255, 0, 0]], dtype=np.uint8)
        image = encode_png(palette[wafer])
        response = self.upload('odd.png', image, 'image/png')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['decision_path'], 'REVIEW_NEEDED')
        self.assertTrue(body['input_info']['palette']['guessed'])
        self.assertTrue(any('추정' in r for r in body['input_info']['review_reasons']))


class ClassThresholdApiTests(ApiTestCase):
    CALIBRATION = {'temperature': 1.0,
                   'class_thresholds': {name: 0.80 for name in
                                        ('Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
                                         'Near-full', 'Random', 'Scratch')} | {'none': 0.97}}

    def setUp(self):
        super().setUp()
        metadata = self.client.app.state.predictor.backend.metadata
        self._original = metadata.get('calibration')
        metadata['calibration'] = self.CALIBRATION
        self.login(SENIOR)

    def tearDown(self):
        self.client.app.state.predictor.backend.metadata['calibration'] = self._original

    def test_recommended_thresholds_are_on_by_default(self):
        body = self.client.get('/api/settings/thresholds').json()
        self.assertTrue(body['use_class_thresholds'])
        self.assertEqual(body['class_confidence']['none'], 0.97)
        self.assertEqual(body['recommended_class_thresholds']['none'], 0.97)
        self.assertEqual(self.client.get('/api/status').json()['thresholds']['class_confidence']['none'], 0.97)

    def test_turning_off_falls_back_to_single_threshold(self):
        response = self.client.put('/api/settings/thresholds',
                                   json={'confidence': 0.8, 'high_density': 0.8, 'use_class_thresholds': False})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body['use_class_thresholds'])
        self.assertIsNone(body['class_confidence'])
        self.assertEqual(body['recommended_class_thresholds']['none'], 0.97)   # 권장값은 계속 보인다


class ExportAndTrendTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)
        self.first = self.upload().json()
        self.upload(payload=NOT_A_WAFER)
        self.client.post(f"/api/records/{self.first['wafer_id']}/approve", json={'rank': 1})

    def test_csv_export_has_bom_header_and_rows(self):
        response = self.client.get('/api/records/export')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response.headers['content-type'])
        text = response.content.decode('utf-8')
        self.assertTrue(text.startswith('﻿'))
        rows = list(csv.DictReader(io.StringIO(text.lstrip('﻿'))))
        self.assertEqual(len(rows), 2)
        approved = next(r for r in rows if r['wafer_id'] == self.first['wafer_id'])
        self.assertEqual(approved['ai_agreed'], '1')
        self.assertEqual(approved['reviewer'], ENGINEER['employee_id'])

    def test_export_review_only(self):
        rows = list(csv.DictReader(io.StringIO(
            self.client.get('/api/records/export?review_only=true').content.decode('utf-8').lstrip('﻿'))))
        self.assertTrue(all(r['requires_human_review'] == '1' for r in rows))

    def test_trend_counts_paths_and_agreement(self):
        self.assertEqual(self.client.get('/api/stats/trend').status_code, 403)     # 엔지니어는 못 본다
        self.logout()
        self.login(SENIOR)
        weeks = self.client.get('/api/stats/trend').json()['weeks']
        self.assertEqual(len(weeks), 1)
        week = weeks[0]
        self.assertEqual(week['uploads'], 2)
        self.assertEqual(week['out_of_scope'], 1)
        self.assertEqual(week['reviewed'], 1)
        self.assertEqual(week['ai_agreed'], 1)


class AuditAndHealthTests(ApiTestCase):
    def test_login_events_are_stored_and_admin_only(self):
        self.client.post('/api/auth/login', json={'employee_id': ENGINEER['employee_id'],
                                                  'password': 'wrong-pass-1'})
        self.login(ENGINEER)
        self.assertEqual(self.client.get('/api/audit').status_code, 403)
        self.logout()
        self.login(ADMIN)
        events = self.client.get('/api/audit?event=login').json()
        kinds = [(e['event'], e['employee_id']) for e in events]
        self.assertIn(('login.fail', ENGINEER['employee_id']), kinds)
        self.assertIn(('login.ok', ENGINEER['employee_id']), kinds)
        self.assertTrue(all('password' not in json.dumps(e) for e in events))

    def test_reset_is_recorded_with_actor(self):
        self.login(ADMIN)
        self.client.post(f"/api/users/{ENGINEER['employee_id']}/reset-password")
        event = self.client.get('/api/audit?event=password.reset').json()[0]
        self.assertEqual(event['employee_id'], ENGINEER['employee_id'])
        self.assertEqual(event['actor'], ADMIN['employee_id'])

    def test_system_health_for_admin(self):
        self.login(SENIOR)
        self.assertEqual(self.client.get('/api/system/health').status_code, 403)
        self.logout()
        self.login(ADMIN)
        body = self.client.get('/api/system/health').json()
        self.assertGreater(body['disk_total_gb'], 0)
        self.assertIn('wafer_result', body['database_rows'])
