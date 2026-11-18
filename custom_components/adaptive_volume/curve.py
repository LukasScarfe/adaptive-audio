"""Turn an options dict into a volume-at-minute function. Shared by the controller, the
sensor's 24 h curve and the Configure preview, so all three always agree."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import schedule
from .const import (
    A_EARLIEST,
    A_KIND,
    A_LATEST,
    A_OFFSET,
    A_RAMP,
    A_TIME,
    CONF_ALIGN,
    CONF_CURVE,
    CONF_DAY_VOLUME,
    CONF_EVENING_VOLUME,
    CONF_MODE,
    CONF_NIGHT_VOLUME,
    CONF_POINTS,
    CONF_SCHEDULE_TYPE,
    CONF_STEEPNESS,
    CONF_USE_EVENING,
    CURVE_SAMPLE_MINUTES,
    DEFAULTS,
)


def opt(options: dict[str, Any], key: str):
    return options.get(key, DEFAULTS.get(key))


def schedule_type(options: dict[str, Any]) -> str:
    if CONF_SCHEDULE_TYPE not in options and CONF_POINTS in options:
        return "custom"  # an 0.1 entry
    return opt(options, CONF_SCHEDULE_TYPE)


def curve_name(options: dict[str, Any]) -> str:
    if CONF_CURVE not in options and CONF_MODE in options:
        return "steps" if options[CONF_MODE] == "steps" else "linear"
    return opt(options, CONF_CURVE)


def _anchor(d: dict[str, Any] | None, default: dict[str, Any]) -> schedule.Anchor:
    d = {**default, **(d or {})}
    clock = lambda v: None if v in (None, "") else schedule.parse_clock(v)  # noqa: E731
    return schedule.Anchor(
        kind=d.get(A_KIND, "fixed"),
        time=schedule.parse_clock(d.get(A_TIME) or default[A_TIME]),
        offset=int(d.get(A_OFFSET) or 0),
        earliest=clock(d.get(A_EARLIEST)),
        latest=clock(d.get(A_LATEST)),
        ramp=int(d.get(A_RAMP) or 0),
    )


def anchors(options: dict[str, Any]) -> list[tuple[str, schedule.Anchor, float]]:
    """(name, anchor, level after it) for the simple schedule."""
    out = [("wake", _anchor(options.get("wake"), DEFAULTS["wake"]), float(opt(options, CONF_DAY_VOLUME)))]
    if opt(options, CONF_USE_EVENING):
        out.append(
            ("evening", _anchor(options.get("evening"), DEFAULTS["evening"]), float(opt(options, CONF_EVENING_VOLUME)))
        )
    out.append(("bedtime", _anchor(options.get("bedtime"), DEFAULTS["bedtime"]), float(opt(options, CONF_NIGHT_VOLUME))))
    return out


def uses_sun(options: dict[str, Any]) -> bool:
    if schedule_type(options) == "custom":
        return schedule.uses_sun(schedule.parse_points(opt(options, CONF_POINTS)))
    return any(a.uses_sun for _, a, _ in anchors(options))


def builder(
    options: dict[str, Any], sunrise: int | None, sunset: int | None
) -> tuple[Callable[[int], float], list[dict[str, Any]]]:
    """A function minute -> volume % for these options and today's sun, plus the transitions
    (for plot markers). Raises ScheduleError if the schedule can't be used."""
    curve = curve_name(options)
    steep = float(opt(options, CONF_STEEPNESS))
    if schedule_type(options) == "custom":
        points = schedule.parse_points(opt(options, CONF_POINTS))
        marks = [{"name": "", "at": p.resolve(sunrise, sunset), "ramp": 0} for p in points]
        return (lambda m: schedule.target_volume(m, points, curve, sunrise, sunset, steep)), marks
    named = anchors(options)
    trs = schedule.transitions([(a, v) for _, a, v in named], sunrise, sunset)
    align = opt(options, CONF_ALIGN)
    if schedule.overlapping(trs, curve, align):
        raise schedule.ScheduleError("the ramps overlap: shorten a ramp or move an anchor")
    marks = [
        {"name": n, "at": a.resolve(sunrise, sunset), "ramp": 0 if curve == "steps" else a.ramp}
        for n, a, _ in named
    ]
    return (lambda m: schedule.simple_target(m, trs, curve, steep, align)), marks


def samples(fn: Callable[[int], float]) -> list[float]:
    """The 24 h curve, one value per CURVE_SAMPLE_MINUTES, midnight to midnight inclusive."""
    return [round(fn(m % 1440), 1) for m in range(0, 1441, CURVE_SAMPLE_MINUTES)]
