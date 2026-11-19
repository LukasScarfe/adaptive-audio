"""Turn an options dict into a volume-at-minute function. Shared by the controller, the
sensor's 24 h curve and the Configure preview, so all three always agree."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Looks up a time entity's time of day (minutes after midnight), or None if it has none now.
EntityMinute = Callable[[str], "int | None"]

from . import schedule
from .const import (
    A_EARLIEST,
    A_ENTITY,
    A_KIND,
    A_LATEST,
    A_OFFSET,
    A_RAMP,
    A_TIME,
    ANCHORS,
    CONF_CAP_END,
    CONF_CAP_END_ENTITY,
    CONF_CAP_START,
    CONF_CAP_START_ENTITY,
    CONF_CURVE,
    CONF_DAY_VOLUME,
    CONF_EVENING_VOLUME,
    CONF_MODE,
    CONF_NIGHT_VOLUME,
    CONF_POINTS,
    CONF_SCHEDULE_TYPE,
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


def _anchor(d: dict[str, Any] | None, default: dict[str, Any], entity_minute: EntityMinute | None) -> schedule.Anchor:
    d = {**default, **(d or {})}
    clock = lambda v: None if v in (None, "") else schedule.parse_clock(v)  # noqa: E731
    time = schedule.parse_clock(d.get(A_TIME) or default[A_TIME])
    kind = d.get(A_KIND, "fixed")
    if (eid := d.get(A_ENTITY)) and entity_minute and (m := entity_minute(eid)) is not None:
        time, kind = m, "fixed"  # the entity wins; its time field is the fallback
    return schedule.Anchor(
        kind=kind,
        time=time,
        offset=int(d.get(A_OFFSET) or 0),
        earliest=clock(d.get(A_EARLIEST)),
        latest=clock(d.get(A_LATEST)),
        ramp=int(d.get(A_RAMP) or 0),
    )


def anchors(options: dict[str, Any], entity_minute: EntityMinute | None = None) -> list[tuple[str, schedule.Anchor, float]]:
    """(name, anchor, level after it) for the simple schedule."""
    a = lambda name: _anchor(options.get(name), DEFAULTS[name], entity_minute)  # noqa: E731
    out = [("wake", a("wake"), float(opt(options, CONF_DAY_VOLUME)))]
    if opt(options, CONF_USE_EVENING):
        out.append(("evening", a("evening"), float(opt(options, CONF_EVENING_VOLUME))))
    out.append(("bedtime", a("bedtime"), float(opt(options, CONF_NIGHT_VOLUME))))
    return out


def time_entities(options: dict[str, Any]) -> list[str]:
    """Every time entity the schedule or cap hours follow (to rebuild when one changes)."""
    out = [options[k] for k in (CONF_CAP_START_ENTITY, CONF_CAP_END_ENTITY) if options.get(k)]
    if schedule_type(options) == "simple":
        out += [(options.get(n) or {}).get(A_ENTITY) for n in ANCHORS]
    return sorted({e for e in out if e})


def cap_window(options: dict[str, Any], entity_minute: EntityMinute | None = None) -> tuple[int, int]:
    """Cap start and end (minutes); a linked time entity wins over the clock time."""
    out = []
    for key, ekey in ((CONF_CAP_START, CONF_CAP_START_ENTITY), (CONF_CAP_END, CONF_CAP_END_ENTITY)):
        m = None
        if (eid := options.get(ekey)) and entity_minute:
            m = entity_minute(eid)
        out.append(schedule.parse_clock(opt(options, key)) if m is None else m)
    return out[0], out[1]


def uses_sun(options: dict[str, Any]) -> bool:
    if schedule_type(options) == "custom":
        return schedule.uses_sun(schedule.parse_points(opt(options, CONF_POINTS)))
    return any(a.uses_sun for _, a, _ in anchors(options))


def builder(
    options: dict[str, Any], sunrise: int | None, sunset: int | None, entity_minute: EntityMinute | None = None
) -> tuple[Callable[[int], float], list[dict[str, Any]]]:
    """A function minute -> volume % for these options and today's sun, plus the transitions
    (for plot markers). Raises ScheduleError if the schedule can't be used."""
    curve = curve_name(options)
    # Steepness and ramp position are fixed for now (not offered in the UI).
    steep = float(DEFAULTS["steepness"])
    align = schedule.ALIGN_CENTRE
    if schedule_type(options) == "custom":
        points = schedule.parse_points(opt(options, CONF_POINTS))
        marks = [{"name": "", "at": p.resolve(sunrise, sunset), "ramp": 0} for p in points]
        return (lambda m: schedule.target_volume(m, points, curve, sunrise, sunset, steep)), marks
    named = anchors(options, entity_minute)
    trs = schedule.transitions([(a, v) for _, a, v in named], sunrise, sunset)
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
