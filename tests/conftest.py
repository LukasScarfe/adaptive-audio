"""Shared fixtures: custom integrations on, Vancouver time, two fake speakers that record
`media_player.volume_set` calls and report the new level back (the controller reads it)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.adaptive_audio import controller as controller_module
from custom_components.adaptive_audio.const import DEFAULTS, DOMAIN

A = "media_player.a"
B = "media_player.b"


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def _no_frontend():
    """The integration depends on `frontend`, whose web files aren't installed for tests.
    Let it "set up" without them; the card's own registration still runs."""
    with (
        patch("homeassistant.components.frontend.async_setup", return_value=True),
        patch("custom_components.adaptive_audio.add_extra_js_url"),
    ):
        yield


@pytest.fixture(autouse=True)
async def _vancouver(hass: HomeAssistant):
    await hass.config.async_set_time_zone("America/Vancouver")


@pytest.fixture(autouse=True)
async def _unload_entries(hass: HomeAssistant):
    """Stop the controllers (and any ramp task) at the end of every test."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


class Speakers:
    """The fake speakers and what was asked of them."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, float]] = []

    def create(self, entity_id: str, state: str = "idle", level: float = 0.5, **attrs) -> None:
        self.hass.states.async_set(entity_id, state, {"volume_level": level, **attrs})

    async def _change(self, entity_id: str, state: str | None = None, **attrs) -> None:
        """Change the state and/or attributes. async_set replaces attributes, so keep the rest."""
        st = self.hass.states.get(entity_id)
        self.hass.states.async_set(
            entity_id, state if state is not None else st.state, {**st.attributes, **attrs}
        )
        await self.hass.async_block_till_done()

    async def play(self, entity_id: str = A) -> None:
        await self._change(entity_id, "playing")

    async def stop(self, entity_id: str = A) -> None:
        await self._change(entity_id, "idle")

    async def hand_change(self, entity_id: str, level: float) -> None:
        """Someone turns the volume up or down by hand."""
        await self._change(entity_id, volume_level=level)

    def level(self, entity_id: str = A) -> float:
        return self.hass.states.get(entity_id).attributes["volume_level"]

    def levels(self, entity_id: str = A) -> list[float]:
        return [lvl for pid, lvl in self.calls if pid == entity_id]


@pytest.fixture
def speakers(hass: HomeAssistant, freezer) -> Speakers:
    at(freezer, 12)  # freeze first, so the speakers' "stopped since" times are on the test clock
    sp = Speakers(hass)
    sp.create(A)
    sp.create(B)

    async def volume_set(call: ServiceCall) -> None:
        ids = call.data["entity_id"]
        for pid in [ids] if isinstance(ids, str) else ids:
            level = call.data["volume_level"]
            sp.calls.append((pid, level))
            st = hass.states.get(pid)
            hass.states.async_set(pid, st.state, {**st.attributes, "volume_level": level})

    hass.services.async_register("media_player", "volume_set", volume_set)
    return sp


async def setup_entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        options={**DEFAULTS, "players": [A, B], **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    """Find an entity by its unique id, `{entry_id}_{key}`, rather than by slug."""
    reg = er.async_get(hass)
    found = [e for e in reg.entities.values() if e.unique_id == f"{entry.entry_id}_{key}"]
    assert len(found) == 1, f"no entity for {key}"
    return found[0].entity_id


def attrs(hass: HomeAssistant, entry: MockConfigEntry, key: str = "target") -> dict:
    return dict(hass.states.get(entity_id(hass, entry, key)).attributes)


async def switch(hass: HomeAssistant, entry: MockConfigEntry, key: str, on: bool) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id(hass, entry, key)},
        blocking=True,
    )
    await hass.async_block_till_done()


async def tick(hass: HomeAssistant, freezer, minutes: int = 1) -> None:
    """Let `minutes` minutes pass, firing the controller's 1-minute tick each minute."""
    for _ in range(minutes):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await settle(hass)


async def settle(hass: HomeAssistant) -> None:
    """Block till done, and let a background ramp task run up to its next sleep."""
    for _ in range(3):
        await hass.async_block_till_done()
        await asyncio.sleep(0)


def at(freezer, hour: int, minute: int = 0, second: int = 0) -> None:
    """Freeze the clock at a Vancouver wall-clock time on 2026-11-20. The offset comes from the
    tzdata (BC is UTC-8 in older tzdata, permanent UTC-7 in newer), never a hard-coded one, so
    the schedule sees exactly the time the test names."""
    local = datetime(2026, 11, 20, hour, minute, second, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(dt_util.as_utc(local))


class Ramp:
    """Stands in for the controller's asyncio.sleep. The ramp waits there after each 1 % step
    until the test lets it go, so a test sees the steps one at a time and the delays asked for."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.delays: list[float] = []
        self._gate: asyncio.Future | None = None

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self._gate = asyncio.get_running_loop().create_future()
        await self._gate

    @property
    def waiting(self) -> bool:
        return self._gate is not None and not self._gate.done()

    async def step(self) -> bool:
        """Let the ramp take its next step. False if it isn't waiting (it has finished)."""
        if not self.waiting:
            return False
        self._gate.set_result(None)
        await settle(self.hass)
        return True

    async def run_out(self, limit: int = 200) -> None:
        for _ in range(limit):
            if not await self.step():
                return
        raise AssertionError("the ramp never finished")


@pytest.fixture
def ramp(hass: HomeAssistant, monkeypatch) -> Ramp:
    r = Ramp(hass)
    monkeypatch.setattr(
        controller_module, "asyncio", SimpleNamespace(sleep=r.sleep, Task=asyncio.Task)
    )
    return r
