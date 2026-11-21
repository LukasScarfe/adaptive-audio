"""The setup and Configure page, driven the way the frontend drives it."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_audio.const import DEFAULTS, DOMAIN

from .conftest import A, B, setup_entry


def page(name: str | None = "Living room", players=(A,), **sections) -> dict:
    """A full page submit: top-level name, then the sections."""
    d = DEFAULTS
    out = {
        "speakers": {
            "players": list(players),
            "skip_sources": "",
            "idle_gap": d["idle_gap"],
            "adapt": d["adapt"],
            "autoreset": d["autoreset"],
            "max_rate": d["max_rate"],
        },
        "schedule": {
            k: d[k]
            for k in ("schedule_type", "curve", "day_volume", "use_evening", "evening_volume", "night_volume", "points")
        },
        "wake": dict(d["wake"]),
        "evening": dict(d["evening"]),
        "bedtime": dict(d["bedtime"]),
        "quiet_cap": {
            k: d[k]
            for k in ("quiet_volume", "quiet_instant", "cap_enabled", "cap_volume", "cap_start", "cap_end")
        },
    }
    if name is not None:
        out = {"name": name, **out}
    for key, val in sections.items():
        out[key] = {**out.get(key, {}), **val}
    return out


async def _setup_flow(hass, user_input):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


# 1
async def test_setup_creates_entry(hass, speakers):
    result = await _setup_flow(hass, page(speakers={"players": [A, B], "skip_sources": "Line In"}))
    assert result["type"] == "create_entry"
    assert result["title"] == "Living room"
    opts = result["options"]
    assert opts["players"] == [A, B]  # flat keys
    assert opts["skip_sources"] == "Line In"
    assert opts["day_volume"] == 40
    assert opts["quiet_volume"] == 10
    assert opts["wake"] == {"time": "07:30:00", "ramp": 60}  # anchors stay dicts
    assert opts["evening"] == {"time": "19:00:00", "ramp": 60}
    assert opts["bedtime"] == {"time": "22:00:00", "ramp": 90}
    assert "name" not in opts


# 2
async def test_missing_name_or_speakers(hass, speakers):
    for user_input in (page(name=""), page(players=())):
        result = await _setup_flow(hass, user_input)
        assert result["type"] == "form"
        assert result["errors"] == {"base": "need_speakers"}


# 3
async def test_speaker_in_another_entry(hass, speakers):
    speakers.create(A, friendly_name="Speaker A")
    MockConfigEntry(domain=DOMAIN, title="Kitchen", options={**DEFAULTS, "players": [A]}).add_to_hass(hass)
    result = await _setup_flow(hass, page(players=(A,)))
    assert result["type"] == "form"
    assert result["errors"] == {"base": "speaker_taken"}
    assert result["description_placeholders"]["taken"] == "Speaker A is already in Kitchen"


# 4
async def test_configure_keeps_own_speakers(hass, speakers):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], page(name=None, players=(A, B), schedule={"day_volume": 50})
    )
    assert result["type"] == "create_entry"
    assert entry.options["day_volume"] == 50
    assert entry.options["players"] == [A, B]


# 5
async def test_overlapping_ramps_are_refused(hass, speakers):
    # The ramp box stops at 480 minutes, so use the longest and put another change inside it:
    # wake 07:30 +-240 min covers 03:30 to 11:30, and the evening change moves to 10:00.
    result = await _setup_flow(
        hass, page(wake={"ramp": 480}, evening={"time": "10:00:00", "ramp": 60})
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "bad_schedule"}


async def test_tester_link_carries_every_setting(hass):
    """The tester link holds every option on the page but the speakers, plus what the linked
    entities hold now, so the tester can stand in for them."""
    import base64
    import json

    from custom_components.adaptive_audio.config_flow import FLAT, tester_url

    hass.states.async_set("input_datetime.wake", "07:05:00", {"has_time": True, "hour": 7, "minute": 5})
    hass.states.async_set("input_select.mode", "Night")
    options = {
        **DEFAULTS,
        "players": [A],
        "skip_sources": "Line In",
        "wake": {"entity": "input_datetime.wake", "time": "07:30:00", "ramp": 45},
        "quiet_entity": "input_select.mode",
        "quiet_state": "Night",
        "cap_entity": "input_boolean.missing",
    }
    url = tester_url(hass, options)
    raw = url.split("#", 1)[1]
    got = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    page_keys = {str(k) for schema in FLAT.values() for k in schema.schema} - {"players"}
    present = {k for k in page_keys if k in options}
    assert present <= set(got)
    assert "players" not in got
    assert got["skip_sources"] == "Line In"
    assert got["wake"] == {"entity": "input_datetime.wake", "time": "07:30:00", "ramp": 45}
    assert got["entities"] == {"input_datetime.wake": "07:05", "input_select.mode": "Night"}
