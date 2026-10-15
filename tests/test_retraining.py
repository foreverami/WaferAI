"""재학습 루프 — 검토 누적 → 작업 생성 → 데이터 내보내기 → 새 모델 등록 시 완료.

실제 기준은 500건이지만 테스트에서는 3건으로 낮춰 같은 흐름을 짧게 돈다.
"""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tests.conftest import ADMIN, ENGINEER, SENIOR, ApiTestCase
from waferai import retraining
from waferai.models import AiModel, RetrainJob

THRESHOLD = 3


def wafer_json(seed: int) -> bytes:
    """서로 다른 웨이퍼를 만들어 올린다 (같은 맵이어도 기록은 따로 생기지만, 구분하기 쉽게)."""
    rng = np.random.default_rng(seed)
    return json.dumps(rng.integers(0, 3, (6, 6)).tolist()).encode()


class RetrainApiTestCase(ApiTestCase):
    settings_overrides = {'retrain_threshold': THRESHOLD}

    def upload_and_review(self, count: int, label: str = 'Center', start: int = 0) -> list[str]:
        ids = []
        for seed in range(start, start + count):
            wafer_id = self.upload(f'w{seed}.json', wafer_json(seed)).json()['wafer_id']
            response = self.client.post(f'/api/records/{wafer_id}/review', json={'label': label})
            self.assertEqual(response.status_code, 200, response.text)
            ids.append(wafer_id)
        return ids

    def overview(self) -> dict:
        response = self.client.get('/api/models/retrain')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def as_admin(self):
        self.logout()
        self.login(ADMIN)


class TriggerTests(RetrainApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ADMIN)       # admin 은 검토도 할 수 있고 관리 화면도 볼 수 있다

    def test_job_is_created_when_threshold_is_reached(self):
        self.upload_and_review(THRESHOLD - 1)
        self.assertIsNone(self.overview()['active_job'], '기준 전에 작업이 생겼습니다')

        self.upload_and_review(1, start=THRESHOLD)
        state = self.overview()
        job = state['active_job']
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], 'PENDING')
        self.assertEqual(job['triggered_by'], retraining.AUTO_TRIGGER)
        self.assertEqual(job['new_reviews'], THRESHOLD)
        self.assertIsNotNone(job['base_model_id'], '어느 모델에서 출발했는지 남아야 합니다')

    def test_re_reviewing_the_same_wafer_counts_once(self):
        wafer_id = self.upload_and_review(1)[0]
        for label in ('Donut', 'Scratch', 'Loc'):
            self.client.post(f'/api/records/{wafer_id}/review', json={'label': label})
        self.assertEqual(self.overview()['new_reviews'], 1)
        self.assertIsNone(self.overview()['active_job'])

    def test_no_second_job_while_one_is_active(self):
        self.upload_and_review(THRESHOLD * 2)
        jobs = self.client.get('/api/models/retrain/jobs').json()
        self.assertEqual(len(jobs), 1)

    def test_failed_job_does_not_consume_the_reviews(self):
        """실패한 작업은 데이터를 쓰지 못했으므로 그 검토는 다시 센다."""
        self.upload_and_review(THRESHOLD)
        job_id = self.overview()['active_job']['job_id']
        self.client.post(f'/api/models/retrain/jobs/{job_id}/fail', json={'note': '학습 중단'})
        self.assertIsNone(self.overview()['active_job'])
        self.assertEqual(self.overview()['new_reviews'], THRESHOLD)

        self.upload_and_review(1, start=100)          # 다음 검토에서 곧바로 다시 생긴다
        self.assertEqual(self.overview()['active_job']['status'], 'PENDING')

    def test_completed_job_resets_the_counter(self):
        self.upload_and_review(THRESHOLD)
        job_id = self.overview()['active_job']['job_id']
        self.client.get(f'/api/models/retrain/jobs/{job_id}/dataset')          # → RUNNING
        factory = self.client.app.state.session_factory
        with factory() as session:
            model_id = session.query(AiModel.model_id).first()[0]
            completed = retraining.complete_running(session, model_id)
            session.commit()
        self.assertEqual(completed.job_id, job_id)

        state = self.overview()
        self.assertEqual(state['new_reviews'], 0)
        self.assertEqual(state['last_completed']['job_id'], job_id)
        self.assertEqual(state['last_completed']['status'], 'COMPLETED')


