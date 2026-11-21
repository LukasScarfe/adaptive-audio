# CLAUDE.md: adaptive-audio developer guide

How this repo is built and tested. Keep it current (edit in place; git history is the
changelog). Raccoon context lives in the memory `[[adaptive-audio-project]]` and
`~/claude/docs/ha-features.md` (Adaptive audio); link there rather than restating.

## What this is

A custom HA integration (domain `adaptive_audio`): a time-of-day default volume per speaker
group (Simple Adaptive-Lighting-style anchors or Custom points; sigmoid/linear/steps curves),
applied when playback starts after an idle gap, optionally adapted while playing (hand changes
take a speaker over), plus quiet volume and night cap. Bundled card. Behaviour rules are in the `controller.py` docstring; user-facing
summary in `README.md`.

## Layout

```
custom_components/adaptive_audio/
  schedule.py     PURE math (no HA import): sigmoid shape, anchors/transitions, custom points, windows
  curve.py        options dict -> volume-at-minute function + marks; shared by controller, sensor, card
  controller.py   per-entry state + event handling (player state changes, quiet entity, 1-min tick/adapt)
  simulate.py     PURE: one speaker's day under the controller's rules, for the tester; change it with controller.py
  __init__.py     setup; reloads on options change except LIVE_OPTIONS (the number entities)
  config_flow.py  setup and Configure share one page of collapsible sections; submit saves
                  (re-shown only for a missing name/speaker or a broken schedule)
  frontend/adaptive-audio-card.js   the card, vanilla JS + SVG, registered in async_setup
  switch.py sensor.py number.py button.py entity.py   the per-instance entities (one service device)
  const.py        option keys + DEFAULTS
  brand/          icon.svg (source, Lukas's HA house theme: #4CAF50 speaker, #2E7D32 bar, #b9a3d6 lavender wave)
                  rendered to icon.png 256 / icon@2x.png 512, transparent; one icon reads on light and dark
  strings.json + translations/en.json   generated: edit dev/gen_strings.py, run it
tests/test_schedule.py   plain unittest for the pure schedule math (also collected by pytest)
tests/conftest.py        fixtures: fake speakers that record volume_set calls, frozen Vancouver clock, gated ramp sleep
                         (`at(freezer, h, m)` is local wall-clock time from the tzdata; never hard-code an offset)
tests/test_controller.py one test per rule in the controller.py docstring
tests/test_config_flow.py  setup/Configure page: errors, saved options, the tester link
tests/test_simulate.py   parity: each scenario through simulate.run and the real controller must give identical volume calls
pytest.ini  requirements_test.txt   asyncio_mode=auto; phcc pinned (needs Python 3.14)
dev/docker-compose.yml   throwaway HA on raccoon:8126 (dev/config/ is gitignored) + the local tester on :8127
dev/e2e.py               end-to-end checks against the dev HA's demo speakers
site/                    the online tester (GitHub Pages): index.html + app.js + style.css (lukas.css
                         + a Home Assistant style); runs const/schedule/curve/simulate.py in Pyodide
.github/workflows/validate.yml  hassfest, HACS validation and pytest on every push and PR
.github/workflows/pages.yml   publishes site/ + those four .py files into py/ on push to main
```

## Online tester

https://lukasscarfe.github.io/adaptive-audio/ has every Configure setting except the speakers. It
draws the day's curve from the integration's own `curve.builder`, and below it simulates one
speaker's day (play, stop, hand changes, switches, entity changes) with `simulate.run`. Keep
`schedule.py`, `curve.py`, `simulate.py` and `const.py` free of HA imports.

`simulate.py` restates the controller's rules without HA. When a rule in `controller.py` changes,
change `simulate.py` the same way and add a scenario to `tests/test_simulate.py`; that test fails
if the two disagree on any volume call or its timing. Linked entities are stand-ins in the tester:
a time entity is "a time helper" (its time in `entities`) or `sensor.sun_next_rising`/`setting`
(read from the page's sunrise and sunset); the quiet and night cap entities have a state you
change during the simulated day.

Settings ride in the URL hash (base64url JSON of the stored options, plus `rise`/`set`,
`entities` and the simulated day `sim`). `config_flow.tester_url` builds the link at the top of
the setup page from every page option, with today's sun times and linked entity values.
**Local copy:** http://raccoon:8127 serves the tester straight from the checkout (the `tester`
service in `dev/docker-compose.yml`, Caddy, config in `dev/Caddyfile`). Edits to `site/` or the
four .py files show on the next reload; no copying or restart. Screenshot it with
`~/scripts/screenshot.sh http://192.168.1.241:8127/` (`?style=ha`, `?theme=light`).

## Dev loop

Production HA is off-box and raccoon can't restart it, so develop against the dev container.

```bash
docker compose -f dev/docker-compose.yml up -d        # HA http://raccoon:8126 (dev / devdevdev), tester :8127
docker compose -f dev/docker-compose.yml restart      # after Python edits
python3 tests/test_schedule.py                        # pure math, no dependencies
python3 dev/e2e.py <token-file>                       # needs an entry with demo living_room + walkman
```

`dev/config/configuration.yaml` sets time zone America/Vancouver (HA defaults to UTC, which
makes the schedule look wrong), the demo media players and `input_boolean.night_mode` as a
linked quiet entity. Get a token through `/auth/login_flow` with the dev login.
The demo `lounge_room` player has sources but no volume_set, so the skip-source rule is only
checked on production (WiiM Line In). Onboarding tokens last 30 min; mint a long-lived one over
WS (`auth/long_lived_access_token`). The e2e adapt tests wait on the 1-min tick (~4 min total).

**Seeing the card:** the puppeteer Chromium (124) is too old for HA's modern frontend build, so HA
serves it the legacy build, which doesn't load extra modules (cards show "Configuration error").
Real browsers are fine. For a screenshot, render the card on a blank page with a stand-in `hass`
(`states`, `config.time_zone`, `callWS` returning history). The same old tzdata predates BC's
permanent UTC-7, so give the stand-in `Etc/GMT+7`.

## Tests

`pytest tests -q` needs Python 3.14 and `pip install -r requirements_test.txt` (the
pytest-homeassistant-custom-component release that matches a Home Assistant version; bump the
pin when you move to a newer HA). Raccoon's host Python has no venv module, so run it in Docker:

```bash
docker run --rm -v "$PWD":/w -w /w python:3.14-slim sh -c \
  "pip install -q -r requirements_test.txt && pytest tests -q"
```

The tests never touch a real speaker: `conftest.py` registers a fake `media_player.volume_set` that
records calls and reports the new level back. The `frontend` component is stubbed (its web files
aren't installed). A test that fails means the code broke a rule in the `controller.py`
docstring: fix the code, not the test, unless the rule itself changed.

## Releasing

Bump `version` in `manifest.json`, commit, tag `vX.Y.Z`, `gh release create`. HA picks up the
update in the Marketplace; an update needs an HA restart (Lukas does that).
