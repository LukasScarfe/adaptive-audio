# Spec: CI checks and controller tests for Adaptive Audio

Builder: Raccoon Sonnet. Planner: Raccoon Opus. Read `CLAUDE.md` in this repo first.

## Goal

Before the 0.8 beta goes public, GitHub Actions must check every push and PR with hassfest, HACS
validation, the existing schedule tests and new pytest tests of the controller's behaviour. The
tests pin down the behaviour rules in the `controller.py` docstring, so a future change that
breaks one fails CI.

## Decisions already made (don't revisit)

- **Test only. Do not change anything under `custom_components/`.** If a test shows that the
  integration breaks a rule in the `controller.py` docstring, stop and SendMessage `Raccoon Opus`
  with the failing test and its output. Don't "fix" the test to match the code, and don't fix the
  code.
- Use `pytest-homeassistant-custom-component` (phcc). Pin the newest release on PyPI that still
  runs on Python 3.13, and set the workflow's Python to whatever that phcc release requires.
- Keep `tests/test_schedule.py` as it is (plain unittest, runs with `python3 tests/test_schedule.py`).
  pytest also collects it, so CI runs it through pytest.
- Leave `dev/e2e.py` alone. It stays the manual check against the dev HA.
- No coverage tooling, no linters, no pre-commit and no extra dependencies beyond phcc.
- Do not tag, release or change `manifest.json` or `hacs.json`. Opus does the release.

## Files

```
.github/workflows/validate.yml     new
requirements_test.txt              new: phcc pinned (==), nothing else
tests/__init__.py                  new, empty
tests/conftest.py                  new
tests/test_controller.py           new
tests/test_config_flow.py          new
CLAUDE.md                          edit the Layout block + Dev loop: how to run the tests
.gitignore                         add .venv/ if you create one in the repo
```

### `.github/workflows/validate.yml`

Name it `Validate`. Trigger on push to main, on pull_request and on workflow_dispatch. Three jobs:

1. `hassfest`: `home-assistant/actions/hassfest@master` after checkout.
2. `hacs`: `hacs/action@main` with `category: integration` and `ignore: brands`. The icon lives in
   `custom_components/adaptive_audio/brand/`, not in the home-assistant/brands repo.
3. `tests`: set up Python, `pip install -r requirements_test.txt`, then `pytest tests -q`.

`permissions: contents: read`. Leave `pages.yml` alone.

### `tests/conftest.py`

- An autouse fixture that uses phcc's `enable_custom_integrations` fixture.
- Set `hass.config.time_zone` to `America/Vancouver` (await `hass.config.async_set_time_zone`)
  so schedule times read as local times.
- A fixture `speakers` that:
  - creates `media_player.a` and `media_player.b` with `hass.states.async_set` (state `idle`,
    attribute `volume_level: 0.5`, plus `source` where a test needs it). Set every attribute on
    every state update; `async_set` replaces the attributes.
  - registers a fake `media_player.volume_set` service with `hass.services.async_register`. It
    records each call in a list the test can read, then sets that entity's `volume_level` to the
    new level with `async_set`, keeping its state and other attributes. (Use this rather than
    `async_mock_service`: the controller reads the reported level back, so the fake must update
    the state.)
- A helper `async def setup_entry(hass, **options)` that builds a `MockConfigEntry`
  (domain `adaptive_audio`, title `Living room`, `options = {**DEFAULTS, "players": [...], **options}`),
  adds it, runs `hass.config_entries.async_setup` and `await hass.async_block_till_done()`.
  Return the entry. The controller is `entry.runtime_data`.
- Helpers to play, stop and hand-change a speaker by setting its state, then block till done.

Control time with phcc's `freezer` fixture plus `async_fire_time_changed` to fire the 1-minute
tick. The ramp sleeps `60 / max_rate` seconds between 1 % steps with `asyncio.sleep`. Advance the
frozen clock *and* fire time changed, and if the ramp's sleep doesn't advance under the frozen
clock, patch `asyncio.sleep` in `custom_components.adaptive_audio.controller` with a fake that
returns at once. Assert on the recorded calls, never on wall-clock timing.

### `tests/test_controller.py`

One test per rule. Each one asserts on the recorded `volume_set` calls and/or the target sensor's
attributes (`taken_over`, `quiet_active`, `cap_active`, `last_applied`). Use the default simple
schedule (40 % day from 07:30, 30 % from 19:00, 15 % from 22:00) and freeze the time where the
target is flat (12:00 → 40 %, 20:00 → 30 %, 03:00 → 15 %) unless a test needs a ramp.

