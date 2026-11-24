import unittest

from quartet_contract import FRAME, SAMPLES, bind_quartet, compare


class QuartetBindingTests(unittest.TestCase):
    def setUp(self):
        self.records = [("M", time * 100, 123, code) for time, code in enumerate(FRAME * len(SAMPLES), 1)]
        self.brackets = [(time - 5, time + 5) for _, time, _, _ in self.records]

    def test_exact_idle_and_cold(self):
        bound = bind_quartet(self.records, self.brackets, SAMPLES, 123)
        self.assertEqual(tuple(bound), SAMPLES)
        self.assertLess(bound[802][10], bound[810][9])

    def test_wrong_order_wrong_owner_missing_or_clock_drift(self):
        tag, time, tid, code = self.records[5]
        for rows, samples in (
            (self.records, (800, 801, 810, 802)),
            (self.records[:5] + [(tag, time, tid + 1, code)] + self.records[6:], SAMPLES),
            (self.records[:-1], SAMPLES),
            (self.records[:5] + [(tag, time + 20, tid, code)] + self.records[6:], SAMPLES),
        ):
            with self.subTest(length=len(rows), samples=samples):
                with self.assertRaises(ValueError):
                    bind_quartet(rows, self.brackets, samples, 123)


class QuartetComparisonTests(unittest.TestCase):
    def test_contribution_uses_same_idle_capture(self):
        totals = {800: 80_000_000, 801: 75_000_000, 802: 85_000_000, 810: 260_620_000}
        components = {800: 1_000_000, 801: 5_000_000, 802: 6_000_000, 810: 3_000_000}
        value = compare(totals, components, 40_000)
        self.assertEqual(value["idle_median_sample"], 800)
        self.assertEqual(value["margin_ns"], 620_000)
        self.assertEqual(value["conditional_margin_without_component_ns"], -380_000)
        self.assertEqual(value["outcome"], "POSITIVE_COMPONENT_LARGE_ENOUGH_FOR_RELATIVE_MARGIN")

    def test_ptrace_cost_or_near_tie_cannot_support_attribution(self):
        totals = {800: 80_000_000, 801: 75_000_000, 802: 85_000_000, 810: 260_620_000}
        components = {sample: 0 for sample in SAMPLES}
        self.assertEqual(compare(totals, components, 1_059_000)["outcome"],
                         "EXCEEDANCE_WITHIN_MEASUREMENT_UNCERTAINTY")
        totals[802] = 80_100_000
        self.assertEqual(compare(totals, components, 100_000)["outcome"],
                         "MEDIAN_IDENTITY_UNSTABLE_AT_BOUND")
        totals[802] = totals[800]
        self.assertEqual(compare(totals, components, 0)["outcome"],
                         "CAP_ACTIVE_OR_MEDIAN_AMBIGUOUS")

    def test_unmeasured_or_out_of_range_component_rejected(self):
        totals = {sample: 10 for sample in SAMPLES}
        with self.assertRaises(ValueError):
            compare(totals, {800: 1}, 0)
        with self.assertRaises(ValueError):
            compare(totals, {sample: 11 for sample in SAMPLES}, 0)


if __name__ == "__main__":
    unittest.main()
