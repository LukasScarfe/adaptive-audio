# Adaptive Volume for Home Assistant

Your speakers start at a volume that suits the time of day: louder in the afternoon, quieter at
night. If you turn a speaker up or down while it plays, it stays where you put it.

**[Try the settings in your browser](https://lukasscarfe.github.io/ha-adaptive-volume/)**
and see the volume through the day as a chart, before or after you install it.

## How it works

- **A volume for each part of the day.** Set a daytime, evening and night volume, and the time
  each one starts. A time can be a clock time, or come from a time helper or a sun sensor (for
  example, Sun next rising). Or type your own list of times and volumes instead.
- **Smooth changes.** The volume can ease from one level to the next over a set number of
  minutes, change at an even rate, or change all at once.
- **Set when playback starts.** When a speaker starts playing after being stopped for a while
  (10 minutes by default), it starts at the scheduled volume. Shorter pauses keep your volume.
- **Adjust while playing (optional).** Turn on this switch and playing speakers follow the
  schedule, never faster than a rate you set (10% a minute by default). If you change a speaker's volume yourself, it stops
  following the schedule until it next starts playing, or after a number of minutes you choose.
- **Quiet mode.** A switch, and optionally another entity such as a night-mode switch, that sets
  speakers to a quiet volume and keeps them from going above it.
- **Night cap (optional).** A maximum volume during set hours. If someone turns a speaker up past
  it, it goes straight back down. It is on while its switch is on, or while another entity you
  pick is on. The start and end can be clock times or come from a time helper.
- **Leave some inputs alone.** For example, a speaker playing from Line In (a record player) is
  never changed.

## Setting it up

*Settings → Devices & services → Add integration → Adaptive Volume.* Everything is on one page.
To see what a schedule does before you set it, try it in the
[online tester](https://lukasscarfe.github.io/ha-adaptive-volume/): it draws the volume through
the day as you change the settings. The setup page links to it with your saved settings filled in.
Press Create to save it. Change anything later with **Configure**, which shows the same page. The
card shows the day's volume as a chart.

Add one for each speaker or group of speakers that should share a schedule.

## Card

The card comes with the integration, so you don't need to add a resource:

```yaml
type: custom:adaptive-volume-card
entity: sensor.adaptive_volume_living_room_scheduled_volume
title: Living room      # optional
show_history: true      # optional: shows each speaker's real volume today as dots
```

It shows the day's schedule, the time now, night cap hours, the quiet volume, and each
speaker's volume. Times use Home Assistant's time zone.

## Entities

Each one you add creates:

| Entity | What it does |
|---|---|
| `switch.…_adaptive_volume` | Turns it on or off |
| `switch.…_quiet_mode` | Quiet mode |
| `switch.…_night_cap` | The night cap |
| `switch.…_adjust_while_playing` | Playing speakers follow the schedule |
| `sensor.…_scheduled_volume` | The scheduled volume right now |
| `number.…_quiet_volume`, `number.…_night_cap_volume` | Change these volumes straight away |
| `button.…_set_volume_now` | Sets every speaker to the scheduled volume now |

## Install

In HACS (the Marketplace), add this repository as a custom repository with the type
*Integration*. Install **Adaptive Volume**, then restart Home Assistant.

## Good to know

- A speaker has to support setting its volume from Home Assistant.
- Some apps, such as Spotify, set their own volume when they start playing. Whichever change
  arrives last wins.
