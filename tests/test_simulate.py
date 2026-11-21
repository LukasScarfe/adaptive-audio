"""simulate.py must agree with the real controller. Each scenario runs a whole day twice: through
simulate.run, and through the controller on a frozen clock (events on the minute, the 1-minute
tick 30 s later, ramp sleeps woken when the clock reaches them). The volume_set calls, with
their times, must match exactly."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.util import dt as dt_util

from custom_components.adaptive_audio import controller as controller_module
from custom_components.adaptive_audio import schedule, simulate
from custom_components.adaptive_audio.const import DEFAULTS

from .conftest import A, at, entity_id, settle, setup_entry, switch

# name, options, entities, start, events
SCENARIOS = [
    ("fresh start and short pause", {"adapt": False}, {}, {"volume": 50},
     [("08:00", "play"), ("08:30", "stop"), ("08:35", "play"), ("09:00", "stop"), ("12:00", "play")]),
    ("adapt follows the evening change", {"max_rate": 3}, {}, {"volume": 50},
     [("17:00", "play"), ("23:00", "stop")]),
    ("hand change, autoreset", {"autoreset": 20, "max_rate": 5}, {}, {"volume": 50},
     [("12:00", "play"), ("12:10", "volume", 70), ("13:00", "stop")]),
    ("hand change without autoreset", {}, {}, {},
     [("12:00", "play"), ("12:10", "volume", 70), ("19:30", "stop"), ("20:00", "play"), ("20:30", "stop")]),
    ("quiet on and off, gradual", {"adapt": False, "max_rate": 2}, {}, {},
     [("12:00", "play"), ("12:30", "quiet", True), ("12:40", "volume", 8), ("13:00", "quiet", False), ("14:00", "stop")]),
    ("quiet off, instant", {"adapt": False, "quiet_instant": True}, {}, {},
     [("12:00", "play"), ("12:30", "quiet", True), ("13:00", "quiet", False), ("14:00", "stop")]),
    ("quiet from an entity with its own state", {"adapt": False, "quiet_entity": "input_select.mode", "quiet_state": "Night"},
     {"input_select.mode": "Day"}, {},
     [("12:00", "play"), ("12:20", "entity", {"id": "input_select.mode", "state": "night"}),
      ("12:50", "entity", {"id": "input_select.mode", "state": "Day"}), ("14:00", "stop")]),
    ("night cap by switch and hand changes", {"adapt": False, "cap_volume": 20}, {}, {},
     [("21:00", "play"), ("21:30", "volume", 60), ("22:10", "cap", True), ("22:20", "volume", 50), ("23:30", "stop")]),
    ("cap hours begin while playing, adapt off", {"adapt": False, "cap_enabled": True, "cap_volume": 20}, {}, {},
     [("21:00", "play"), ("21:30", "volume", 35), ("23:30", "stop")]),
    ("cap hours begin while adapting", {"cap_enabled": True, "cap_volume": 20, "cap_start": "21:00:00", "max_rate": 2}, {},
     {}, [("20:00", "play"), ("23:30", "stop")]),
    ("night cap from an entity, hours from time helpers",
     {"cap_entity": "input_boolean.guests", "cap_start_entity": "input_datetime.cap_from", "cap_volume": 25},
     {"input_boolean.guests": "off", "input_datetime.cap_from": "20:00"}, {},
     [("19:00", "play"), ("20:30", "entity", {"id": "input_boolean.guests", "state": "on"}),
      ("21:00", "entity", {"id": "input_datetime.cap_from", "state": "21:30"}), ("22:00", "volume", 40), ("23:00", "stop")]),
    ("morning follows a time helper", {"wake": {"entity": "input_datetime.wake", "time": "07:30:00", "ramp": 30}},
     {"input_datetime.wake": "09:00"}, {},
     [("06:00", "play"), ("08:00", "entity", {"id": "input_datetime.wake", "state": "08:15"}), ("10:00", "stop")]),
    ("skipped input", {"adapt": False, "skip_sources": "Line In, Optical"}, {}, {"source": "Line In"},
     [("12:00", "play"), ("12:30", "stop"), ("12:31", "source", "TV"), ("13:00", "play"), ("13:30", "stop")]),
    ("disabled, then Set volume now", {}, {}, {"enabled": False},
     [("12:00", "play"), ("12:05", "volume", 80), ("12:30", "enabled", True), ("12:40", "apply"), ("13:00", "stop")]),
    ("adapt switched off mid-ramp", {"max_rate": 1}, {}, {"volume": 70},
     [("12:00", "play"), ("12:02", "volume", 70), ("12:03", "adapt", True), ("12:10", "adapt", False), ("13:00", "stop")]),
    ("custom schedule with sunset", {"schedule_type": "custom", "points": "07:00 20\nsunset-30 35\n22:00 15", "max_rate": 4},
     {}, {}, [("16:00", "play"), ("23:00", "stop")]),
]
RISE, SET = 7 * 60 + 25, 16 * 60 + 20  # Vancouver, 2026-11-20 (PST)


def _events(raw):
    return [{"at": e[0], "do": e[1], "value": e[2] if len(e) > 2 else None} for e in raw]


class TimedRamp:
    """The controller's ramp sleep, woken when the test clock reaches it."""

    def __init__(self) -> None:
        self.wake: float | None = None  # seconds after midnight
        self._gate: asyncio.Future | None = None
        self.now = 0.0

    async def sleep(self, delay: float) -> None:
        self.wake = self.now + delay
        self._gate = asyncio.get_running_loop().create_future()
        await self._gate

    def release(self) -> None:
        self.wake = None
        if self._gate is not None and not self._gate.done():
            self._gate.set_result(None)


