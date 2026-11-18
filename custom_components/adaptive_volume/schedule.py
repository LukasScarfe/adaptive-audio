"""Pure schedule math for Adaptive Volume. No Home Assistant imports, so it unit-tests alone.

Times are minutes after local midnight (0-1439) and the day is a circle. Two schedule types:

Simple (Adaptive Lighting style): anchors Wake, Evening (optional) and Bedtime. Each anchor is a
fixed time or sunrise/sunset plus an offset, optionally clamped between an earliest and latest
time, and has a ramp length. After Wake the level is Day, after Evening it is Evening, after
Bedtime it is Night. The change happens over the ramp, centred on the anchor or ending at it.

Custom: a list of points, one per line, like the 0.1 schedule:

    07:00 20          a clock time and a volume in percent
    sunrise+30 25     sunrise plus 30 minutes
    sunset-45 30

Here each transition spans the whole gap between neighbouring points.

Curves: "steps" (instant change), "linear" (straight ramp) or "sigmoid" (an S-curve, like
Adaptive Lighting's tanh). Steepness sets how sharp the middle of the S is.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

DAY = 1440
CURVE_STEPS = "steps"
CURVE_LINEAR = "linear"
CURVE_SIGMOID = "sigmoid"
ALIGN_CENTRE = "centre"
ALIGN_END = "end"

_POINT_RE = re.compile(
    r"^\s*(?:(?P<clock>\d{1,2}:\d{2})|(?P<sun>sunrise|sunset)\s*(?P<off>[+-]\s*\d+)?)"
    r"\s+(?P<vol>\d{1,3})\s*%?\s*$",
    re.IGNORECASE,
)


class ScheduleError(ValueError):
    """A schedule that can't be used."""


def shape(frac: float, curve: str, steepness: float = 6.0) -> float:
    """Map ramp progress 0..1 to 0..1 for the curve. Sigmoid is a logistic rescaled to hit
    exactly 0 and 1 at the ends of the ramp."""
    frac = min(1.0, max(0.0, frac))
    if curve == CURVE_STEPS:
        return 1.0 if frac > 0 else 0.0
    if curve != CURVE_SIGMOID:
        return frac
    k = max(0.5, float(steepness))
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
class Anchor:
    kind: str  # "fixed", "sunrise" or "sunset"
    time: int  # fixed: minutes after midnight (ignored for sun anchors)
    offset: int = 0  # minutes, added to sun anchors
    earliest: int | None = None
    latest: int | None = None
    ramp: int = 60  # minutes

    @property
    def uses_sun(self) -> bool:
        return self.kind in ("sunrise", "sunset")

    def resolve(self, sunrise: int | None, sunset: int | None) -> int:
        if self.kind == "fixed":
            return self.time % DAY
        base = sunrise if self.kind == "sunrise" else sunset
        if base is None:
            raise ScheduleError(f"no {self.kind} time available")
        t = base + self.offset
        if self.earliest is not None:
            t = max(t, self.earliest)
        if self.latest is not None:
            t = min(t, self.latest)
        return t % DAY


@dataclass(frozen=True)
class Transition:
    """A change to `level` at `at`, spread over `ramp` minutes."""

    at: int
    ramp: int
    level: float


def transitions(
    anchors: list[tuple[Anchor, float]], sunrise: int | None, sunset: int | None
) -> list[Transition]:
    """Resolve (anchor, level after it) pairs into transitions sorted by time."""
    out = [Transition(a.resolve(sunrise, sunset), max(0, int(a.ramp)), float(v)) for a, v in anchors]
    return sorted(out, key=lambda t: t.at)


def _window(t: Transition, curve: str, align: str) -> tuple[int, int]:
    """Start minute and length of a transition's ramp."""
    ramp = 0 if curve == CURVE_STEPS else t.ramp
    start = t.at - (ramp if align == ALIGN_END else ramp / 2)
    return int(round(start)) % DAY, ramp


def overlapping(trs: list[Transition], curve: str, align: str) -> bool:
    """True if any ramp runs into the next transition's ramp."""
    if len(trs) < 2:
        return False
    wins = [_window(t, curve, align) for t in trs]
    total = sum(r for _, r in wins)
    if total >= DAY:
        return True
    for i, (start, ramp) in enumerate(wins):
        nstart, _ = wins[(i + 1) % len(wins)]
        if ramp > (nstart - start) % DAY and len(wins) > 1:
            return True
    return False


def simple_target(
    now: int, trs: list[Transition], curve: str = CURVE_SIGMOID, steepness: float = 6.0,
    align: str = ALIGN_CENTRE,
) -> float:
    if not trs:
        raise ScheduleError("the schedule needs at least one anchor")
    if len(trs) == 1:
        return trs[0].level
    now %= DAY
    wins = [_window(t, curve, align) for t in trs]
    # The transition whose ramp started most recently (smallest distance back from now).
    i = min(range(len(trs)), key=lambda j: (now - wins[j][0]) % DAY)
    start, ramp = wins[i]
    prev = trs[i - 1].level
    since = (now - start) % DAY
    frac = 1.0 if ramp == 0 else since / ramp
    if curve == CURVE_STEPS:
        frac = 1.0
    return prev + (trs[i].level - prev) * shape(frac, curve, steepness)


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
            raise ScheduleError(f"no {self.anchor} time available")
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
    curve: str = CURVE_LINEAR,
    sunrise: int | None = None,
    sunset: int | None = None,
    steepness: float = 6.0,
) -> float:
    """The custom schedule's volume (percent, unrounded) at `now`."""
    if curve == "curve":  # 0.1 name for linear
        curve = CURVE_LINEAR
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
    return v0 + (v1 - v0) * shape(((now - t0) % DAY) / span, curve, steepness)