class DatasetExportTests(RetrainApiTestCase):
    def setUp(self):
        super().setUp()
        self.login(ADMIN)
        self.wafer_ids = self.upload_and_review(THRESHOLD - 1, label='Center')
        # 같은 웨이퍼를 고쳐 쓰면 가장 최근 검토가 정답이어야 한다 (서로 다른 웨이퍼 수는 그대로)
        self.client.post(f'/api/records/{self.wafer_ids[0]}/review', json={'label': 'Scratch'})
        self.wafer_ids += self.upload_and_review(1, label='Center', start=THRESHOLD)   # 여기서 생성
        self.job_id = self.overview()['active_job']['job_id']

    def download(self) -> dict:
        response = self.client.get(f'/api/models/retrain/jobs/{self.job_id}/dataset')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('attachment', response.headers['content-disposition'])
        return dict(np.load(io.BytesIO(response.content), allow_pickle=False))

    def test_download_marks_the_job_running(self):
        self.download()
        job = self.overview()['active_job']
        self.assertEqual(job['status'], 'RUNNING')
        self.assertIsNotNone(job['started_at'])

    def test_latest_review_is_the_label(self):
        data = self.download()
        labels = dict(zip(data['wafer_ids'].tolist(), data['labels'].tolist()))
        self.assertEqual(labels[self.wafer_ids[0]], 'Scratch')
        self.assertEqual(labels[self.wafer_ids[1]], 'Center')
        self.assertEqual(len(labels), THRESHOLD, '웨이퍼마다 한 건이어야 합니다')

    def test_reviews_after_the_cutoff_are_excluded(self):
        """작업이 만들어진 뒤의 검토는 다음 작업의 몫이다."""
        later = self.upload_and_review(1, start=500)[0]
        data = self.download()
        self.assertNotIn(later, data['wafer_ids'].tolist())

    def test_dataset_is_frozen_at_creation(self):
        """생성 뒤에 라벨을 고쳐도 이 작업의 데이터는 바뀌지 않는다 — 같은 작업은 같은 데이터."""
        self.client.post(f'/api/records/{self.wafer_ids[1]}/review', json={'label': 'Donut'})
        labels = dict(zip(*(self.download()[k].tolist() for k in ('wafer_ids', 'labels'))))
        self.assertEqual(labels[self.wafer_ids[1]], 'Center')

    def test_maps_round_trip(self):
        from scripts.training_common import unpack

        data = self.download()
        maps = unpack(data['flat'], data['shapes'])
        self.assertEqual(len(maps), THRESHOLD)
        self.assertTrue(all(set(np.unique(m)) <= {0, 1, 2} for m in maps))
        self.assertEqual(maps[0].dtype, np.uint8)

    def test_export_feeds_the_training_script(self):
        """서버가 내보낸 파일을 학습 스크립트가 그대로 읽어 학습 데이터에 더해야 한다."""
        from scripts.train import build_datasets
        from scripts.training_common import TrainingSet

        response = self.client.get(f'/api/models/retrain/jobs/{self.job_id}/dataset')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reviews.npz'
            path.write_bytes(response.content)
            base = TrainingSet(
                maps=[np.ones((5, 5), np.uint8) * (i % 3) for i in range(12)],
                labels=np.array([0, 8, 0, 8, 1, 8, 1, 8, 2, 8, 2, 8]),
                split=np.array([0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2], dtype=np.int8),
                sample_ids=np.array([f's{i}' for i in range(12)]), split_id='test-split')
            _, without, *_ = build_datasets(base, None, None, seed=1)
            maps, labels, _, _, reviewed = build_datasets(base, str(path), None, seed=1)
        self.assertEqual(reviewed, THRESHOLD)
        self.assertEqual(len(labels), len(without) + THRESHOLD)
        self.assertIn(7, labels.tolist(), 'Scratch(7) 검토 라벨이 학습 데이터에 들어가야 합니다')

    def test_finished_jobs_cannot_be_downloaded(self):
        self.client.post(f'/api/models/retrain/jobs/{self.job_id}/fail', json={'note': 'x'})
        response = self.client.get(f'/api/models/retrain/jobs/{self.job_id}/dataset')
        self.assertEqual(response.status_code, 409)


