"""One test per rule in the controller.py docstring. Default schedule: 40 % from 07:30,
30 % from 19:00, 15 % from 22:00, so 12:00 -> 40 %, 20:00 -> 30 %, 03:00 -> 15 %."""

from __future__ import annotations

import pytest

from .conftest import A, B, at, attrs, entity_id, setup_entry, switch, tick


async def _press(hass, entry, key):
    await hass.services.async_call("button", "press", {"entity_id": entity_id(hass, entry, key)}, blocking=True)
    await hass.async_block_till_done()


async def _quiet(hass, entry, on):
    await switch(hass, entry, "quiet", on)


# 1
async def test_fresh_start_gets_scheduled_volume(hass, speakers, freezer):
    at(freezer, 12)
    entry = await setup_entry(hass)
    await tick(hass, freezer, 11)  # idle for longer than idle_gap (10)
    await speakers.play(A)
    assert speakers.calls == [(A, 0.4)]
    assert attrs(hass, entry)["last_applied"][A]["volume"] == 40


# 2
async def test_short_pause_is_not_a_fresh_start(hass, speakers, freezer):
    at(freezer, 12)
    await setup_entry(hass)
    await speakers.play(A)
    await speakers.stop(A)
    await tick(hass, freezer, 5)  # less than idle_gap
    await speakers.play(A)
    assert speakers.calls == []


# 3
async def test_startup_is_not_a_fresh_start(hass, speakers, freezer):
    at(freezer, 12)
    await setup_entry(hass)
    hass.states.async_remove(A)
    await hass.async_block_till_done()
    await tick(hass, freezer, 11)
    speakers.create(A, "playing")  # first state seen is already playing (old state None)
    await hass.async_block_till_done()
    assert speakers.calls == []


# 4
@pytest.mark.parametrize("source", ["Line In", "LINE IN"])
async def test_skipped_source_is_never_touched(hass, speakers, freezer, source):
    at(freezer, 12)
    speakers.create(A, source=source)
    speakers.create(B, source="Optical")
    await setup_entry(hass, skip_sources="Line In")
    await tick(hass, freezer, 11)
    await speakers.play(A)
    assert speakers.calls == []
    await speakers.play(B)  # control: a speaker on another source does get set
    assert speakers.calls == [(B, 0.4)]


# 5
async def test_disabled_makes_no_calls(hass, speakers, freezer):
    at(freezer, 12)
    entry = await setup_entry(hass)
    await switch(hass, entry, "enabled", False)
    await tick(hass, freezer, 11)
    await speakers.play(A)
    assert speakers.calls == []


# 6
async def test_hand_change_takes_over_until_fresh_start(hass, speakers, freezer, ramp):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass)
    await switch(hass, entry, "adapt", True)
    await speakers.hand_change(A, 0.7)
    assert attrs(hass, entry)["taken_over"] == [A]
    await tick(hass, freezer, 3)
    assert speakers.calls == []
    # a fresh start clears the takeover
    await speakers.stop(A)
    await tick(hass, freezer, 11)
    await speakers.play(A)
    assert speakers.calls == [(A, 0.4)]
    assert attrs(hass, entry)["taken_over"] == []


# 7
async def test_autoreset_resumes_adapting(hass, speakers, freezer, ramp):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, autoreset=5, max_rate=3)
    await switch(hass, entry, "adapt", True)
    await speakers.hand_change(A, 0.7)
    await tick(hass, freezer, 4)
    assert speakers.calls == []
    assert attrs(hass, entry)["taken_over"] == [A]
    await tick(hass, freezer, 1)  # five minutes since the hand change
    assert speakers.calls == [(A, 0.69)]
    assert attrs(hass, entry)["taken_over"] == []


# 8
async def test_adapt_ramps_one_percent_at_a_time(hass, speakers, freezer, ramp):
    at(freezer, 12)
    speakers.create(A, "playing", 0.5)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, max_rate=3)
    await switch(hass, entry, "adapt", True)
    await tick(hass, freezer, 1)
    await ramp.run_out()
    levels = speakers.levels(A)
    assert levels == [round(0.49 - 0.01 * i, 2) for i in range(10)]  # 49 % ... 40 %, then stops
    assert ramp.delays and all(d == 20 for d in ramp.delays)  # 3 steps a minute at most
    await tick(hass, freezer, 3)
    await ramp.run_out()
    assert len(speakers.calls) == 10  # at the target: nothing more


# 9
async def test_adapt_off_leaves_volume_alone(hass, speakers, freezer, ramp):
    at(freezer, 12)
    speakers.create(A, "playing", 0.5)
    await hass.async_block_till_done()
    await setup_entry(hass, max_rate=3, adapt=False)
    await tick(hass, freezer, 5)
    assert speakers.calls == []


# 10
async def test_quiet_switch_pulls_down_and_sets_start_volume(hass, speakers, freezer):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass)
    await _quiet(hass, entry, True)
    assert speakers.calls == [(A, 0.1)]
    assert attrs(hass, entry)["quiet_active"] is True
    await speakers.stop(A)
    await tick(hass, freezer, 11)
    await speakers.play(A)
    assert speakers.calls[-1] == (A, 0.1)


