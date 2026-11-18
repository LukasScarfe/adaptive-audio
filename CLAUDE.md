# CLAUDE.md: ha-adaptive-volume developer guide

How this repo is built and tested. Keep it current (edit in place; git history is the
changelog). Raccoon context lives in the memory `[[ha-adaptive-volume-project]]` and
`~/claude/docs/ha-features.md` (Adaptive volume); link there rather than restating.

## What this is

A custom HA integration (domain `adaptive_volume`): a time-of-day default volume per speaker
group, applied when playback starts after an idle gap, never mid-play except to enforce the quiet
volume or the night cap. Behaviour rules are in the `controller.py` docstring; user-facing
summary in `README.md`.

## Layout

```
custom_components/adaptive_volume/
  schedule.py     PURE math (no HA import): parse points, curve/steps target, time windows
  controller.py   per-entry state + event handling (player state changes, quiet entity, 1-min tick)
  __init__.py     setup; reloads on options change except LIVE_OPTIONS (the number entities)
  config_flow.py  user step (name, players) -> settings step; options flow edits everything
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
checked on production (WiiM Line In).

## Releasing

Bump `version` in `manifest.json`, commit, tag `vX.Y.Z`, `gh release create`. HA picks up the
update in the Marketplace; an update needs an HA restart (Lukas does that).