async def _run_controller(hass, freezer, speakers, monkeypatch, options, entities, start, events):
    ramp = TimedRamp()
    monkeypatch.setattr(controller_module, "asyncio", SimpleNamespace(sleep=ramp.sleep, Task=asyncio.Task))
    at(freezer, 0)
    midnight = dt_util.utcnow()
    for eid, state in entities.items():
        hass.states.async_set(eid, state)
    hass.states.async_remove(A)  # the fixture made it at 12:00; "stopped since" must be midnight
    speakers.create(A, "playing" if start.get("playing") else "idle", round(start.get("volume", 50) / 100, 2),
                    **({"source": start["source"]} if start.get("source") else {}))
    await hass.async_block_till_done()
    entry = await setup_entry(hass, **{**options, "players": [A]})
    for key, on in (("enabled", start.get("enabled", True)), ("quiet", start.get("quiet", False))):
        await switch(hass, entry, key, on)
    speakers.calls.clear()

    def stamp():
        return (dt_util.utcnow() - midnight).total_seconds()

    calls: list[tuple[float, float]] = []
    seen = 0

    def collect():
        nonlocal seen
        for _, level in speakers.calls[seen:]:
            calls.append((stamp(), level))
        seen = len(speakers.calls)

    queue = sorted(((schedule.parse_clock(e["at"]) * 60, i, e) for i, e in enumerate(events)), key=lambda x: x[:2])
    timeline = [(t, 0, e) for t, _, e in queue] + [(m * 60 + 30, 1, None) for m in range(1440)]
    timeline.sort(key=lambda x: (x[0], x[1]))

    async def go(t):
        freezer.move_to(midnight + timedelta(seconds=t))
        ramp.now = t

    for t, kind, e in timeline:
        while ramp.wake is not None and ramp.wake <= t:
            await go(ramp.wake)
            ramp.release()
            await settle(hass)
            collect()
        await go(t)
        if kind == 1:
            async_fire_time_changed(hass)
        else:
            await _do(hass, entry, speakers, e)
        await settle(hass)
        collect()
    while ramp.wake is not None and ramp.wake < 1440 * 60:
        await go(ramp.wake)
        ramp.release()
        await settle(hass)
        collect()
    ramp.release()
    return calls


async def _do(hass, entry, speakers, e):
    do, v = e["do"], e["value"]
    if do == "play":
        await speakers.play(A)
    elif do == "stop":
        await speakers.stop(A)
    elif do == "volume":
        await speakers.hand_change(A, round(v / 100, 2))
    elif do == "source":
        await speakers._change(A, source=v)
    elif do in ("enabled", "quiet", "adapt"):
        await switch(hass, entry, do, v)
    elif do == "cap":
        await switch(hass, entry, "night_cap", v)
    elif do == "entity":
        hass.states.async_set(v["id"], v["state"])
        await hass.async_block_till_done()
    elif do == "apply":
        await hass.services.async_call("button", "press", {"entity_id": entity_id(hass, entry, "apply")}, blocking=True)
        await hass.async_block_till_done()


@pytest.fixture
async def _sun(hass):
    """Pin today's sunrise and sunset so both sides use the same ones."""
    from unittest.mock import patch

    with patch.object(controller_module, "sun_minutes", return_value=(RISE, SET)):
        yield


@pytest.mark.parametrize(("name", "options", "entities", "start", "raw"), SCENARIOS, ids=[s[0] for s in SCENARIOS])
async def test_simulator_matches_controller(hass, speakers, freezer, monkeypatch, _sun, name, options, entities, start, raw):
    events = _events(raw)
    sim = simulate.run({**DEFAULTS, **options}, RISE, SET, entities, start, events)
    expected = [(round(t, 1), round(v / 100, 2)) for t, v, _ in sim["sets"]]
    got = await _run_controller(hass, freezer, speakers, monkeypatch, options, entities, start, events)
    got = [(round(t, 1), lvl) for t, lvl in got]
    assert expected, "the scenario should set the volume at least once"
    assert got == expected


def test_looped_day_starts_as_it_ended():
    """With days > 1 the shown day begins exactly where it ends: volume and playing."""
    events = _events([("07:00", "play"), ("12:30", "volume", 64), ("15:00", "stop"), ("22:00", "play")])
    out = simulate.run({**DEFAULTS, "cap_enabled": True}, RISE, SET, {}, {"volume": 90}, events, days=3)
    assert out["trace"][0][1] == out["trace"][-1][1]
    assert out["playing"][0][0] == 0  # still playing from 22:00 the day before
    assert out["cap"] == [[0, 7 * 60], [22 * 60, 1440]]
