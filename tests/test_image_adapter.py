import unittest

import cv2
import numpy as np

from waferai.image_adapter import (STORE_LIMIT, UnsupportedImage, encode_png,
                                   image_to_wafer_map, render_wafer_map)
from waferai.preprocess import to_model_input


def circular_wafer(h: int, w: int, defect: str = 'center') -> np.ndarray:
    """가장자리가 배경인 실제형 원형 웨이퍼 맵."""
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    radius = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
    wafer_map = np.where(radius <= 1.0, 1, 0).astype(np.uint8)
    if defect == 'center':
        wafer_map[(radius < 0.35) & (wafer_map == 1)] = 2
    elif defect == 'scratch':
        for row in range(h):
            col = int(cx + (row - cy) * 0.45)
            if 0 <= col < w and wafer_map[row, col] == 1:
                wafer_map[row, col] = 2
    return wafer_map


class RoundTripTests(unittest.TestCase):
    def test_lossless_round_trip_when_content_touches_borders(self):
        """테두리까지 내용이 찬 맵은 렌더링 → 복원이 무손실이어야 한다."""
        wafer_map = np.ones((64, 64), dtype=np.uint8)
        wafer_map[20:40, 20:40] = 2
        restored, _ = image_to_wafer_map(encode_png(render_wafer_map(wafer_map)))
        np.testing.assert_array_equal(restored, wafer_map)

    def test_crop_restores_training_geometry(self):
        """크롭이 학습 패딩을 정확히 되돌려 가로세로비가 보존되어야 한다."""
        wafer_map = circular_wafer(45, 48)
        restored, _ = image_to_wafer_map(encode_png(render_wafer_map(wafer_map, 224)))
        self.assertAlmostEqual(restored.shape[0] / restored.shape[1], 45 / 48, places=2)

    def test_model_input_stays_close_through_the_image_path(self):
        """이미지 경로를 거쳐도 모델이 보는 텐서가 실질적으로 같아야 한다."""
        for defect in ('center', 'scratch'):
            wafer_map = circular_wafer(45, 48, defect)
            restored, _ = image_to_wafer_map(encode_png(render_wafer_map(wafer_map, 224)))
            direct, through_image = to_model_input(wafer_map), to_model_input(restored)
            identical = float((direct == through_image).mean())
            self.assertGreater(identical, 0.98, f'{defect}: 동일 픽셀 {identical:.3%}')

    def test_jpeg_artifacts_are_tolerated(self):
        """JPEG 압축으로 색이 흔들려도 PNG 와 사실상 같은 맵으로 복원되어야 한다.

        완전 일치까지는 요구하지 않는다. JPEG 는 색 경계에서 실제로 값을 흔들기 때문에
        경계 픽셀 몇 개는 다를 수 있다. 여기서 막으려는 것은 압축 때문에 맵이 무너지는
        경우이지, 경계의 한두 픽셀이 아니다.
        """
        rgb = render_wafer_map(circular_wafer(45, 48), 224)
        ok, buffer = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                                  [cv2.IMWRITE_JPEG_QUALITY, 85])
        self.assertTrue(ok)
        from_jpeg, info = image_to_wafer_map(buffer.tobytes())
        from_png, _ = image_to_wafer_map(encode_png(rgb))

        self.assertEqual(from_jpeg.shape, from_png.shape)
        identical = float((from_jpeg == from_png).mean())
        self.assertGreater(identical, 0.999, f'JPEG 복원 일치율 {identical:.4%}')
        self.assertLess(info['unmatched_ratio'], 0.02)


class RejectionTests(unittest.TestCase):
    def test_foreign_palette_rejected(self):
        """다른 색 체계를 조용히 잘못 해석하지 않고 거부해야 한다."""
        wafer_map = circular_wafer(45, 48)
        for palette in ({0: (0, 0, 0), 1: (128, 128, 128), 2: (255, 255, 255)},
                        {0: (0, 0, 0), 1: (0, 0, 255), 2: (255, 0, 0)}):
            rgb = np.zeros((*wafer_map.shape, 3), dtype=np.uint8)
            for value, color in palette.items():
                rgb[wafer_map == value] = color
            with self.assertRaises(UnsupportedImage):
                image_to_wafer_map(encode_png(rgb))

    def test_blank_image_rejected(self):
        with self.assertRaises(UnsupportedImage):
            image_to_wafer_map(encode_png(np.zeros((64, 64, 3), dtype=np.uint8)))

    def test_undecodable_bytes_rejected(self):
        with self.assertRaises(UnsupportedImage):
            image_to_wafer_map(b'this is not an image')


class DownsamplingTests(unittest.TestCase):
    def test_oversized_image_is_reduced_once_and_warns(self):
        restored, info = image_to_wafer_map(
            encode_png(render_wafer_map(circular_wafer(45, 48), 800)))
        self.assertTrue(info['downsampled'])
        self.assertEqual(restored.shape, (224, 224))
        self.assertTrue(info['warnings'])

    def test_small_image_is_left_alone(self):
        restored, info = image_to_wafer_map(
            encode_png(render_wafer_map(circular_wafer(45, 48), 224)))
        self.assertFalse(info['downsampled'])
        self.assertFalse(info['warnings'])
        self.assertLessEqual(max(restored.shape), STORE_LIMIT)
