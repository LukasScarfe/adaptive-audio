"""Unit tests for the pure schedule math. Run: python3 tests/test_schedule.py"""

import importlib.util
import pathlib
import sys
import unittest

_path = pathlib.Path(__file__).parent.parent / "custom_components/adaptive_audio/schedule.py"
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
        self.assertEqual(s.target_volume(hm("09:59"), self.pts, s.CURVE_STEPS), 20)
        self.assertEqual(s.target_volume(hm("03:00"), self.pts, s.CURVE_STEPS), 15)
        self.assertEqual(s.target_volume(hm("10:00"), self.pts, s.CURVE_STEPS), 40)

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


class ShapeTests(unittest.TestCase):
    def test_ends_and_middle(self):
        for c in (s.CURVE_LINEAR, s.CURVE_SIGMOID):
            self.assertAlmostEqual(s.shape(0, c), 0)
            self.assertAlmostEqual(s.shape(1, c), 1)
            self.assertAlmostEqual(s.shape(0.5, c), 0.5)
        # Sigmoid starts gently and is steeper in the middle.
        self.assertLess(s.shape(0.1, s.CURVE_SIGMOID), 0.1)
        self.assertGreater(s.shape(0.6, s.CURVE_SIGMOID), 0.6)
        self.assertLess(s.shape(0.1, s.CURVE_SIGMOID, 12), s.shape(0.1, s.CURVE_SIGMOID, 3))

    def test_custom_sigmoid(self):
        pts = s.parse_points(DEFAULT)
        self.assertAlmostEqual(s.target_volume(hm("08:30"), pts, s.CURVE_SIGMOID), 30)
        self.assertLess(s.target_volume(hm("07:30"), pts, s.CURVE_SIGMOID), s.target_volume(hm("07:30"), pts))


def simple(evening=True, kind="fixed", **kw):
    A = s.Anchor
    pairs = [(A("fixed", hm("07:30"), ramp=60), 40)]
    if evening:
        pairs.append((A("fixed", hm("19:00"), ramp=60), 30))
    pairs.append((A(kind, hm("22:00"), ramp=90, **kw), 15))
    return pairs


class SimpleTests(unittest.TestCase):
    def target(self, t, pairs=None, curve=s.CURVE_SIGMOID, align=s.ALIGN_CENTRE, rise=None, set_=None):
        trs = s.transitions(pairs or simple(), rise, set_)
        return s.simple_target(hm(t), trs, curve, 6, align)

    def test_levels_hold(self):
        self.assertAlmostEqual(self.target("12:00"), 40)
        self.assertAlmostEqual(self.target("20:00"), 30)
        self.assertAlmostEqual(self.target("03:00"), 15)

    def test_centred_ramp(self):
        self.assertAlmostEqual(self.target("07:00"), 15)
        self.assertAlmostEqual(self.target("07:30"), 27.5)
        self.assertAlmostEqual(self.target("08:00"), 40)
        self.assertAlmostEqual(self.target("22:00"), 22.5)
        self.assertAlmostEqual(self.target("22:45"), 15)

    def test_end_aligned(self):
        self.assertAlmostEqual(self.target("21:59", align=s.ALIGN_END), 15 + 0.0001, places=0)
        self.assertAlmostEqual(self.target("20:30", align=s.ALIGN_END), 30)
        self.assertAlmostEqual(self.target("21:15", align=s.ALIGN_END), 22.5)

    def test_steps_and_linear(self):
        self.assertEqual(self.target("07:29", curve=s.CURVE_STEPS), 15)
        self.assertEqual(self.target("07:30", curve=s.CURVE_STEPS), 40)
        self.assertAlmostEqual(self.target("07:15", curve=s.CURVE_LINEAR), 21.25)

    def test_no_evening(self):
        self.assertAlmostEqual(self.target("20:00", simple(evening=False)), 40)

    def test_sun_clamp(self):
        # Bedtime = sunset (16:25 in winter), but never before 21:00.
        pairs = simple(kind="sunset", earliest=hm("21:00"))
        trs = s.transitions(pairs, hm("07:50"), hm("16:25"))
        self.assertEqual(next(x.at for x in trs if x.level == 15), hm("21:00"))
        pairs = simple(kind="sunset", offset=30, latest=hm("21:00"))
        trs = s.transitions(pairs, hm("07:50"), hm("16:25"))
        self.assertEqual(next(x.at for x in trs if x.level == 15), hm("16:55"))

    def test_overlap(self):
        trs = s.transitions(simple(), None, None)
        self.assertFalse(s.overlapping(trs, s.CURVE_SIGMOID, s.ALIGN_CENTRE))
        A = s.Anchor
        bad = s.transitions([(A("fixed", hm("19:00"), ramp=240), 30), (A("fixed", hm("20:00"), ramp=60), 15)], None, None)
        self.assertTrue(s.overlapping(bad, s.CURVE_LINEAR, s.ALIGN_CENTRE))
        self.assertFalse(s.overlapping(bad, s.CURVE_STEPS, s.ALIGN_CENTRE))


if __name__ == "__main__":
    unittest.main(verbosity=1)
