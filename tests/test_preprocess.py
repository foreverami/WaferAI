"""전처리가 학습의 검증 경로와 수치까지 같은지 검증한다.

여기가 깨지면 모델이 학습 때와 다른 입력을 보게 되므로, 정확도가 조용히 무너진다.
그래서 근사 비교가 아니라 rtol=0, atol=0 으로 비교한다.
"""
import unittest

import cv2
import numpy as np
import torch
from torchvision import transforms

from waferai.inference import load_model, preprocess
from waferai.preprocess import COLOR_LUT, defect_ratio, pad_to_square, to_model_input

REFERENCE_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.ToTensor(),
    transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
])


def reference_pipeline(wafer_map: np.ndarray) -> torch.Tensor:
    """training_reference.py 의 WaferDataset + val_transform 을 그대로 옮긴 기준 구현."""
    height, width = wafer_map.shape
    side = max(height, width)
    pad_h, pad_w = (side - height) // 2, (side - width) // 2
    padded = np.pad(wafer_map, ((pad_h, side - height - pad_h), (pad_w, side - width - pad_w)))
    rgb = COLOR_LUT[cv2.resize(padded, (224, 224), interpolation=cv2.INTER_NEAREST)]
    return REFERENCE_TRANSFORM(rgb)


class PreprocessingTests(unittest.TestCase):
    def test_matches_training_validation_transform(self):
        wafer_map = np.array([[0, 1, 2, 1], [1, 2, 0, 2], [0, 1, 1, 0]], dtype=np.uint8)
        torch.testing.assert_close(preprocess(wafer_map)[0], reference_pipeline(wafer_map),
                                   rtol=0, atol=0)

    def test_matches_across_shapes(self):
        """가로가 긴 맵, 세로가 긴 맵, 정사각, 한 줄짜리까지 모두 일치해야 한다."""
        rng = np.random.default_rng(0)
        for shape in [(45, 48), (48, 45), (30, 30), (1, 7), (200, 53), (64, 64)]:
            wafer_map = rng.integers(0, 3, shape).astype(np.uint8)
            torch.testing.assert_close(preprocess(wafer_map)[0], reference_pipeline(wafer_map),
                                       rtol=0, atol=0, msg=f'{shape} 불일치')

    def test_numpy_and_torch_entry_points_agree(self):
        wafer_map = np.array([[0, 1, 2], [1, 2, 0], [2, 0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(to_model_input(wafer_map),
                                      preprocess(wafer_map).numpy())

    def test_output_shape_and_dtype(self):
        result = to_model_input(np.array([[0, 1], [2, 1]], dtype=np.uint8))
        self.assertEqual(result.shape, (1, 3, 224, 224))
        self.assertEqual(result.dtype, np.float32)

    def test_rejects_invalid_maps(self):
        for wafer_map in [[], [[3]], [[float('nan')]], np.zeros((2, 2, 3)), [[-1]]]:
            with self.assertRaises(ValueError):
                to_model_input(wafer_map)

    def test_padding_puts_the_odd_pixel_at_the_end(self):
        """학습의 (side - h) // 2 내림 규칙과 같아야 한다."""
        padded = pad_to_square(np.ones((3, 6), dtype=np.uint8))
        self.assertEqual(padded.shape, (6, 6))
        self.assertEqual(int(padded[0].sum()), 0)              # 위 1줄 패딩
        self.assertEqual(int(padded[4].sum()) + int(padded[5].sum()), 0)   # 아래 2줄

    def test_missing_checkpoint_stops(self):
        """가중치가 없으면 임의 가중치로 추론하지 않고 멈춰야 한다."""
        with self.assertRaises(FileNotFoundError):
            load_model('/nonexistent/model.pth')


class DefectRatioTests(unittest.TestCase):
    def test_background_is_excluded_from_the_denominator(self):
        wafer_map = np.array([[0, 0, 0], [0, 1, 2], [0, 2, 2]], dtype=np.uint8)
        self.assertAlmostEqual(defect_ratio(wafer_map), 3 / 4)

    def test_all_background_does_not_divide_by_zero(self):
        self.assertEqual(defect_ratio(np.zeros((4, 4), dtype=np.uint8)), 0.0)

    def test_extremes(self):
        self.assertEqual(defect_ratio(np.full((4, 4), 2, dtype=np.uint8)), 1.0)
        self.assertEqual(defect_ratio(np.full((4, 4), 1, dtype=np.uint8)), 0.0)
