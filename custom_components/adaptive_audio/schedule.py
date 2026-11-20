"""Pure schedule math for Adaptive Audio. No Home Assistant imports, so it unit-tests alone
(and runs in the online tester).

Times are minutes after local midnight (0-1439) and the day is a circle. Two schedule types:

Simple (Adaptive Lighting style): Wake, Evening (optional) and Bedtime, each a time of day with a
ramp length. After Wake the level is Day, after Evening it is Evening, after Bedtime it is Night.
Each change is spread over its ramp, centred on its time.

Custom: a list of points, one per line:

    07:00 20          a clock time and a volume in percent
    sunrise+30 25     sunrise plus 30 minutes
    sunset-45 30

Here each change spans the whole gap between neighbouring points.

Curves: "steps" (instant change), "linear" (straight ramp) or "sigmoid" (an S-curve, like
Adaptive Lighting's tanh).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

DAY = 1440
CURVE_STEPS = "steps"
CURVE_LINEAR = "linear"
CURVE_SIGMOID = "sigmoid"
_STEEPNESS = 6.0  # how sharp the middle of the sigmoid is

_POINT_RE = re.compile(
    r"^\s*(?:(?P<clock>\d{1,2}:\d{2})|(?P<sun>sunrise|sunset)\s*(?P<off>[+-]\s*\d+)?)"
    r"\s+(?P<vol>\d{1,3})\s*%?\s*$",
    re.IGNORECASE,
)


class ScheduleError(ValueError):
    """A schedule that can't be used."""


def shape(frac: float, curve: str) -> float:
    """Map ramp progress 0..1 to 0..1 for the curve. Sigmoid is a logistic rescaled to hit
    exactly 0 and 1 at the ends of the ramp."""
    frac = min(1.0, max(0.0, frac))
    if curve == CURVE_STEPS:
        return 1.0 if frac > 0 else 0.0
    if curve != CURVE_SIGMOID:
        return frac
    k = _STEEPNESS
    lo = 1 / (1 + math.exp(k / 2))
    hi = 1 / (1 + math.exp(-k / 2))
    return (1 / (1 + math.exp(-k * (frac - 0.5))) - lo) / (hi - lo)


def parse_clock(value) -> int:
    """'HH:MM' or 'HH:MM:SS' to minutes after midnight."""
    parts = [int(x) for x in str(value).split(":")]
    return parts[0] * 60 + parts[1]


def in_window(now: int, start: int, end: int) -> bool:
    """True if `now` lies in [start, end), wrapping past midnight. start == end means all day."""
    now %= DAY
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


# ---- Simple (Adaptive Lighting style) ------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """A change to `level` at `at`, spread over `ramp` minutes centred on `at`."""

    at: int
    ramp: int
    level: float


def _window(t: Transition, curve: str) -> tuple[int, int]:
    """Start minute and length of a transition's ramp."""
    ramp = 0 if curve == CURVE_STEPS else t.ramp
    return int(round(t.at - ramp / 2)) % DAY, ramp


def overlapping(trs: list[Transition], curve: str) -> bool:
    """True if any ramp runs into the next one. `trs` is sorted by time."""
    if len(trs) < 2:
        return False
    wins = [_window(t, curve) for t in trs]
    if sum(r for _, r in wins) >= DAY:
        return True
    return any(
        ramp > (wins[(i + 1) % len(wins)][0] - start) % DAY for i, (start, ramp) in enumerate(wins)
    )


def simple_target(now: int, trs: list[Transition], curve: str = CURVE_SIGMOID) -> float:
    """The simple schedule's volume (percent, unrounded) at `now`. `trs` is sorted by time."""
    if not trs:
        raise ScheduleError("the schedule needs at least one time")
    if len(trs) == 1:
        return trs[0].level
    now %= DAY
    wins = [_window(t, curve) for t in trs]
    # The transition whose ramp started most recently (smallest distance back from now).
    i = min(range(len(trs)), key=lambda j: (now - wins[j][0]) % DAY)
    start, ramp = wins[i]
    prev = trs[i - 1].level
    frac = 1.0 if ramp == 0 else ((now - start) % DAY) / ramp
    return prev + (trs[i].level - prev) * shape(frac, curve)


# ---- Custom points -------------------------------------------------------------------------


@dataclass(frozen=True)
class Point:
    """One custom point, before sun anchors are resolved."""

    anchor: str  # "clock", "sunrise" or "sunset"
    minutes: int  # clock: minutes after midnight; sun: offset in minutes
    volume: int  # percent, 0-100

    def resolve(self, sunrise: int | None, sunset: int | None) -> int:
        if self.anchor == "clock":
            return self.minutes
        base = sunrise if self.anchor == "sunrise" else sunset
        if base is None:
            raise ScheduleError(f"there is no {self.anchor} time today")
        return (base + self.minutes) % DAY


def parse_points(text: str) -> list[Point]:
    """Parse the custom schedule text. Raises ScheduleError on a bad line."""
    points: list[Point] = []
    for n, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _POINT_RE.match(line)
        if not m:
            raise ScheduleError(f"line {n} should look like 07:00 20 or sunset+30 25, not '{raw.strip()}'")
        vol = int(m["vol"])
        if vol > 100:
            raise ScheduleError(f"line {n} has a volume over 100")
        if m["clock"]:
            h, mi = (int(x) for x in m["clock"].split(":"))
            if h > 23 or mi > 59:
                raise ScheduleError(f"line {n} has {m['clock']}, which isn't a time of day")
            points.append(Point("clock", h * 60 + mi, vol))
        else:
            off = int(m["off"].replace(" ", "")) if m["off"] else 0
            points.append(Point(m["sun"].lower(), off, vol))
    if not points:
        raise ScheduleError("add at least one time and volume")
    return points


def uses_sun(points: list[Point]) -> bool:
    return any(p.anchor != "clock" for p in points)


def target_volume(
    now: int,
    points: list[Point],
    curve: str = CURVE_LINEAR,
    sunrise: int | None = None,
    sunset: int | None = None,
) -> float:
    """The custom schedule's volume (percent, unrounded) at `now`."""
    resolved = sorted((p.resolve(sunrise, sunset), p.volume) for p in points)
    if len(resolved) == 1:
        return float(resolved[0][1])
    now %= DAY
    idx = max((i for i, (t, _) in enumerate(resolved) if t <= now), default=len(resolved) - 1)
    t0, v0 = resolved[idx]
    if curve == CURVE_STEPS:
        return float(v0)
    t1, v1 = resolved[(idx + 1) % len(resolved)]
    span = (t1 - t0) % DAY
    if span == 0:
        return float(v0)
    return v0 + (v1 - v0) * shape(((now - t0) % DAY) / span, curve)
