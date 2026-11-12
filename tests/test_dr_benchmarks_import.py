"""Regression checks for authorized source-independent DR benchmarks."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from build_dr_benchmarks_from_csv import summarize, robust_clean_scores

META = {
    "event_id": "2026-11-09-C",
    "source": "test fixture",
    "source_permission": "authorized",
    "population_total": 4,
    "population_definition": "all_qualified_drivers",
    "observed_at": "2026-11-12T07:00:00-03:00",
}
ROWS = [
    {"dr": "B", "score_ms": "80000", "rank": "1"},
    {"dr": "B", "score_ms": "82000", "rank": "2"},
    {"dr": "A", "score_ms": "79000", "rank": "3"},
    {"dr": "A", "score_ms": "79000", "rank": "4"},
]


class BenchmarksTests(unittest.TestCase):
    def test_population_stats(self):
        report = summarize(ROWS, META)
        self.assertEqual(report["rows_verified"], 4)
        self.assertEqual(report["dr_laptime_stats"]["4"]["average_laptime"], "1:21.000")
        self.assertAlmostEqual(report["dr_laptime_stats"]["4"]["stddev_seconds"], 1.0)
        self.assertAlmostEqual(report["dr_laptime_stats"]["5"]["stddev_seconds"], 0.0)

    def test_refuses_incomplete_population(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_POPULATION"):
            summarize(ROWS[:-1], META)

    def test_refuses_unverified_permission(self):
        with self.assertRaisesRegex(ValueError, "authorized"):
            summarize(ROWS, {**META, "source_permission": "unknown"})

    def test_refuses_filtered_samples(self):
        with self.assertRaisesRegex(ValueError, "all qualified"):
            summarize(ROWS, {**META, "population_definition": "within_20_pct_of_wr"})

    def test_refuses_duplicate_rank(self):
        with self.assertRaisesRegex(ValueError, "duplicated"):
            summarize(ROWS[:-1] + [{"dr": "B", "score_ms": "82000", "rank": "1"}], META)

    def test_mad_rule_compatibility(self):
        clean, diagnostics = robust_clean_scores([80000.0] * 12)
        self.assertEqual(len(clean), 12)
        self.assertEqual(diagnostics["excluded_n"], 0)


if __name__ == "__main__":
    unittest.main()
