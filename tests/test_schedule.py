"""Unit tests for the pure schedule math. Run: python3 tests/test_schedule.py"""

import importlib.util
import pathlib
import sys
import unittest

_path = pathlib.Path(__file__).parent.parent / "custom_components/adaptive_volume/schedule.py"
_spec = importlib.util.spec_from_file_location("schedule", _path)
s = importlib.util.module_from_spec(_spec)
sys.modules["schedule"] = s
_spec.loader.exec_module(s)

DEFAULT = "07:00 20\n10:00 40\n18:00 35\n22:00 15"


def hm(t: str) -> int:
    return s.parse_clock(t)


class ParseTests(unittest.TestCase):
    def test_clock_and_sun(self):
        pts = s.parse_points("07:00 20\nsunrise+30 25%\nsunset - 45 30\nsunset 10  # comment\n\n")
        self.assertEqual(
            pts,
            [
                s.Point("clock", 420, 20),
                s.Point("sunrise", 30, 25),
                s.Point("sunset", -45, 30),
                s.Point("sunset", 0, 10),
            ],
        )
        self.assertTrue(s.uses_sun(pts))
        self.assertFalse(s.uses_sun(s.parse_points(DEFAULT)))

    def test_errors(self):
        for bad in ["", "# only a comment", "7am 20", "25:00 20", "07:00 120", "07:00", "noon 20"]:
            with self.assertRaises(s.ScheduleError, msg=bad):
                s.parse_points(bad)


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.pts = s.parse_points(DEFAULT)

    def test_on_points(self):
        for t, v in [("07:00", 20), ("10:00", 40), ("18:00", 35), ("22:00", 15)]:
            self.assertAlmostEqual(s.target_volume(hm(t), self.pts), v)

    def test_curve_between(self):
        self.assertAlmostEqual(s.target_volume(hm("08:30"), self.pts), 30)
        self.assertAlmostEqual(s.target_volume(hm("20:00"), self.pts), 25)

    def test_curve_wraps_midnight(self):
        # 22:00 15 -> 07:00 20 is 9 h; 02:30 is halfway.
        self.assertAlmostEqual(s.target_volume(hm("02:30"), self.pts), 17.5)
        self.assertAlmostEqual(s.target_volume(hm("23:00"), self.pts), 15 + 5 / 9)

    def test_steps(self):
        self.assertEqual(s.target_volume(hm("09:59"), self.pts, s.MODE_STEPS), 20)
        self.assertEqual(s.target_volume(hm("03:00"), self.pts, s.MODE_STEPS), 15)
        self.assertEqual(s.target_volume(hm("10:00"), self.pts, s.MODE_STEPS), 40)

    def test_single_point(self):
        self.assertEqual(s.target_volume(hm("13:00"), s.parse_points("09:00 33")), 33)

    def test_sun_anchors_sorted(self):
        pts = s.parse_points("sunrise 20\n12:00 40\nsunset 30\nsunset+120 15")
        # Winter: sunrise 07:50, sunset 16:20.
        rise, set_ = hm("07:50"), hm("16:20")
        self.assertAlmostEqual(s.target_volume(hm("16:20"), pts, sunrise=rise, sunset=set_), 30)
        self.assertAlmostEqual(s.target_volume(hm("17:20"), pts, sunrise=rise, sunset=set_), 22.5)
        with self.assertRaises(s.ScheduleError):
            s.target_volume(600, pts)


class WindowTests(unittest.TestCase):
    def test_wrap(self):
        a, b = hm("22:00"), hm("07:00")
        self.assertTrue(s.in_window(hm("23:30"), a, b))
        self.assertTrue(s.in_window(hm("06:59"), a, b))
        self.assertFalse(s.in_window(hm("07:00"), a, b))
        self.assertFalse(s.in_window(hm("12:00"), a, b))

    def test_plain_and_all_day(self):
        self.assertTrue(s.in_window(hm("13:00"), hm("12:00"), hm("14:00")))
        self.assertFalse(s.in_window(hm("14:00"), hm("12:00"), hm("14:00")))
        self.assertTrue(s.in_window(5, 100, 100))


if __name__ == "__main__":
    unittest.main(verbosity=1)
