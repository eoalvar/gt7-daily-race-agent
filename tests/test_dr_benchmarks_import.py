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
    "population_definition": "within_20_pct_of_wr",
    "world_record_ms": 78000,
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

    def test_refuses_population_without_20pct_rule(self):
        with self.assertRaisesRegex(ValueError, "within 20%"):
            summarize(ROWS, {**META, "population_definition": "all_qualified_drivers"})

    def test_excludes_slower_than_120pct_world_record(self):
        # WR=78,000ms; upper bound inclusive = 93,600ms.
        extended = ROWS + [
            {"dr": "D", "score_ms": "93600", "rank": "5"},
            {"dr": "D", "score_ms": "93601", "rank": "6"},
        ]
        result = summarize(extended, {**META, "population_total": 5})
        self.assertEqual(result["source_rows"], 6)
        self.assertEqual(result["rows_verified"], 5)
        self.assertEqual(result["excluded_over_20pct"], 1)
        self.assertEqual(result["dr_laptime_stats"]["2"]["average_laptime"], "1:33.600")
        self.assertEqual(result["dr_laptime_stats"]["2"]["drivers"], 1)

    def test_filtered_population_count_must_be_complete(self):
        extended = ROWS + [{"dr": "D", "score_ms": "93601", "rank": "5"}]
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_POPULATION"):
            summarize(extended, {**META, "population_total": 5})

    def test_world_record_required(self):
        with self.assertRaisesRegex(ValueError, "Missing metadata"):
            summarize(ROWS, {k: v for k, v in META.items() if k != "world_record_ms"})

    def test_missing_or_invalid_world_record(self):
        with self.assertRaisesRegex(ValueError, "world_record_ms"):
            summarize(ROWS, {**META, "world_record_ms": 0})

    def test_refuses_duplicate_rank(self):
        with self.assertRaisesRegex(ValueError, "duplicated"):
            summarize(ROWS[:-1] + [{"dr": "B", "score_ms": "82000", "rank": "1"}], META)

    def test_mad_rule_compatibility(self):
        clean, diagnostics = robust_clean_scores([80000.0] * 12)
        self.assertEqual(len(clean), 12)
        self.assertEqual(diagnostics["excluded_n"], 0)


if __name__ == "__main__":
    unittest.main()
