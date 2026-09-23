"""Grad-CAM 이 결함 위치를 실제로 가리키는지 검증한다.

히트맵은 엔지니어가 AI 판단을 납득하는 근거다. 모양만 그럴듯하고 위치가 엉뚱하면
설명가능성이 아니라 잘못된 확신을 준다. 그래서 "값이 나온다" 가 아니라 "결함이 있는
쪽에 몰린다" 를 검증한다.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from waferai.gradcam import GradCAM, find_target_layer, overlay_heatmap
from waferai.preprocess import to_model_input, to_rgb, validate_map

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / 'models/best_coatnet_model_optimized.pth'


def wafer(kind: str, h: int = 45, w: int = 48) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    radius = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
    wafer_map = np.where(radius <= 1.0, 1, 0).astype(np.uint8)
    if kind == 'center':
        wafer_map[(radius < 0.35) & (wafer_map == 1)] = 2
    elif kind == 'ring':
        wafer_map[(radius > 0.82) & (radius <= 1.0) & (wafer_map == 1)] = 2
    elif kind == 'donut':
        wafer_map[(radius > 0.45) & (radius < 0.70) & (wafer_map == 1)] = 2
    return validate_map(wafer_map)


def mass_radius(cam: np.ndarray) -> float:
    """CAM 질량 중심의 정규화 반경. 0 이면 한가운데, 1 이면 가장자리."""
    yy, xx = np.mgrid[0:224, 0:224]
    radius = np.sqrt(((yy - 111.5) / 112) ** 2 + ((xx - 111.5) / 112) ** 2)
    total = cam.sum()
    return float((cam * radius).sum() / total) if total > 0 else float('nan')


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class GradCamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from waferai.backends import TorchBackend

        cls.backend = TorchBackend(CHECKPOINT)
        cls.cam = GradCAM(cls.backend.model, find_target_layer(cls.backend.model))

    @classmethod
    def tearDownClass(cls):
        cls.cam.release()

    def test_output_shape_and_range(self):
        cam, index = self.cam(to_model_input(wafer('center')))
        self.assertEqual(cam.shape, (224, 224))
        self.assertEqual(cam.dtype, np.float32)
        self.assertGreaterEqual(cam.min(), 0.0)
        self.assertLessEqual(cam.max(), 1.0)
        self.assertIn(index, range(9))

    def test_attention_follows_defect_geometry(self):
        """중앙 결함은 가운데, 링 결함은 가장자리, 도넛은 그 사이를 봐야 한다."""
        radii = {kind: mass_radius(self.cam(to_model_input(wafer(kind)))[0])
                 for kind in ('center', 'donut', 'ring')}
        self.assertLess(radii['center'], radii['donut'],
                        f'Center 가 Donut 보다 바깥을 본다: {radii}')
        self.assertLess(radii['donut'], radii['ring'],
                        f'Donut 이 Edge-Ring 보다 바깥을 본다: {radii}')

    def test_center_defect_attention_is_actually_central(self):
        cam, _ = self.cam(to_model_input(wafer('center')))
        self.assertLess(mass_radius(cam), 0.6)

    def test_edge_defect_attention_is_actually_peripheral(self):
        cam, _ = self.cam(to_model_input(wafer('ring')))
        self.assertGreater(mass_radius(cam), 0.7)

    def test_explicit_class_is_honoured(self):
        """2순위 클래스로도 히트맵을 뽑을 수 있어야 한다(UIUX 문서의 2순위 표시)."""
        _, index = self.cam(to_model_input(wafer('center')), class_index=3)
        self.assertEqual(index, 3)

    def test_different_classes_give_different_maps(self):
        model_input = to_model_input(wafer('center'))
        first, _ = self.cam(model_input, class_index=0)
        second, _ = self.cam(model_input, class_index=5)
        self.assertGreater(float(np.abs(first - second).max()), 0.01)

    def test_repeated_calls_are_stable(self):
        """훅에 상태가 남아 두 번째 호출이 달라지면 안 된다."""
        model_input = to_model_input(wafer('donut'))
        first, _ = self.cam(model_input)
        second, _ = self.cam(model_input)
        np.testing.assert_allclose(first, second, atol=1e-6)


class OverlayTests(unittest.TestCase):
    def test_overlay_shape_and_dtype(self):
        cam = np.zeros((224, 224), dtype=np.float32)
        background = np.full((224, 224, 3), 128, dtype=np.uint8)
        blended = overlay_heatmap(cam, background)
        self.assertEqual(blended.shape, (224, 224, 3))
        self.assertEqual(blended.dtype, np.uint8)

    def test_background_shows_through(self):
        """alpha=0 이면 원본 그대로여야 한다."""
        background = to_rgb(wafer('center'))
        blended = overlay_heatmap(np.zeros((224, 224), np.float32), background, alpha=0.0)
        np.testing.assert_array_equal(blended, background)

    def test_size_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            overlay_heatmap(np.zeros((64, 64), np.float32),
                            np.zeros((224, 224, 3), np.uint8))


if __name__ == '__main__':
    unittest.main()
