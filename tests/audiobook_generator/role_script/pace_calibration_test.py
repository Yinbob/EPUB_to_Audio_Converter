import math
import unittest

from audiobook_generator.role_script.pace_calibration import calibrated_speeds


class PaceCalibrationTest(unittest.TestCase):
    def test_different_voice_durations_converge_to_narrator_duration(self):
        durations = {"narrator": 5000, "fast": 4000, "slow": 7000}
        speeds, limited = calibrated_speeds(durations, "narrator", 1.0)
        self.assertEqual(speeds, {"narrator": 1.0, "fast": 0.8, "slow": 1.4})
        self.assertFalse(limited)
        for role, duration in durations.items():
            self.assertAlmostEqual(duration / speeds[role], 5000)

    def test_preserves_baseline_speed_and_reports_clamped_roles(self):
        speeds, limited = calibrated_speeds({"a": 5000, "b": 50000}, "a", 0.9)
        self.assertEqual(speeds["a"], 0.9)
        self.assertEqual(speeds["b"], 4.0)
        self.assertEqual(limited, ["b"])

    def test_invalid_duration_or_speed_fails_without_partial_result(self):
        for duration in (0, -1, math.nan, math.inf):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                calibrated_speeds({"a": 5000, "b": duration}, "a", 1)
        for speed in (0, math.inf, math.nan, 5):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                calibrated_speeds({"a": 5000}, "a", speed)


if __name__ == "__main__":
    unittest.main()
