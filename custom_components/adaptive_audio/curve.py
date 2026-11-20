"""Turn an options dict into a volume-at-minute function. Shared by the controller, the
sensor's 24 h curve and the online tester, so they always agree. No Home Assistant imports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import schedule
from .const import (
    A_ENTITY,
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
    CONF_NIGHT_VOLUME,
    CONF_POINTS,
    CONF_SCHEDULE_TYPE,
    CONF_USE_EVENING,
    CURVE_SAMPLE_MINUTES,
    DEFAULTS,
)

# Looks up a time entity's time of day (minutes after midnight), or None if it has none now.
EntityMinute = Callable[[str], "int | None"]

LABELS = {"wake": "morning", "evening": "evening", "bedtime": "bedtime"}  # chart labels


def opt(options: dict[str, Any], key: str):
    return options.get(key, DEFAULTS.get(key))


def _transition(
    name: str, options: dict[str, Any], level: float, entity_minute: EntityMinute | None
) -> schedule.Transition:
    """One anchor of the simple schedule. A time entity wins; its time field is the fallback."""
    d = {**DEFAULTS[name], **(options.get(name) or {})}
    at = None
    if (eid := d.get(A_ENTITY)) and entity_minute:
        at = entity_minute(eid)
    if at is None:
        at = schedule.parse_clock(d[A_TIME])
    return schedule.Transition(at % schedule.DAY, max(0, int(d.get(A_RAMP) or 0)), level)


def anchors(
    options: dict[str, Any], entity_minute: EntityMinute | None = None
) -> list[tuple[str, schedule.Transition]]:
    """(name, transition) for the simple schedule, in Wake, Evening, Bedtime order."""
    levels = [("wake", CONF_DAY_VOLUME)]
    if opt(options, CONF_USE_EVENING):
        levels.append(("evening", CONF_EVENING_VOLUME))
    levels.append(("bedtime", CONF_NIGHT_VOLUME))
    return [(n, _transition(n, options, float(opt(options, k)), entity_minute)) for n, k in levels]


def time_entities(options: dict[str, Any]) -> list[str]:
    """Every time entity the schedule or cap hours follow (to rebuild when one changes)."""
    out = [options[k] for k in (CONF_CAP_START_ENTITY, CONF_CAP_END_ENTITY) if options.get(k)]
    if opt(options, CONF_SCHEDULE_TYPE) == "simple":
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
    """Only custom points can name sunrise or sunset."""
    if opt(options, CONF_SCHEDULE_TYPE) != "custom":
        return False
    return schedule.uses_sun(schedule.parse_points(opt(options, CONF_POINTS)))


def builder(
    options: dict[str, Any], sunrise: int | None, sunset: int | None, entity_minute: EntityMinute | None = None
) -> tuple[Callable[[int], float], list[dict[str, Any]]]:
    """A function minute -> volume % for these options and today's sun, plus the transitions
    (for plot markers). Raises ScheduleError if the schedule can't be used."""
    curve = opt(options, CONF_CURVE)
    if opt(options, CONF_SCHEDULE_TYPE) == "custom":
        points = schedule.parse_points(opt(options, CONF_POINTS))
        marks = [{"name": "", "at": p.resolve(sunrise, sunset), "ramp": 0} for p in points]
        return (lambda m: schedule.target_volume(m, points, curve, sunrise, sunset)), marks
    named = anchors(options, entity_minute)
    trs = sorted((t for _, t in named), key=lambda t: t.at)
    if schedule.overlapping(trs, curve):
        raise schedule.ScheduleError("two volume changes overlap. Make one shorter or move it")
    marks = [{"name": LABELS[n], "at": t.at, "ramp": 0 if curve == "steps" else t.ramp} for n, t in named]
    return (lambda m: schedule.simple_target(m, trs, curve)), marks


def samples(fn: Callable[[int], float]) -> list[float]:
    """The 24 h curve, one value per CURVE_SAMPLE_MINUTES, midnight to midnight inclusive."""
    return [round(fn(m % 1440), 1) for m in range(0, 1441, CURVE_SAMPLE_MINUTES)]
