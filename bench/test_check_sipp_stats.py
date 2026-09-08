import tempfile
import unittest
from pathlib import Path

from check_sipp_stats import check_stats


class SippStatsTest(unittest.TestCase):
    def check(self, contents, expected=10):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.csv"
            path.write_text(contents, encoding="utf-8")
            return check_stats(path, expected)

    def test_uses_final_cumulative_sample(self):
        self.assertEqual(
            self.check("SuccessfulCall(C);FailedCall(C);\n3;0;\n10;0;\n"),
            (10, 0),
        )

    def test_failed_calls(self):
        with self.assertRaises(ValueError):
            self.check("SuccessfulCall(C);FailedCall(C);\n10;1;\n")

    def test_incomplete_run(self):
        with self.assertRaises(ValueError):
            self.check("SuccessfulCall(C);FailedCall(C);\n9;0;\n")

    def test_no_samples(self):
        with self.assertRaises(ValueError):
            self.check("SuccessfulCall(C);FailedCall(C);\n")

    def test_wrong_schema(self):
        with self.assertRaises(KeyError):
            self.check("Other;FailedCall(C);\n10;0;\n")

    def test_malformed_final_sample(self):
        with self.assertRaises(ValueError):
            self.check("SuccessfulCall(C);FailedCall(C);\n10;0;\nbad;0;\n")


if __name__ == "__main__":
    unittest.main()
