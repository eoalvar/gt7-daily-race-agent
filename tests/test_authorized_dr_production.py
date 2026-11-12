"""Production report tests (no network, email or real external data)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_authorized_dr_report import build_report, fetch_https
from build_dr_benchmarks_from_csv import summarize

META = {
    "event_id": "week-2026-11-09-race-c",
    "source": "authorized-test",
    "source_permission": "authorized",
    "population_total": 2,
    "population_definition": "within_20_pct_of_wr",
    "world_record_ms": 78000,
    "observed_at": "2026-11-12T07:00:00-03:00",
}


class ProductionRunnerTests(unittest.TestCase):
    def test_report_contains_dr_benchmarks_and_coverage(self):
        data = summarize(
            [{"dr": "B", "score_ms": "81000", "rank": "1"},
             {"dr": "B", "score_ms": "83000", "rank": "2"}], META
        )
        report = build_report(data)
        self.assertIn("1:22.000", report)
        self.assertIn("1.000s", report)
        self.assertIn("Verified eligible drivers: 2", report)
        self.assertIn("+20%", report)

    def test_reject_non_https_source(self):
        import requests
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            fetch_https(requests.Session(), "http://example.com/data.csv", max_bytes=100)


if __name__ == "__main__":
    unittest.main()
