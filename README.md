# Adaptive Volume for Home Assistant

Adaptive brightness, but for speakers. Each speaker gets a sensible default volume for the time
of day, applied **when playback starts**. Turn it up or down while it plays and your choice
stands until the next fresh start.

## What it does

- **Schedule:** points like `07:00 20` or `sunset+30 25`, one per line. In **Smooth curve** mode
  the volume glides between points; in **Steps** mode each point holds until the next. The day
  wraps, so the last point carries past midnight.
- **Fresh starts only:** a speaker gets the schedule's volume when it starts playing after the
  **idle gap** (default 10 min) of not playing. Shorter pauses keep your volume. Nothing changes
  mid-play.
- **Quiet:** a Quiet switch per instance, and optionally a linked entity (a night-mode switch, an
  `input_select` in a given state...). While quiet, fresh starts use the quiet volume, it is also
  the maximum, and turning quiet on pulls playing speakers down to it.
- **Night cap (optional):** during cap hours, turning a speaker above the cap volume pulls it
  straight back. Fresh starts never go above it either.
- **Skip sources:** sources where it never touches the volume, e.g. `Line In` for a turntable.

## Entities (per instance)

| Entity | What it is |
|---|---|
| `switch.…_adaptive_volume` | Turns the instance on or off |
| `switch.…_quiet` | Your quiet switch (attribute `quiet_active` includes the linked entity) |
| `sensor.…_target_volume` | The schedule's volume now; attributes: `start_volume`, `cap`, `last_applied`... |
| `number.…_quiet_volume`, `number.…_cap_volume` | Change live, no reload |
| `button.…_apply_volume_now` | Give every speaker its start volume now |

## Install

Add this repository as a custom repository (type *Integration*) in HACS / the Marketplace,
install **Adaptive Volume**, restart Home Assistant, then *Settings → Devices & services → Add
integration → Adaptive Volume*. Make one instance per speaker or speaker group. Everything is
editable later under **Configure**.

## Notes

- Volume is set with `media_player.volume_set`, so the player must support it.
- Some apps (e.g. a Spotify client) push their own volume when they start; whichever arrives
  last wins.
