import unittest

from tests.conftest import ENGINEER, ApiTestCase


class HeatmapEndpointTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)
        self.wafer_id = self.upload().json()['wafer_id']

    def test_returns_png(self):
        response = self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))

    def test_lazy_generation_records_the_path(self):
        """생성 전에는 heatmap_path 가 비어 있고, 한 번 열면 채워져야 한다."""
        before = self.client.get(f'/api/records/{self.wafer_id}').json()
        self.assertIsNone(before['heatmap_path'])

        self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        after = self.client.get(f'/api/records/{self.wafer_id}').json()
        self.assertIsNotNone(after['heatmap_path'])

    def test_second_request_reuses_the_file(self):
        first = self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        second = self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        self.assertEqual(first.content, second.content)

    def test_explicit_class_produces_a_different_map(self):
        default = self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        other = self.client.get(f'/api/records/{self.wafer_id}/heatmap',
                                params={'class_name': 'Near-full'})
        self.assertEqual(other.status_code, 200, other.text)
        self.assertNotEqual(default.content, other.content)

    def test_explicit_class_does_not_overwrite_recorded_path(self):
        """ERD 의 heatmap_path 는 1순위 히트맵만 가리켜야 한다."""
        self.client.get(f'/api/records/{self.wafer_id}/heatmap')
        recorded = self.client.get(f'/api/records/{self.wafer_id}').json()['heatmap_path']
        self.client.get(f'/api/records/{self.wafer_id}/heatmap',
                        params={'class_name': 'Near-full'})
        after = self.client.get(f'/api/records/{self.wafer_id}').json()['heatmap_path']
        self.assertEqual(recorded, after)

    def test_unknown_class_rejected(self):
        response = self.client.get(f'/api/records/{self.wafer_id}/heatmap',
                                   params={'class_name': 'NotAClass'})
        self.assertEqual(response.status_code, 422)

    def test_missing_record_returns_404(self):
        self.assertEqual(
            self.client.get('/api/records/does-not-exist/heatmap').status_code, 404)

    def test_requires_login(self):
        self.logout()
        self.assertEqual(
            self.client.get(f'/api/records/{self.wafer_id}/heatmap').status_code, 401)


class ThumbnailTests(ApiTestCase):
    """목록용 썸네일. 모델을 건드리지 않아야 한다."""

    def setUp(self):
        super().setUp()
        self.login(ENGINEER)
        self.wafer_id = self.upload().json()['wafer_id']

    def test_returns_png(self):
        response = self.client.get(f'/api/records/{self.wafer_id}/thumbnail')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))

    def test_does_not_load_the_torch_model(self):
        """목록에 히트맵을 쓰면 카드 수만큼 역전파가 돌아 지연 생성이 무너진다.

        썸네일은 LUT 와 리사이즈만 하므로 PyTorch 를 올려서는 안 된다.
        """
        service = self.client.app.state.heatmaps
        service.release()
        self.client.get(f'/api/records/{self.wafer_id}/thumbnail')
        self.assertFalse(service.loaded, '썸네일이 PyTorch 를 올렸습니다')

    def test_differs_from_heatmap(self):
        thumbnail = self.client.get(f'/api/records/{self.wafer_id}/thumbnail').content
        heatmap = self.client.get(f'/api/records/{self.wafer_id}/heatmap').content
        self.assertNotEqual(thumbnail, heatmap)

    def test_missing_record_returns_404(self):
        self.assertEqual(
            self.client.get('/api/records/does-not-exist/thumbnail').status_code, 404)

    def test_requires_login(self):
        self.logout()
        self.assertEqual(
            self.client.get(f'/api/records/{self.wafer_id}/thumbnail').status_code, 401)


class LazyLoadingTests(ApiTestCase):
    def test_torch_model_is_not_loaded_until_a_heatmap_is_requested(self):
        """아무도 히트맵을 열지 않으면 PyTorch 102MB 를 올리지 않아야 한다."""
        service = self.client.app.state.heatmaps
        service.release()                       # 앞선 테스트의 상태를 지운다
        self.assertFalse(service.loaded)

        self.login(ENGINEER)
        wafer_id = self.upload().json()['wafer_id']
        self.assertFalse(service.loaded, '예측만으로 PyTorch 가 올라갔습니다')

        self.client.get(f'/api/records/{wafer_id}/heatmap')
        self.assertTrue(service.loaded)


class ApproveTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ENGINEER)
        self.detail = self.upload().json()
        self.wafer_id = self.detail['wafer_id']

    def _ranked(self):
        return sorted(self.detail['probabilities'].items(), key=lambda kv: kv[1],
                      reverse=True)

    def test_approve_records_ai_first_choice(self):
        response = self.client.post(f'/api/records/{self.wafer_id}/approve', json={})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['reviews'][0]['final_class'], self._ranked()[0][0])
        self.assertEqual(body['reviews'][0]['reviewer_id'], ENGINEER['employee_id'])

    def test_approve_rank_two_records_runner_up(self):
        response = self.client.post(f'/api/records/{self.wafer_id}/approve',
                                    json={'rank': 2, 'memo': '2순위가 맞음'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reviews'][0]['final_class'], self._ranked()[1][0])

    def test_approve_clears_the_queue_flag(self):
        self.client.post(f'/api/records/{self.wafer_id}/approve', json={})
        self.assertFalse(
            self.client.get(f'/api/records/{self.wafer_id}').json()['requires_human_review'])

    def test_approve_keeps_the_original_prediction(self):
        before = self.client.get(f'/api/records/{self.wafer_id}').json()
        after = self.client.post(f'/api/records/{self.wafer_id}/approve', json={}).json()
        self.assertEqual(after['probabilities'], before['probabilities'])
        self.assertEqual(after['final_class'], before['final_class'])

    def test_rank_beyond_class_count_rejected(self):
        response = self.client.post(f'/api/records/{self.wafer_id}/approve',
                                    json={'rank': 9})
        self.assertIn(response.status_code, (200, 422))   # 9클래스라 경계값
        over = self.client.post(f'/api/records/{self.wafer_id}/approve', json={'rank': 12})
        self.assertEqual(over.status_code, 422)

    def test_missing_record_returns_404(self):
        response = self.client.post('/api/records/nope/approve', json={})
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