# 11
async def test_quiet_from_linked_entity(hass, speakers, freezer):
    at(freezer, 12)
    hass.states.async_set("input_boolean.night_mode", "off")
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, quiet_entity="input_boolean.night_mode", quiet_state="on")
    hass.states.async_set("input_boolean.night_mode", "on")
    await hass.async_block_till_done()
    assert speakers.calls == [(A, 0.1)]
    assert attrs(hass, entry)["quiet_active"] is True
    await speakers.stop(A)
    await tick(hass, freezer, 11)
    await speakers.play(A)
    assert speakers.calls[-1] == (A, 0.1)


# 12
async def test_quiet_off_instant(hass, speakers, freezer):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, quiet_instant=True)
    await _quiet(hass, entry, True)
    speakers.calls.clear()
    await _quiet(hass, entry, False)
    assert speakers.calls == [(A, 0.4)]


# 13
async def test_quiet_off_gradual_even_with_adapt_off(hass, speakers, freezer, ramp):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, quiet_instant=False, max_rate=3, adapt=False)
    await _quiet(hass, entry, True)
    await speakers.hand_change(A, 0.08)  # a hand change during quiet takes the speaker over
    assert attrs(hass, entry)["taken_over"] == [A]
    speakers.calls.clear()
    await _quiet(hass, entry, False)
    assert attrs(hass, entry)["adapt"] is False
    assert attrs(hass, entry)["taken_over"] == []  # quiet off clears the takeover
    await ramp.run_out()
    levels = speakers.levels(A)
    assert levels == [round(0.09 + 0.01 * i, 2) for i in range(32)]  # 9 % ... 40 %, 1 % steps
    assert all(d == 20 for d in ramp.delays)


# 14
async def test_night_cap_pulls_back_only_in_cap_hours(hass, speakers, freezer):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, cap_enabled=True, cap_start="22:00:00", cap_end="07:00:00", cap_volume=25)
    await speakers.hand_change(A, 0.6)
    assert speakers.calls == []  # noon: not cap hours
    assert attrs(hass, entry)["cap_active"] is False
    at(freezer, 23)
    await speakers.hand_change(A, 0.7)
    assert speakers.calls == [(A, 0.25)]
    assert attrs(hass, entry)["cap_active"] is True


# 14b
async def test_night_cap_applies_when_cap_hours_begin_mid_play(hass, speakers, freezer):
    at(freezer, 21, 58)
    speakers.create(A, "playing", 0.35)
    await hass.async_block_till_done()
    await setup_entry(hass, cap_enabled=True, cap_start="22:00:00", cap_end="07:00:00", cap_volume=20, adapt=False)
    await tick(hass, freezer, 1)  # 21:59: not cap hours yet, and adapting is off
    assert speakers.calls == []
    await tick(hass, freezer, 1)  # 22:00: cap hours begin
    assert speakers.calls == [(A, 0.2)]


# 15
async def test_cap_from_linked_entity(hass, speakers, freezer):
    at(freezer, 23)
    hass.states.async_set("input_boolean.cap", "off")
    speakers.create(A, "playing", 0.6)
    await hass.async_block_till_done()
    entry = await setup_entry(hass, cap_entity="input_boolean.cap", cap_volume=25)
    assert speakers.calls == []
    hass.states.async_set("input_boolean.cap", "on")
    await hass.async_block_till_done()
    assert speakers.calls == [(A, 0.25)]
    assert attrs(hass, entry)["cap_active"] is True


# 16
async def test_lowering_quiet_volume_applies_at_once(hass, speakers, freezer):
    at(freezer, 12)
    speakers.create(A, "playing", 0.4)
    await hass.async_block_till_done()
    entry = await setup_entry(hass)
    await _quiet(hass, entry, True)
    assert speakers.calls == [(A, 0.1)]
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id(hass, entry, "quiet_volume"), "value": 5}, blocking=True
    )
    await hass.async_block_till_done()
    assert speakers.calls[-1] == (A, 0.05)


# 17
async def test_apply_button_sets_every_speaker_that_is_not_off(hass, speakers, freezer):
    at(freezer, 12)
    speakers.create(A, "playing", 0.9)
    await hass.async_block_till_done()
    entry = await setup_entry(hass)
    await speakers.hand_change(A, 0.8)
    assert attrs(hass, entry)["taken_over"] == [A]
    await _press(hass, entry, "apply")
    assert sorted(speakers.calls) == [(A, 0.4), (B, 0.4)]  # B is idle, not off
    assert attrs(hass, entry)["taken_over"] == []
    speakers.calls.clear()
    await speakers.stop(B)
    speakers.create(B, "off", 0.5)
    await hass.async_block_till_done()
    await _press(hass, entry, "apply")
    assert speakers.calls == [(A, 0.4)]


# Adjust while playing is an option now (default on); before 0.8.1 it was a restored switch.
async def test_adapt_defaults_on_and_the_switch_sets_the_option(hass, speakers, freezer):
    entry = await setup_entry(hass)
    assert attrs(hass, entry)["adapt"] is True
    await switch(hass, entry, "adapt", False)
    assert entry.options["adapt"] is False
    assert attrs(hass, entry)["adapt"] is False


async def test_old_switch_state_becomes_the_option(hass, speakers, freezer):
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    from homeassistant.core import State

    entry = await setup_entry(hass)
    eid = entity_id(hass, entry, "adapt")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, options={k: v for k, v in entry.options.items() if k != "adapt"})
    mock_restore_cache(hass, [State(eid, "off")])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options["adapt"] is False
