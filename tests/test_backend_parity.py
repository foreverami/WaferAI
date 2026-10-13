"""PyTorch 와 ONNX Runtime 이 같은 답을 내는지 검증한다.

두 백엔드가 갈라져 조용히 다른 예측을 내는 것이 이 구조의 가장 큰 위험이다.
ONNX 를 아직 익스포트하지 않았으면 건너뛴다(CI 에서 실패로 잡히지 않도록).
"""
import unittest
from pathlib import Path

import numpy as np

from waferai.backends import OnnxBackend, TorchBackend
from waferai.inference import DEFAULT_CHECKPOINT, DEFAULT_ONNX, Predictor
from waferai.preprocess import to_model_input

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / DEFAULT_CHECKPOINT
ONNX_MODEL = ROOT / DEFAULT_ONNX
PROBABILITY_TOLERANCE = 1e-4


def sample_maps():
    rng = np.random.default_rng(0)
    return [rng.integers(0, 3, shape).astype(np.uint8)
            for shape in [(45, 48), (53, 53), (26, 30), (64, 64), (33, 41)]]


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
@unittest.skipUnless(ONNX_MODEL.is_file(),
                     'ONNX 모델이 없습니다 (python3 -m scripts.export_onnx)')
class BackendParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.torch_backend = TorchBackend(CHECKPOINT)
        cls.onnx_backend = OnnxBackend(ONNX_MODEL)

    @classmethod
    def tearDownClass(cls):
        del cls.torch_backend, cls.onnx_backend

    def test_probabilities_match(self):
        for wafer_map in sample_maps():
            model_input = to_model_input(wafer_map)
            expected = self.torch_backend.probabilities(model_input)
            actual = self.onnx_backend.probabilities(model_input)
            np.testing.assert_allclose(actual, expected, atol=PROBABILITY_TOLERANCE, rtol=0)

    def test_predicted_class_matches(self):
        for wafer_map in sample_maps():
            model_input = to_model_input(wafer_map)
            self.assertEqual(int(self.onnx_backend.probabilities(model_input).argmax()),
                             int(self.torch_backend.probabilities(model_input).argmax()))

    def test_probabilities_form_a_distribution(self):
        for backend in (self.torch_backend, self.onnx_backend):
            probabilities = backend.probabilities(to_model_input(sample_maps()[0]))
            self.assertEqual(probabilities.shape, (9,))
            self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=5)
            self.assertTrue((probabilities >= 0).all())

    def test_predictor_agrees_across_backends(self):
        """Predictor 전체 경로(전처리+판정 포함)도 백엔드에 무관해야 한다."""
        wafer_map = sample_maps()[0]
        via_torch = Predictor.from_paths(CHECKPOINT, ONNX_MODEL, 'torch').predict(wafer_map)
        via_onnx = Predictor.from_paths(CHECKPOINT, ONNX_MODEL, 'onnx').predict(wafer_map)
        self.assertEqual(via_torch['final_class'], via_onnx['final_class'])
        self.assertEqual(via_torch['decision_path'], via_onnx['decision_path'])
        self.assertAlmostEqual(via_torch['confidence'], via_onnx['confidence'], places=4)


@unittest.skipUnless(CHECKPOINT.is_file(), '체크포인트가 없습니다')
class BackendSelectionTests(unittest.TestCase):
    def test_auto_falls_back_to_torch_without_onnx(self):
        predictor = Predictor.from_paths(CHECKPOINT, ROOT / 'models/does-not-exist.onnx')
        self.assertEqual(predictor.backend.name, 'torch')

    def test_explicit_onnx_without_file_fails_loudly(self):
        with self.assertRaises(FileNotFoundError):
            Predictor.from_paths(CHECKPOINT, ROOT / 'models/does-not-exist.onnx', 'onnx')

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            Predictor.from_paths(CHECKPOINT, ONNX_MODEL, 'tensorflow')
