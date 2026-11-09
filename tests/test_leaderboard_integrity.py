"""Tests for fail-closed leaderboard integrity gate without network calls."""
import ast
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "src" / "run_daily_cached.py"


def load_injected_integrity_check():
    tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
    func = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_run_daily_agent")
    assignment = next(node for node in func.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name)
                              and target.id == "integrity_check" for target in node.targets))
    return ast.literal_eval(assignment.value)


class FullLeaderboardUnavailable(RuntimeError):
    pass


class LeaderboardIntegrityTests(unittest.TestCase):
    def check_source(self, source_mode, ranking):
        namespace = {
            "source_mode": source_mode,
            "ranking": ranking,
            "FullLeaderboardUnavailable": FullLeaderboardUnavailable,
        }
        exec(textwrap.dedent(load_injected_integrity_check()), namespace)

    def test_injection_marker_matches_real_agent_source(self):
        wrapper_tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
        function = next(node for node in wrapper_tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "_run_daily_agent")
        assignment = next(node for node in function.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == "ranking_sort_marker"
                                  for target in node.targets))
        marker = ast.literal_eval(assignment.value)
        agent_source = (ROOT / "src" / "test_race_detector.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(agent_source.count(marker), 1)

    def test_rejects_html_top_100(self):
        with self.assertRaises(FullLeaderboardUnavailable):
            self.check_source("initialRanking_fallback", [{}] * 100)

    def test_rejects_update_endpoint_fallback(self):
        with self.assertRaises(FullLeaderboardUnavailable):
            self.check_source("update_endpoint_fallback", [{}] * 100)

    def test_accepts_verified_full_source(self):
        self.check_source("live_page_data_parallel", [{}] * 125)

    def test_rejects_unavailable_source(self):
        with self.assertRaises(FullLeaderboardUnavailable):
            self.check_source(None, None)


if __name__ == "__main__":
    unittest.main()
