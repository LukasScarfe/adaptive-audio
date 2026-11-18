# Adaptive Volume for Home Assistant

Adaptive brightness, but for speakers. Each speaker gets a sensible default volume for the time
of day, applied **when playback starts**. Turn it up or down while it plays and your choice
stands until the next fresh start.

## What it does

- **Simple schedule (like Adaptive Lighting):** Day, Evening (optional) and Night levels, changed
  at Wake, Evening and Bedtime anchors. Each anchor is a fixed time or sunrise/sunset plus an
  offset, can be clamped ("sunset, but not before 21:30"), and has a ramp length. Ramps are
  centred on the anchor or end at it.
- **Custom schedule:** your own points, one per line, e.g. `07:00 20`, `sunrise+30 25`,
  `sunset-45 30`. Each transition spans the gap to the next point.
- **Curves:** Sigmoid (an S-curve that eases in and out, with a steepness setting), Linear, or Steps.
- **Preview:** Configure shows today's curve as a picture before you save.
- **Fresh starts:** a speaker gets the schedule's volume when it starts playing after the
  **idle gap** (default 10 min) of not playing. Shorter pauses keep your volume.
- **Adapt while playing (switch):** playing speakers glide along the curve, at most *Adapt step*
  % per minute. If you change a speaker's volume by hand, it stops adapting until its next fresh
  start, or for *Hand-change reset* minutes if you set that.
- **Quiet:** a Quiet switch per instance, and optionally a linked entity (a night-mode switch, an
  `input_select` in a given state...). While quiet, fresh starts use the quiet volume, it is also
  the maximum, and turning quiet on pulls playing speakers down to it.
- **Night cap (optional):** during cap hours, turning a speaker above the cap volume pulls it
  straight back. Fresh starts never go above it either.
- **Skip sources:** sources where it never touches the volume, e.g. `Line In` for a turntable.

## Card

The integration registers its own card, so no Lovelace resource is needed:

```yaml
type: custom:adaptive-volume-card
entity: sensor.adaptive_volume_living_room_target_volume
title: Living room      # optional
show_history: true      # optional: today's actual speaker volumes as dots
```

It plots the 24 h curve, a now marker, ramps, cap hours and the quiet level, plus each speaker's
volume today. Times are in Home Assistant's time zone.

## Entities (per instance)

| Entity | What it is |
|---|---|
| `switch.…_adaptive_volume` | Turns the instance on or off |
| `switch.…_quiet` | Your quiet switch (attribute `quiet_active` includes the linked entity) |
| `switch.…_adapt_while_playing` | Glide playing speakers along the curve (attribute `taken_over`) |
| `sensor.…_target_volume` | The schedule's volume now; attributes: `start_volume`, `cap`, `curve` (24 h, 10-min steps), `last_applied`... |
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