class ManualTriggerTests(RetrainApiTestCase):
    def test_admin_can_request_before_threshold(self):
        self.login(ADMIN)
        self.upload_and_review(1)
        response = self.client.post('/api/models/retrain')
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['triggered_by'], ADMIN['employee_id'])
        self.assertEqual(self.client.post('/api/models/retrain').status_code, 409)

    def test_request_without_new_reviews_is_rejected(self):
        self.login(ADMIN)
        self.assertEqual(self.client.post('/api/models/retrain').status_code, 422)


class RoleTests(RetrainApiTestCase):
    def test_engineer_cannot_see_model_management(self):
        self.login(ENGINEER)
        self.assertEqual(self.client.get('/api/models').status_code, 403)
        self.assertEqual(self.client.get('/api/models/retrain').status_code, 403)

    def test_senior_can_view_but_not_act(self):
        self.login(ADMIN)
        self.upload_and_review(THRESHOLD)
        job_id = self.overview()['active_job']['job_id']
        self.logout()

        self.login(SENIOR)
        self.assertEqual(self.client.get('/api/models').status_code, 200)
        self.assertEqual(self.client.get('/api/models/retrain/jobs').status_code, 200)
        self.assertEqual(self.client.post('/api/models/retrain').status_code, 403)
        self.assertEqual(
            self.client.get(f'/api/models/retrain/jobs/{job_id}/dataset').status_code, 403,
            '학습 데이터에는 생산 웨이퍼와 검토자 사번이 들어 있어 관리자만 받아야 합니다')
        self.assertEqual(
            self.client.post(f'/api/models/retrain/jobs/{job_id}/fail',
                             json={'note': 'x'}).status_code, 403)

    def test_model_list_marks_the_legacy_model(self):
        self.login(SENIOR)
        models = self.client.get('/api/models').json()
        active = [model for model in models if model['is_active']]
        self.assertEqual(len(active), 1)
        if active[0]['split_id'] is None:            # 1학기 모델
            self.assertFalse(active[0]['has_clean_test'])


