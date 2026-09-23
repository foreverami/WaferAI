import unittest

from waferai.decision import DecisionPath, Thresholds, decide

# Center 0.85 가 1순위인 기본 분포
CONFIDENT = {'Center': 0.85, 'Donut': 0.10, 'none': 0.05}
UNCERTAIN = {'Center': 0.55, 'Donut': 0.30, 'none': 0.15}


class DecisionTests(unittest.TestCase):
    def test_low_density_forces_none_and_ignores_ai(self):
        """밀도가 낮으면 AI 가 Center 를 강하게 주장해도 none 으로 확정한다."""
        result = decide(CONFIDENT, defect_ratio=0.01)
        self.assertEqual(result['final_class'], 'none')
        self.assertEqual(result['decision_path'], DecisionPath.RULE_BASE_NONE.value)
        self.assertTrue(result['rule_base_applied'])
        self.assertFalse(result['requires_human_review'])
        self.assertEqual(result['ai_top1']['class'], 'Center')   # AI 예측은 기록에 남는다

    def test_high_density_forces_near_full(self):
        result = decide(CONFIDENT, defect_ratio=0.95)
        self.assertEqual(result['final_class'], 'Near-full')
        self.assertEqual(result['decision_path'], DecisionPath.RULE_BASE_NEAR_FULL.value)
        self.assertFalse(result['requires_human_review'])

    def test_density_rules_outrank_confidence(self):
        """확신도가 낮아도 밀도 규칙에 걸리면 검토로 넘기지 않는다."""
        self.assertFalse(decide(UNCERTAIN, 0.01)['requires_human_review'])
        self.assertFalse(decide(UNCERTAIN, 0.99)['requires_human_review'])

    def test_auto_pass_when_confident(self):
        result = decide(CONFIDENT, defect_ratio=0.30)
        self.assertEqual(result['final_class'], 'Center')
        self.assertEqual(result['decision_path'], DecisionPath.AUTO_PASS.value)
        self.assertFalse(result['requires_human_review'])

    def test_review_when_not_confident(self):
        result = decide(UNCERTAIN, defect_ratio=0.30)
        self.assertEqual(result['decision_path'], DecisionPath.REVIEW_NEEDED.value)
        self.assertTrue(result['requires_human_review'])
        self.assertEqual(result['final_class'], 'Center')   # 잠정값 — 엔지니어가 확정한다

    def test_boundaries_are_inclusive_as_documented(self):
        """확신도는 이상(>=), 밀도는 초과·미만(<, >)."""
        thresholds = Thresholds()
        exact = dict(CONFIDENT, Center=0.80, Donut=0.15, none=0.05)
        self.assertEqual(decide(exact, 0.30)['decision_path'], DecisionPath.AUTO_PASS.value)

        just_under = dict(CONFIDENT, Center=0.799, Donut=0.151, none=0.05)
        self.assertEqual(decide(just_under, 0.30)['decision_path'],
                         DecisionPath.REVIEW_NEEDED.value)

        # 경계값 자체는 규칙에 걸리지 않는다
        self.assertEqual(decide(CONFIDENT, thresholds.low_density)['decision_path'],
                         DecisionPath.AUTO_PASS.value)
        self.assertEqual(decide(CONFIDENT, thresholds.high_density)['decision_path'],
                         DecisionPath.AUTO_PASS.value)

    def test_custom_thresholds_shift_behaviour(self):
        strict = Thresholds(confidence=0.95)
        self.assertEqual(decide(CONFIDENT, 0.30, strict)['decision_path'],
                         DecisionPath.REVIEW_NEEDED.value)
        self.assertEqual(decide(CONFIDENT, 0.30, strict)['thresholds']['confidence'], 0.95)

    def test_runner_up_is_reported_for_the_ui(self):
        """UIUX 문서의 '2순위 수정' 링크가 쓸 값."""
        result = decide(CONFIDENT, defect_ratio=0.30)
        self.assertEqual(result['ai_top2']['class'], 'Donut')
        self.assertAlmostEqual(result['ai_top2']['confidence'], 0.10)

    def test_invalid_thresholds_rejected(self):
        for kwargs in ({'confidence': 1.5}, {'low_density': -0.1},
                       {'low_density': 0.9, 'high_density': 0.2}):
            with self.assertRaises(ValueError):
                Thresholds(**kwargs)

    def test_empty_distribution_rejected(self):
        with self.assertRaises(ValueError):
            decide({}, defect_ratio=0.5)
