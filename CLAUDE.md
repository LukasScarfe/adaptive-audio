# CLAUDE.md: ha-adaptive-volume developer guide

How this repo is built and tested. Keep it current (edit in place; git history is the
changelog). Raccoon context lives in the memory `[[ha-adaptive-volume-project]]` and
`~/claude/docs/ha-features.md` (Adaptive volume); link there rather than restating.

## What this is

A custom HA integration (domain `adaptive_volume`): a time-of-day default volume per speaker
group (Simple Adaptive-Lighting-style anchors or Custom points; sigmoid/linear/steps curves),
applied when playback starts after an idle gap, optionally adapted while playing (hand changes
take a speaker over), plus quiet volume and night cap. Bundled card and a Configure preview image. Behaviour rules are in the `controller.py` docstring; user-facing
summary in `README.md`.

## Layout

```
custom_components/adaptive_volume/
  schedule.py     PURE math (no HA import): sigmoid shape, anchors/transitions, custom points, windows
  curve.py        options dict -> volume-at-minute function + marks; shared by controller, sensor, preview
  plot.py         PURE server-side SVG of the curve (the Configure preview)
  http.py         preview view: flow stores pending options, embeds a signed /api/adaptive_volume/preview/<flow>.svg
  controller.py   per-entry state + event handling (player state changes, quiet entity, 1-min tick/adapt)
  __init__.py     setup; reloads on options change except LIVE_OPTIONS (the number entities)
  config_flow.py  setup: user -> schedule -> simple|custom -> preview. Configure: a menu
                  (speakers, schedule, quiet_cap, preview, save); nothing saved until Save
  frontend/adaptive-volume-card.js   the card, vanilla JS + SVG, registered in async_setup
  switch.py sensor.py number.py button.py entity.py   the per-instance entities (one service device)
  const.py        option keys + DEFAULTS
  strings.json + translations/en.json   keep identical (generated together)
tests/test_schedule.py   python3 tests/test_schedule.py
dev/docker-compose.yml   throwaway HA on raccoon:8126; dev/config/ is gitignored
dev/e2e.py               end-to-end checks against the dev HA's demo speakers
```

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
permanent UTC-7, so give the stand-in `Etc/GMT+7`. HA's `ha-markdown` keeps `<img>`, which is
what makes the preview step work.

## Releasing

Bump `version` in `manifest.json`, commit, tag `vX.Y.Z`, `gh release create`. HA picks up the
update in the Marketplace; an update needs an HA restart (Lukas does that).
