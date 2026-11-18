"""Pure schedule math for Adaptive Volume. No Home Assistant imports, so it unit-tests alone.

Times are minutes after local midnight (0-1439). A schedule is a list of points, one per line
in the options flow:

    07:00 20          a clock time and a volume in percent
    sunrise+30 25     sunrise plus 30 minutes
    sunset-45 30      sunset minus 45 minutes
    sunset 30

The day is a circle: the last point carries past midnight to the first. In "curve" mode the
volume moves in a straight line between neighbouring points; in "steps" mode each point's
volume holds until the next point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DAY = 1440
MODE_CURVE = "curve"
MODE_STEPS = "steps"

_POINT_RE = re.compile(
    r"^\s*(?:(?P<clock>\d{1,2}:\d{2})|(?P<sun>sunrise|sunset)\s*(?P<off>[+-]\s*\d+)?)"
    r"\s+(?P<vol>\d{1,3})\s*%?\s*$",
    re.IGNORECASE,
)


class ScheduleError(ValueError):
    """A schedule line that can't be read."""


@dataclass(frozen=True)
class Point:
    """One schedule point, before sun anchors are resolved."""

    anchor: str  # "clock", "sunrise" or "sunset"
    minutes: int  # clock: minutes after midnight; sun: offset in minutes
    volume: int  # percent, 0-100

    def resolve(self, sunrise: int | None, sunset: int | None) -> int:
        """Minutes after midnight for this point, given today's sunrise/sunset."""
        if self.anchor == "clock":
            return self.minutes
        base = sunrise if self.anchor == "sunrise" else sunset
        if base is None:
            raise ScheduleError(f"no {self.anchor} time available")
        return (base + self.minutes) % DAY


def parse_points(text: str) -> list[Point]:
    """Parse the options-flow text into points. Raises ScheduleError on a bad line."""
    points: list[Point] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _POINT_RE.match(line)
        if not m:
            raise ScheduleError(f"line {n}: '{raw.strip()}' is not like '07:00 20' or 'sunset+30 25'")
        vol = int(m["vol"])
        if vol > 100:
            raise ScheduleError(f"line {n}: volume {vol} is over 100")
        if m["clock"]:
            h, mi = (int(x) for x in m["clock"].split(":"))
            if h > 23 or mi > 59:
                raise ScheduleError(f"line {n}: {m['clock']} is not a time of day")
            points.append(Point("clock", h * 60 + mi, vol))
        else:
            off = int(m["off"].replace(" ", "")) if m["off"] else 0
            points.append(Point(m["sun"].lower(), off, vol))
    if not points:
        raise ScheduleError("the schedule needs at least one point")
    return points


def uses_sun(points: list[Point]) -> bool:
    return any(p.anchor != "clock" for p in points)


def target_volume(
    now: int,
    points: list[Point],
    mode: str = MODE_CURVE,
    sunrise: int | None = None,
    sunset: int | None = None,
) -> float:
    """The schedule's volume (percent, unrounded) at `now` minutes after midnight."""
    resolved = sorted((p.resolve(sunrise, sunset), p.volume) for p in points)
    if len(resolved) == 1:
        return float(resolved[0][1])
    now %= DAY
    # The latest point at or before now; before the first point, the last one (yesterday).
    idx = max((i for i, (t, _) in enumerate(resolved) if t <= now), default=len(resolved) - 1)
    t0, v0 = resolved[idx]
    if mode == MODE_STEPS:
        return float(v0)
    t1, v1 = resolved[(idx + 1) % len(resolved)]
    span = (t1 - t0) % DAY
    if span == 0:
        return float(v0)
    frac = ((now - t0) % DAY) / span
    return v0 + (v1 - v0) * frac


def in_window(now: int, start: int, end: int) -> bool:
    """True if `now` lies in [start, end), wrapping past midnight. start == end means all day."""
    now %= DAY
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def parse_clock(value: str) -> int:
    """'HH:MM' or 'HH:MM:SS' to minutes after midnight."""
    parts = [int(x) for x in str(value).split(":")]
    return parts[0] * 60 + parts[1]
