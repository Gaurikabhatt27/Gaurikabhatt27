import importlib.util
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_commit_log.py"
spec = importlib.util.spec_from_file_location("generate_commit_log", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GenerateCommitLogTests(unittest.TestCase):
    def test_graphql_query_does_not_request_total_contributions(self):
        self.assertNotIn("totalContributions", module.CONTRIBUTIONS_QUERY)
        self.assertIn("contributionCalendar", module.CONTRIBUTIONS_QUERY)
        self.assertIn("contributionCount", module.CONTRIBUTIONS_QUERY)

    def test_total_is_sum_of_daily_contribution_counts(self):
        start = date(2026, 1, 1)
        counts = {
            start: 2,
            start + timedelta(days=1): 0,
            start + timedelta(days=2): 5,
        }
        metrics = module.calculate_contribution_metrics(counts, start, start + timedelta(days=2))
        self.assertEqual(metrics["total"], 7)
        self.assertEqual(metrics["active"], 2)

    def test_calendar_parser_sums_the_returned_days(self):
        start = date(2026, 1, 1)
        end = date(2026, 1, 3)
        calendar = {
            "weeks": [{
                "contributionDays": [
                    {"date": "2026-01-01", "contributionCount": 2},
                    {"date": "2026-01-02", "contributionCount": 0},
                    {"date": "2026-01-03", "contributionCount": 5},
                ],
            }],
        }
        counts = module.flatten_calendar(calendar, start, end)
        metrics = module.calculate_contribution_metrics(counts, start, end)
        self.assertEqual(metrics["total"], 7)
        self.assertEqual(sum(day["contributionCount"] for day in calendar["weeks"][0]["contributionDays"]), 7)

    def test_generated_svgs_contain_calculated_values_not_placeholders(self):
        start = date(2026, 1, 1)
        end = date(2026, 1, 3)
        counts = {
            start: 2,
            start + timedelta(days=1): 0,
            start + timedelta(days=2): 5,
        }
        metrics = module.calculate_contribution_metrics(counts, start, end)
        level = module.intensity_levels(counts)

        commit_svg = module.generate_commit_svg(counts, metrics, start, end, level, "")
        stats_svg = module.generate_stats_svg(3, 10, 4, {"Python": 2, "JavaScript": 1}, "2026-01-01T00:00Z")

        ET.fromstring(commit_svg)
        ET.fromstring(stats_svg)
        self.assertIn(">7<", commit_svg)
        self.assertIn(">2<", commit_svg)
        self.assertIn(">3<", stats_svg)
        self.assertIn(">10<", stats_svg)
        self.assertIn(">4<", stats_svg)
        self.assertNotIn("UNAVAILABLE", commit_svg)
        self.assertNotIn("UNAVAILABLE", stats_svg)


if __name__ == "__main__":
    unittest.main()