class RegistrationTests(unittest.TestCase):
    """기동 시 모델 등록 — 활성 모델은 언제나 하나, 재학습 결과는 작업을 완료시킨다."""

    def setUp(self):
        from waferai.db import create_all, create_db_engine, create_session_factory

        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        folder = Path(self._folder.name)
        engine = create_db_engine(f'sqlite:///{folder / "reg.db"}')
        self.addCleanup(engine.dispose)
        create_all(engine)
        self.factory = create_session_factory(engine)
        self.weights = {}
        for name in ('legacy', 'retrained'):
            path = folder / f'{name}.pth'
            path.write_bytes(name.encode() * 100)          # 해시만 다르면 된다
            self.weights[name] = path

    def register(self, name: str, split_id: str | None = None) -> int:
        from waferai.server import _register_model

        predictor = SimpleNamespace(
            backend=SimpleNamespace(name='torch', source_path=self.weights[name]),
            metadata={'epoch': 3, 'val_acc': 90.0, 'split_id': split_id,
                      'test_metrics': {'natural': {'accuracy': 0.9}} if split_id else None})
        return _register_model(self.factory, predictor, self.weights[name])

    def active_ids(self) -> list[int]:
        with self.factory() as session:
            return [m.model_id for m in session.query(AiModel).filter(AiModel.is_active.is_(True))]

    def test_same_weights_register_once(self):
        first = self.register('legacy')
        second = self.register('legacy')
        self.assertEqual(first, second)
        with self.factory() as session:
            self.assertEqual(session.query(AiModel).count(), 1)

    def test_rolling_back_keeps_exactly_one_active(self):
        """이전 가중치로 되돌릴 때 다른 모델을 내리지 않으면 활성 모델이 둘이 된다."""
        legacy = self.register('legacy')
        self.register('retrained', split_id='abc')
        self.assertEqual(len(self.active_ids()), 1)
        self.register('legacy')
        self.assertEqual(self.active_ids(), [legacy])

    def test_new_retrained_model_completes_the_running_job(self):
        base = self.register('legacy')
        with self.factory() as session:
            job = retraining.create_job(session, retraining.AUTO_TRIGGER, 500)
            retraining.mark_running(session, job)
            session.commit()
            job_id = job.job_id

        new = self.register('retrained', split_id='abc')
        with self.factory() as session:
            job = session.get(RetrainJob, job_id)
            self.assertEqual(job.status, 'COMPLETED')
            self.assertEqual(job.result_model_id, new)
            self.assertEqual(job.base_model_id, base)
            model = session.get(AiModel, new)
            self.assertEqual(model.split_id, 'abc')
            self.assertTrue(model.has_clean_test)

    def test_legacy_registration_does_not_complete_a_job(self):
        """분할 기록이 없는 가중치는 재학습 결과가 아니다."""
        with self.factory() as session:
            job = retraining.create_job(session, retraining.AUTO_TRIGGER, 500)
            retraining.mark_running(session, job)
            session.commit()
            job_id = job.job_id
        self.register('legacy')
        with self.factory() as session:
            self.assertEqual(session.get(RetrainJob, job_id).status, 'RUNNING')


class ContaminationGuardTests(unittest.TestCase):
    """이어 학습할 가중치가 다른 분할로 학습됐으면 거부한다 — 테스트 셋 오염 방지."""

    def test_rules(self):
        from scripts.train import check_init_split

        check_init_split('6685ab33', '6685ab33', False)             # 같은 분할: 통과
        check_init_split(None, '6685ab33', True)                    # 명시적으로 감수: 통과
        for origin in (None, 'other-split'):                        # 1학기 모델, 다른 분할
            with self.assertRaises(SystemExit):
                check_init_split(origin, '6685ab33', False)


class StaleOnnxTests(unittest.TestCase):
    """.pth 만 바꾸고 .onnx 를 다시 만들지 않으면 서버가 옛 모델을 계속 낸다."""

    @classmethod
    def setUpClass(cls):
        try:
            import onnx
            from onnx import TensorProto, helper
        except ImportError:
            raise unittest.SkipTest('onnx 가 없습니다 (requirements-dev.txt)')
        cls._folder = tempfile.TemporaryDirectory()
        folder = Path(cls._folder.name)
        cls.checkpoint = folder / 'model.pth'
        cls.checkpoint.write_bytes(b'current weights')
        graph = helper.make_graph(
            [helper.make_node('Identity', ['x'], ['y'])], 'g',
            [helper.make_tensor_value_info('x', TensorProto.FLOAT, [1])],
            [helper.make_tensor_value_info('y', TensorProto.FLOAT, [1])])
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)])
        model.ir_version = 9
        entry = model.metadata_props.add()
        entry.key, entry.value = 'source_sha256', 'f' * 64            # 다른 가중치에서 나온 ONNX
        cls.onnx_path = folder / 'model.onnx'
        onnx.save(model, str(cls.onnx_path))
        entry.value = hashlib.sha256(b'current weights').hexdigest()  # 지금 가중치에서 나온 ONNX
        cls.fresh_onnx_path = folder / 'fresh.onnx'
        onnx.save(model, str(cls.fresh_onnx_path))

    @classmethod
    def tearDownClass(cls):
        cls._folder.cleanup()

    def test_mismatch_is_detected(self):
        from waferai.backends import onnx_matches_checkpoint

        self.assertIs(onnx_matches_checkpoint(self.onnx_path, self.checkpoint), False)

    def test_explicit_onnx_refuses_stale_file(self):
        from waferai.backends import build_backend

        with self.assertRaises(RuntimeError):
            build_backend(self.checkpoint, self.onnx_path, prefer='onnx')

    def test_matching_file_opens_a_single_session(self):
        """짝 확인 때문에 세션을 여러 번 열면 기동이 느려지고 작업 스레드가 쌓인다."""
        import onnxruntime as ort

        from waferai.backends import build_backend

        opened = []
        original = ort.InferenceSession

        def counting(*args, **kwargs):
            opened.append(args[0])
            return original(*args, **kwargs)

        with mock.patch.object(ort, 'InferenceSession', counting):
            backend = build_backend(self.checkpoint, self.fresh_onnx_path, prefer='onnx')
        self.assertEqual(backend.name, 'onnx')
        self.assertEqual(len(opened), 1)