1. **Fresh start:** stopped longer than `idle_gap` then playing → one call to the scheduled volume.
2. **Short pause:** stopped for less than `idle_gap` then playing → no call.
3. **Startup is not a fresh start:** a speaker whose first state is already `playing` (old state
   None) → no call.
4. **Skipped source:** `skip_sources: "Line In"`, speaker with `source: "Line In"` starts → no
   call. Matching ignores case.
5. **Disabled:** Adaptive Audio switch off → a fresh start makes no call.
6. **Hand change takes over (adapt on):** Adjust while playing on, speaker playing at the target,
   then set its `volume_level` to a level Adaptive Audio didn't set → it appears in `taken_over`,
   and the next ticks make no calls for it. A fresh start clears the takeover.
7. **Auto-reset:** `autoreset: 5` → after a hand change, ticks within 5 minutes leave it alone,
   and after 5 minutes it is adapted again.
8. **Adapt ramp:** adapt on, `max_rate: 3`, speaker playing at 50 % with target 40 % → steps are
   exactly 1 % each, toward the target, at most 3 per minute, and stop at the target.
9. **Adapt off:** the same setup with adapt off → no calls during play.
10. **Quiet on:** turning the Quiet switch on pulls a playing speaker above `quiet_volume` down to
    it, and a fresh start during quiet gets `quiet_volume`.
11. **Quiet from a linked entity:** `quiet_entity: input_boolean.night_mode`, `quiet_state: "on"`
    → that entity turning on behaves like test 10.
12. **Quiet off, instant:** `quiet_instant: true` → playing speakers go straight back to the
    target in one call.
13. **Quiet off, gradual:** `quiet_instant: false` → back up in 1 % steps at `max_rate`. This
    happens even with adapt off, and it clears any takeover.
14. **Night cap:** `cap_enabled: true`, cap hours 22:00–07:00, `cap_volume: 25`. At 23:00 a hand
    raise to 60 % is pulled back to 25 %. At 12:00 the same raise is left alone.
15. **Cap from a linked entity:** `cap_entity` turns on during cap hours → a playing speaker
    above the cap is pulled down at once.
16. **Quiet volume number:** while quiet is on, lowering `number.…_quiet_volume` below a playing
    speaker's level pulls it down to the new value.
17. **Apply button:** pressing `button.…_set_volume_now` sets every speaker that isn't `off` to the
    start volume and clears `taken_over`.

Find entity ids from the entity registry by unique id (`{entry_id}_{key}`, keys `enabled`, `quiet`,
`adapt`, `night_cap`, `target`, `quiet_volume`, `cap_volume`, `apply`) rather than hard-coding
the slugs.

### `tests/test_config_flow.py`

Drive the flows with `hass.config_entries.flow.async_init` and `async_configure`. Shape the input
the way the page does: top-level `name` (setup only) and sections `speakers`, `schedule`, `wake`,
`evening`, `bedtime` and `quiet_cap` (see `page_schema` and `dev/e2e.py::options`).

1. Setup with valid input creates an entry whose options hold the flat keys plus the anchor dicts.
2. Missing name or speakers → error `need_speakers`.
3. A speaker already in another entry → error `speaker_taken`, and the `taken` placeholder names
   the speaker and the other entry's title.
4. Configure on an entry keeping its own speakers → saves (doesn't flag itself).
5. Overlapping ramps (wake 07:30 with a 600-minute ramp) → error `bad_schedule`.

## Edge cases to watch

- The controller tells its own changes from hand changes by comparing levels within 0.015. The
  fake service must report exactly the level it was given (rounded to 2 decimals, as the
  controller sends it).
- Platforms restore switch state from `RestoreEntity`. Fresh test HA has no restore data, so the
  switches start as their defaults: enabled on, quiet off, adapt off.
- Turn switches on and off through `hass.services.async_call("switch", ...)` with
  `blocking=True`, not by touching the controller.

## Done when

- `pytest tests -q` passes locally (in a venv in your scratchpad, not on the host Python), and
  `python3 tests/test_schedule.py` still passes.
- The Validate workflow is committed and pushed to main and passes on GitHub. Check with
  `gh run watch` / `gh run view`. If hassfest or HACS fail on something in `custom_components/`
  or `hacs.json`, report it to Opus rather than changing it.
- `CLAUDE.md` says how to run the tests.
- Commit as Lukas (repo-local identity already set) with **no** Claude attribution lines.
- Report back to `Raccoon Opus`: the files changed, test count, the CI run URL, and anything that
  failed or was unclear.
