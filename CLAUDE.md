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
  __init__.py     setup; reloads on options change except LIVE_OPTIONS (the number entities)
  config_flow.py  setup and Configure share one page of collapsible sections; submit saves
                  (re-shown only for a missing name/speaker or a broken schedule)
  frontend/adaptive-audio-card.js   the card, vanilla JS + SVG, registered in async_setup
  switch.py sensor.py number.py button.py entity.py   the per-instance entities (one service device)
  const.py        option keys + DEFAULTS
  brand/          icon.svg + dark_icon.svg (sources, lukas.css light / Moss dark tokens) rendered to
                  icon.png 256 / icon@2x.png 512 and dark_icon(@2x).png, transparent; HA picks by theme
  strings.json + translations/en.json   generated: edit dev/gen_strings.py, run it
tests/test_schedule.py   python3 tests/test_schedule.py
dev/docker-compose.yml   throwaway HA on raccoon:8126; dev/config/ is gitignored
dev/e2e.py               end-to-end checks against the dev HA's demo speakers
site/                    the online tester (GitHub Pages): index.html + app.js + style.css (lukas.css
                         + a Home Assistant style); runs const/schedule/curve.py in Pyodide
.github/workflows/pages.yml   publishes site/ + those three .py files into py/ on push to main
```

## Online tester

https://lukasscarfe.github.io/adaptive-audio/ draws the curve from the integration's own
`curve.builder`, so keep `schedule.py`, `curve.py` and `const.py` free of HA imports. Settings ride in
the URL hash (base64url JSON of the stored options, plus `rise`/`set`); `config_flow.tester_url`
builds the link at the top of the setup page, with time entities and sun times resolved to today.
Preview locally: copy `site/` and the three .py files (into `py/`) to a scratch folder and serve it
with `python3 -m http.server`; screenshot with `~/scripts/screenshot.sh` (`?style=ha`, `?theme=light`).

## Dev loop

Production HA is off-box and raccoon can't restart it, so develop against the dev container.

```bash
docker compose -f dev/docker-compose.yml up -d        # http://raccoon:8126, user dev / devdevdev
docker compose -f dev/docker-compose.yml restart      # after Python edits
python3 tests/test_schedule.py
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

## Releasing

Bump `version` in `manifest.json`, commit, tag `vX.Y.Z`, `gh release create`. HA picks up the
update in the Marketplace; an update needs an HA restart (Lukas does that).