def scores(balanced: float, natural: float) -> dict:
    return {'balanced': {'macro_f1': balanced, 'accuracy': balanced, 'n': 100},
            'natural': {'macro_f1': natural, 'accuracy': natural, 'n': 1000}}


class PromotionGateTests(unittest.TestCase):
    """새 모델이 기존보다 나쁘면 교체를 막는다. 첫 재학습에서는 공정한 비교가 불가능하다."""

    SPLIT = '6685ab33'

    def decide(self, candidate, current, candidate_split=SPLIT, current_split=SPLIT):
        from scripts.promote_model import decide

        return decide(candidate, current, candidate_split, current_split, self.SPLIT)

    def test_better_model_passes_a_fair_comparison(self):
        verdict = self.decide(scores(0.95, 0.90), scores(0.93, 0.88))
        self.assertTrue(verdict.passed)
        self.assertTrue(verdict.fair_comparison)

    def test_worse_model_is_rejected(self):
        verdict = self.decide(scores(0.95, 0.80), scores(0.93, 0.88))
        self.assertFalse(verdict.passed)
        self.assertIn('natural', verdict.reasons[0])

    def test_small_drop_within_tolerance_passes(self):
        self.assertTrue(self.decide(scores(0.928, 0.877), scores(0.93, 0.88)).passed)

    def test_legacy_baseline_is_not_compared(self):
        """1학기 모델은 테스트 셋을 이미 봐서 점수가 부풀려져 있다. 그와 비교하면 항상 진다."""
        inflated = scores(0.99, 0.99)
        verdict = self.decide(scores(0.92, 0.85), inflated, current_split=None)
        self.assertTrue(verdict.passed, '부풀려진 기준과 비교해 거부하면 안 됩니다')
        self.assertFalse(verdict.fair_comparison)

    def test_legacy_baseline_still_requires_the_floor(self):
        verdict = self.decide(scores(0.70, 0.95), scores(0.99, 0.99), current_split=None)
        self.assertFalse(verdict.passed)

    def test_candidate_from_another_split_is_refused(self):
        verdict = self.decide(scores(0.99, 0.99), None, candidate_split='other')
        self.assertFalse(verdict.passed)

    def test_no_current_model_uses_the_floor(self):
        self.assertTrue(self.decide(scores(0.90, 0.90), None).passed)
        self.assertFalse(self.decide(scores(0.50, 0.90), None).passed)


