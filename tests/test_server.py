import unittest

import numpy as np
from conftest import (ADMIN, ENGINEER, SENIOR, SYNTHETIC_MAP, ApiTestCase, wafer_png)

from waferai.image_adapter import encode_png
from waferai.models import WaferResult
from waferai.routers.wafer_routes import MAX_UPLOAD_BYTES


class AuthorizationGateTests(ApiTestCase):
    def test_every_data_endpoint_requires_login(self):
        """인증 없이 데이터에 닿을 수 있는 구멍이 없어야 한다."""
        self.assertEqual(self.upload().status_code, 401)
        self.assertEqual(self.client.get('/api/records').status_code, 401)
        self.assertEqual(self.client.get('/api/records/anything').status_code, 401)
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        self.assertEqual(
            self.client.post('/api/records/x/review', json={'label': 'Center'}).status_code,
            401)

    def test_health_and_home_stay_public(self):
        """로드밸런서·Docker 헬스체크가 로그인 없이 불러야 한다."""
        self.assertEqual(self.client.get('/healthz').json()['status'], 'ok')
        self.assertEqual(self.client.get('/').status_code, 200)


class PredictionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)

    def test_array_upload(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['input_type'], 'array')
        self.assertEqual(len(body['probabilities']), 9)
        self.assertIn('decision_path', body)
        self.assertEqual(body['uploaded_by'], ENGINEER['employee_id'])
        self.assertIsNotNone(body['model_version'])

    def test_image_upload(self):
        response = self.upload('wafer.png', wafer_png(), 'image/png')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['input_type'], 'image')

    def test_image_and_array_paths_agree(self):
        from waferai.image_adapter import image_to_wafer_map
        import json

        png = wafer_png()
        wafer_map, _ = image_to_wafer_map(png)
        array = json.dumps(wafer_map.astype(int).tolist()).encode()

        via_image = self.upload('w.png', png, 'image/png').json()
        via_array = self.upload('w.json', array, 'application/json').json()
        self.assertEqual(via_image['final_class'], via_array['final_class'])

    def test_invalid_map_rejected(self):
        self.assertEqual(self.upload('bad.json', b'[[3]]').status_code, 422)

    def test_foreign_palette_rejected(self):
        rgb = np.zeros((64, 64, 3), dtype=np.uint8)
        rgb[10:50, 10:50] = (255, 0, 0)
        response = self.upload('red.png', encode_png(rgb), 'image/png')
        self.assertEqual(response.status_code, 422)
        self.assertIn('색 체계', response.json()['detail'])

    def test_unsupported_extension_rejected(self):
        self.assertEqual(self.upload('notes.txt', b'0 1 2', 'text/plain').status_code, 422)

    def test_oversized_upload_rejected(self):
        payload = b'x' * (MAX_UPLOAD_BYTES + 10)
        self.assertEqual(self.upload('huge.png', payload, 'image/png').status_code, 413)

    def test_status_reports_active_model_and_thresholds(self):
        body = self.client.get('/api/status').json()
        self.assertEqual(len(body['classes']), 9)
        self.assertIn('.png', body['accepted_formats'])
        self.assertIsNotNone(body['model_version'])
        # 저밀도 규칙은 실측 근거로 기본 꺼짐
        self.assertIsNone(body['thresholds']['low_density'])


class ReviewTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)
        self.wafer_id = self.upload().json()['wafer_id']

    def test_review_records_reviewer_and_keeps_ai_prediction(self):
        original = self.client.get(f'/api/records/{self.wafer_id}').json()
        response = self.client.post(f'/api/records/{self.wafer_id}/review',
                                    json={'label': 'Center', 'memo': '수동 확인'})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()

        self.assertEqual(body['reviews'][0]['final_class'], 'Center')
        self.assertEqual(body['reviews'][0]['reviewer_id'], ENGINEER['employee_id'])
        # 원래 AI 예측은 덮어쓰지 않는다 — 나중에 모델 성능을 되짚어야 한다
        self.assertEqual(body['probabilities'], original['probabilities'])
        self.assertEqual(body['final_class'], original['final_class'])

    def test_review_clears_the_queue_flag(self):
        self.client.post(f'/api/records/{self.wafer_id}/review', json={'label': 'Center'})
        self.assertFalse(
            self.client.get(f'/api/records/{self.wafer_id}').json()['requires_human_review'])

    def test_multiple_reviews_accumulate_newest_first(self):
        for label in ('Center', 'Donut'):
            self.client.post(f'/api/records/{self.wafer_id}/review', json={'label': label})
        reviews = self.client.get(f'/api/records/{self.wafer_id}').json()['reviews']
        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0]['final_class'], 'Donut')

    def test_invalid_label_rejected(self):
        response = self.client.post(f'/api/records/{self.wafer_id}/review',
                                    json={'label': 'NotAClass'})
        self.assertEqual(response.status_code, 422)

    def test_review_on_missing_record(self):
        response = self.client.post('/api/records/does-not-exist/review',
                                    json={'label': 'Center'})
        self.assertEqual(response.status_code, 404)


class RecordListTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)

    def test_pagination_and_summary_omits_heavy_map(self):
        for _ in range(3):
            self.upload()
        rows = self.client.get('/api/records?limit=2').json()
        self.assertEqual(len(rows), 2)
        self.assertNotIn('wafer_map', rows[0])      # 목록에 맵 전체를 싣지 않는다
        self.assertIn('final_class', rows[0])

    def test_offset_returns_different_rows(self):
        for _ in range(3):
            self.upload()
        first = self.client.get('/api/records?limit=1').json()
        second = self.client.get('/api/records?limit=1&offset=1').json()
        self.assertNotEqual(first[0]['wafer_id'], second[0]['wafer_id'])

    def test_review_only_filter(self):
        self.upload()
        all_rows = self.client.get('/api/records').json()
        pending = self.client.get('/api/records?review_only=true').json()
        self.assertTrue(all(row['requires_human_review'] for row in pending))
        self.assertLessEqual(len(pending), len(all_rows))

    def test_detail_includes_map_and_reviews(self):
        wafer_id = self.upload().json()['wafer_id']
        body = self.client.get(f'/api/records/{wafer_id}').json()
        self.assertIsInstance(body['wafer_map'], list)
        self.assertEqual(body['reviews'], [])

    def test_missing_record_returns_404(self):
        self.assertEqual(self.client.get('/api/records/nope').status_code, 404)


class ThresholdEffectTests(ApiTestCase):
    def test_threshold_change_affects_new_predictions(self):
        """설정 화면에서 바꾼 임계값이 실제 판정에 반영되어야 한다."""
        self.login(SENIOR)
        self.client.put('/api/settings/thresholds',
                        json={'confidence': 0.999, 'high_density': 0.8})
        self.logout()

        self.login(ENGINEER)
        body = self.upload().json()
        self.assertTrue(body['requires_human_review'])
        self.assertEqual(body['decision_path'], 'REVIEW_NEEDED')

    def test_thresholds_persist_in_database(self):
        self.login(SENIOR)
        self.client.put('/api/settings/thresholds',
                        json={'confidence': 0.77, 'high_density': 0.9})
        self.logout()
        self.login(ADMIN)
        self.assertEqual(self.client.get('/api/settings/thresholds').json()['confidence'], 0.77)


class PersistenceTests(ApiTestCase):
    def test_records_survive_in_the_database(self):
        self.login(ENGINEER)
        wafer_id = self.upload().json()['wafer_id']
        with self.client.app.state.session_factory() as session:
            stored = session.get(WaferResult, wafer_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.uploaded_by, ENGINEER['employee_id'])
            self.assertIsNotNone(stored.model_id)


if __name__ == '__main__':
    unittest.main()
