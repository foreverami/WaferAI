import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from waferai.decision import Thresholds
from waferai.image_adapter import encode_png, render_wafer_map
from waferai.server import MAX_UPLOAD_BYTES, create_app

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / 'models/best_coatnet_model_optimized.pth'

SYNTHETIC_MAP = b'[[0,1,0],[1,2,1],[0,1,0]]'


def wafer_png(size: int = 224) -> bytes:
    """학습과 같은 색으로 렌더링한 웨이퍼 맵 PNG."""
    yy, xx = np.mgrid[0:45, 0:48]
    radius = np.sqrt(((yy - 22) / 22.5) ** 2 + ((xx - 23.5) / 24) ** 2)
    wafer_map = np.where(radius <= 1.0, 1, 0).astype(np.uint8)
    wafer_map[(radius < 0.35) & (wafer_map == 1)] = 2
    return encode_png(render_wafer_map(wafer_map, size))


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class IntegrationTest(unittest.TestCase):
    def test_real_model_review_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / 'test.sqlite3'
            with TestClient(create_app(db_path=db_path)) as client:
                self.assertEqual(client.get('/').status_code, 200)
                self.assertEqual(client.get('/healthz').json()['status'], 'ok')

                status = client.get('/api/status').json()
                self.assertTrue(status['model_ready'])
                self.assertEqual(len(status['classes']), 9)
                self.assertIn('.png', status['accepted_formats'])
                self.assertEqual(status['thresholds']['confidence'], 0.80)

                invalid = client.post('/api/predict',
                                      files={'file': ('bad.json', b'[[3]]', 'application/json')})
                self.assertEqual(invalid.status_code, 422)

                result = client.post(
                    '/api/predict',
                    files={'file': ('synthetic.json', SYNTHETIC_MAP, 'application/json')})
                self.assertEqual(result.status_code, 200, result.text)
                data = result.json()
                record_id = data['id']
                self.assertEqual(len(data['result']['probabilities']), 9)
                self.assertIn('decision_path', data['result'])
                self.assertEqual(data['input_type'], 'array')

                self.assertEqual(
                    client.post(f'/api/records/{record_id}/review',
                                json={'label': 'invalid'}).status_code, 422)

                review = client.post(f'/api/records/{record_id}/review',
                                     json={'label': 'Center', 'note': 'synthetic integration test'})
                self.assertEqual(review.status_code, 200, review.text)
                self.assertEqual(review.json()['reviews'][0]['label'], 'Center')
                self.assertEqual(review.json()['result'], data['result'])

                client.post(f'/api/records/{record_id}/review',
                            json={'label': 'Donut', 'note': 'second review'})

            with TestClient(create_app(db_path=db_path)) as client:
                detail = client.get(f'/api/records/{record_id}').json()
                self.assertEqual(len(detail['reviews']), 2)
                self.assertEqual(client.get('/api/records').json()[0]['review']['label'], 'Donut')


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class ImageUploadTest(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.client = TestClient(create_app(db_path=Path(self._folder.name) / 'test.sqlite3'))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_rendered_wafer_map_image_is_accepted(self):
        response = self.client.post('/api/predict',
                                    files={'file': ('wafer.png', wafer_png(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['input_type'], 'image')
        self.assertEqual(body['result']['input']['source'], 'image')
        self.assertIn(body['result']['final_class'], body['result']['probabilities'])

    def test_image_and_array_paths_agree(self):
        """같은 웨이퍼를 이미지로 올리든 배열로 올리든 같은 클래스가 나와야 한다."""
        from waferai.image_adapter import image_to_wafer_map

        png = wafer_png()
        wafer_map, _ = image_to_wafer_map(png)
        array_upload = json.dumps(wafer_map.astype(int).tolist()).encode()

        via_image = self.client.post(
            '/api/predict', files={'file': ('w.png', png, 'image/png')}).json()
        via_array = self.client.post(
            '/api/predict', files={'file': ('w.json', array_upload, 'application/json')}).json()
        self.assertEqual(via_image['result']['final_class'], via_array['result']['final_class'])

    def test_oversized_image_reports_a_warning(self):
        response = self.client.post(
            '/api/predict', files={'file': ('big.png', wafer_png(800), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['result']['input']['warnings'])

    def test_foreign_palette_image_rejected(self):
        rgb = np.zeros((64, 64, 3), dtype=np.uint8)
        rgb[10:50, 10:50] = (255, 0, 0)
        response = self.client.post(
            '/api/predict', files={'file': ('red.png', encode_png(rgb), 'image/png')})
        self.assertEqual(response.status_code, 422)
        self.assertIn('색 체계', response.json()['detail'])

    def test_unsupported_extension_rejected(self):
        response = self.client.post('/api/predict',
                                    files={'file': ('notes.txt', b'0 1 2', 'text/plain')})
        self.assertEqual(response.status_code, 422)

    def test_oversized_upload_rejected(self):
        payload = b'x' * (MAX_UPLOAD_BYTES + 10)
        response = self.client.post('/api/predict',
                                    files={'file': ('huge.png', payload, 'image/png')})
        self.assertEqual(response.status_code, 413)


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class ThresholdConfigTest(unittest.TestCase):
    def test_thresholds_are_injectable(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(db_path=Path(folder) / 'test.sqlite3',
                             thresholds=Thresholds(confidence=0.99))
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/status').json()['thresholds']['confidence'],
                                 0.99)
