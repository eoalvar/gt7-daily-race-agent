"""Regression tests for weekly GT7 Race C selection."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_race_detector import RaceCPendingPublication, find_current_race_c

NOW = datetime(2026, 11, 9, 7, 20, tzinfo=ZoneInfo("America/Sao_Paulo"))


def page(*blocks):
    rows = []
    for i, (label, date, state) in enumerate(blocks):
        rows.append(
            f'<div>Daily Race {label} {date} {state} '
            f'<a href="/daily/leaderboard?event={100+i}">Leaderboard</a></div>'
        )
    return BeautifulSoup("".join(rows), "html.parser")


class RaceCWeekSelectionTests(unittest.TestCase):
    def test_rejects_previous_week_even_if_running(self):
        soup = page(("C", "02 Nov 2026", "Running"),
                    ("C", "16 Nov 2026", "Next Week"))
        with self.assertRaises(RaceCPendingPublication):
            find_current_race_c(soup, NOW)

    def test_selects_current_week_over_stale_running(self):
        soup = page(("C", "02 Nov 2026", "Running"),
                    ("C", "09 Nov 2026", ""))
        result = find_current_race_c(soup, NOW)
        self.assertIn("event=101", result["url"])
        self.assertEqual(result["date"].date(), NOW.date())

    def test_accepts_unique_undated_running(self):
        result = find_current_race_c(page(("C", "", "Running")), NOW)
        self.assertTrue(result["date_inferred"])
        self.assertEqual(result["date"].date(), NOW.date())

    def test_does_not_infer_when_stale_dated_running_exists(self):
        soup = page(("C", "", "Running"),
                    ("C", "02 Nov 2026", "Running"))
        with self.assertRaises(RaceCPendingPublication):
            find_current_race_c(soup, NOW)

    def test_does_not_use_race_a_or_b(self):
        soup = page(("A", "09 Nov 2026", "Running"),
                    ("B", "09 Nov 2026", "Running"))
        with self.assertRaises(RaceCPendingPublication):
            find_current_race_c(soup, NOW)


if __name__ == "__main__":
    unittest.main()