class TrainingCommonTests(unittest.TestCase):
    def test_balanced_keeps_all_defects_and_matches_normals(self):
        from scripts.training_common import NONE_INDEX, balanced

        labels = np.array([0, 3, NONE_INDEX, NONE_INDEX, NONE_INDEX, NONE_INDEX, 7])
        chosen = balanced(np.arange(7), labels, seed=0)
        self.assertEqual(sorted(labels[chosen].tolist()).count(NONE_INDEX), 3)
        self.assertTrue({0, 1, 6} <= set(chosen.tolist()), '결함은 전부 들어가야 합니다')

    def test_confidence_profile_gives_review_rate_per_threshold(self):
        """임계값마다 '그 값 미만이라 검토로 가는 비율' 을 주고, 최대 확신도를 상한으로 알려 준다."""
        from scripts.training_common import CONFIDENCE_GRID, confidence_profile

        probs = np.array([[0.95, 0.05], [0.70, 0.30], [0.55, 0.45]])
        profile = confidence_profile(probs)
        curve = {threshold: rate for threshold, rate in profile['review_curve']}

        self.assertEqual(profile['n'], 3)
        self.assertAlmostEqual(profile['confidence_max'], 0.95)
        self.assertEqual([t for t, _ in profile['review_curve']], CONFIDENCE_GRID)
        self.assertEqual(curve[0.50], 0.0)                       # 셋 다 0.50 이상
        self.assertAlmostEqual(curve[0.60], 1 / 3, places=3)     # 0.55 만 검토
        self.assertAlmostEqual(curve[0.80], 2 / 3, places=3)     # 0.55, 0.70 검토
        self.assertEqual(curve[0.99], 1.0)                       # 전부 검토
        rates = [rate for _, rate in profile['review_curve']]
        self.assertEqual(rates, sorted(rates), '임계값이 오르면 검토율은 내려갈 수 없다')

    def test_confidence_profile_handles_empty_input(self):
        from scripts.training_common import confidence_profile

        profile = confidence_profile(np.zeros((0, 9)))
        self.assertEqual((profile['n'], profile['confidence_max'], profile['review_curve']), (0, 0.0, []))

    def test_balanced_without_defects_is_an_integer_empty_array(self):
        """표본이 적어 결함이 0개면 빈 배열이 실수형이 되어 인덱싱이 터졌다 (승격 판정 중 발견)."""
        from scripts.training_common import NONE_INDEX, balanced

        chosen = balanced(np.arange(4), np.full(4, NONE_INDEX), seed=0)
        self.assertEqual(len(chosen), 0)
        self.assertEqual(chosen.dtype, np.int64)
        np.arange(4)[chosen]                                       # 인덱스로 쓸 수 있어야 한다


class DecisionSummaryTests(unittest.TestCase):
    """판정 효과 측정에서 틀린 무인 통과를 종류별로 센다 — 결함 누락이 가장 나쁘다."""

    def test_wrong_unattended_results_are_split_by_kind(self):
        from scripts.evaluate_decisions import summarize
        from scripts.training_common import CLASS_NAMES, NONE_INDEX

        center, scratch = CLASS_NAMES.index('Center'), CLASS_NAMES.index('Scratch')
        decisions = [
            {'final_class': 'none', 'decision_path': 'AUTO_PASS'},        # 결함을 정상으로
            {'final_class': 'Scratch', 'decision_path': 'AUTO_PASS'},     # 결함 유형 틀림
            {'final_class': 'Center', 'decision_path': 'AUTO_PASS'},      # 정상을 결함으로
            {'final_class': 'Center', 'decision_path': 'AUTO_PASS'},      # 맞음
            {'final_class': 'none', 'decision_path': 'REVIEW_NEEDED'},    # 틀렸지만 사람이 봄
        ]
        truth = np.array([center, center, NONE_INDEX, center, scratch])
        s = summarize(decisions, truth)
        self.assertEqual((s['missed_defect'], s['wrong_type'], s['false_alarm']), (1, 1, 1))
        self.assertEqual(s['escaped'], 3)
        self.assertEqual(s['review'], 1)
        self.assertAlmostEqual(s['unattended'], 0.8)
        self.assertEqual(s['review_ai_correct'], 0.0)
        self.assertEqual(s['missed_by_class'], {'Center': 1})


if __name__ == '__main__':
    unittest.main()
