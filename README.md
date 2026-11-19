![Version](https://img.shields.io/github/v/release/LukasScarfe/adaptive-audio?style=for-the-badge)

# Adaptive Audio for Home Assistant

Adaptive Audio is a custom integration for [Home Assistant](https://www.home-assistant.io/) that
sets your speakers to a volume that suits the time of day. Music starts a little louder in the
afternoon and softer late at night, without you reaching for the volume first. If you do change
it, your change wins.

Think of it as [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting), but for
sound. Adaptive Lighting sets a light's brightness when you turn it on. Adaptive Audio sets a
speaker's volume when it starts playing.

> **[Try it in your browser](https://lukasscarfe.github.io/adaptive-audio/)**: change the
> settings and see the volume through the day as a chart, before or after you install it.

## Contents

- [What it does](#what-it-does)
- [Install](#install)
- [Set it up](#set-it-up)
- [Settings](#settings)
- [Entities](#entities)
- [Card](#card)
- [Good to know](#good-to-know)
- [Troubleshooting](#troubleshooting)

## What it does

### A volume for each part of the day

You set three volumes, and when each one starts:

| Part of the day | Starts at (default) | Volume (default) |
|---|---|---|
| Daytime | Morning, 07:30 | 40% |
| Evening | Evening, 19:00 | 30% |
| Night | Bedtime, 22:00 | 15% |

Each time can be a clock time, or come from another entity: a time helper, or a sun sensor such
as *Sun next rising*. You can leave out the evening volume, or type your own list of times and
volumes instead (times can be `sunrise` or `sunset`, plus or minus minutes).

The volume doesn't have to jump at each time. It can ease from one level to the next over a set
number of minutes, change at an even rate, or change all at once.

### Set when playback starts

When a speaker starts playing after it has been stopped for a while (10 minutes by default), it
starts at the scheduled volume. A shorter pause, such as skipping a track or pausing to answer the
door, keeps whatever volume you had.

### Your change wins

Change a speaker's volume yourself and Adaptive Audio leaves it there. The next time the speaker
starts playing after a break, it goes back to the schedule.

### Adjust while playing (optional)

By default the volume is only set when playback starts. Turn on **Adjust while playing** and
speakers that are already playing slowly follow the schedule too: as the evening gets later, the
volume drifts down. It never moves faster than a rate you set (10% a minute by default), so you
won't notice a jump.

If you change a speaker's volume while this is on, that speaker stops following the schedule
until it next starts playing, or after a number of minutes you choose.

### Quiet mode

A switch that sets every speaker to a quiet volume (10% by default) and keeps them from going
above it. Turning it on lowers speakers that are already playing. You can also link it to
another entity, for example a *night mode* or *baby asleep* switch, so quiet mode is on whenever
that entity is.

### Night cap (optional)

A maximum volume during set hours, for example no louder than 25% between 22:00 and 07:00. If
someone turns a speaker up past it, it goes straight back down to the cap. The night cap is on
while its switch is on, or while another entity you pick is on. The start and end can be clock
times or come from a time helper.

### Leave some inputs alone

List the inputs it should never touch. For example, a speaker playing from *Line In* (a record
player) keeps whatever volume you set by hand.

## Install

Adaptive Audio isn't listed in the Marketplace (HACS) yet, so add it as a custom repository
first.

### Marketplace (recommended)

Select this button to open your Home Assistant and add the repository:

[![Open your Home Assistant instance and add this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=LukasScarfe&repository=adaptive-audio&category=integration)

Or add it by hand:

1. Open **Marketplace** in the sidebar.
2. Open the menu (⋮) in the top right and choose **Custom repositories**.
3. Add a repository. For **GitHub link** enter `https://github.com/LukasScarfe/adaptive-audio`,
   and for **Type** choose **Integration**. If you haven't connected GitHub yet, Home Assistant
   asks you to do that first.
4. Find **Adaptive Audio** in the Marketplace, open it and select **Install**.
5. Restart Home Assistant.

On Home Assistant versions from before the Marketplace, the same steps work in HACS.

### By hand

1. Download the latest release from the
   [releases page](https://github.com/LukasScarfe/adaptive-audio/releases) (*Source code
   (zip)*) and unzip it.
2. Copy the `custom_components/adaptive_audio` folder into the `custom_components` folder in your
   Home Assistant configuration folder (the one with `configuration.yaml`). Create
   `custom_components` if it isn't there. You should end up with
   `config/custom_components/adaptive_audio/manifest.json`.
3. Restart Home Assistant.

To update by hand, replace the folder with the one from the newer release and restart again.

## Set it up

1. Go to **Settings → Devices & services → Add integration** and search for **Adaptive Audio**.
2. Give it a name, such as *Living room*, and pick the speakers it controls.
3. Set the schedule, quiet mode and night cap. Everything is on one page, and the defaults are a
   good start.
4. Select **Create**.

Add one for each speaker or group of speakers that should share a schedule, for example one for
the living room and another for the bedroom.

To change it later, select **Configure** on the integration. It shows the same page. The link at
the top of the page opens the [online tester](https://lukasscarfe.github.io/adaptive-audio/)
with your saved settings filled in, so you can try changes and see the day's volume before you
save them.

## Settings

**Speakers**

| Setting | What it does | Default |
|---|---|---|
| Speakers | The speakers this controls. | |
| Leave these inputs alone | Inputs whose volume is never changed, separated by commas, for example `Line In`. | none |
| Reset after being stopped for | How long a speaker must be stopped before it starts at the scheduled volume again. | 10 min |
| Follow the schedule again after | With Adjust while playing on: how long a speaker you changed by hand is left alone. 0 waits until it next starts playing. | 0 |
| Never change the volume faster than | With Adjust while playing on: the most the volume moves each minute. | 10%/min |

**Schedule**

| Setting | What it does | Default |
|---|---|---|
| Type | *Morning, evening and night* (three volumes), or *My own times* (a typed list). | Morning, evening and night |
| How the volume changes | *Smoothly* eases in and out, *Steadily* changes at an even rate, *All at once* jumps at the set time. | Smoothly |
| Daytime, evening and night volume | The volume for each part of the day. | 40%, 30%, 15% |
| Use a separate evening volume | Turn off to use only the daytime and night volumes. | on |
| Morning, Evening, Bedtime | When each volume starts: a clock time, or a time from a time helper or sun sensor. **Change over** sets how many minutes the change takes, centred on that time. | 07:30, 19:00, 22:00 |
| My own times | One per line, a time and then a volume, for example `07:00 20` or `sunset-45 30`. | |

**Quiet mode and night cap**

| Setting | What it does | Default |
|---|---|---|
| Quiet volume | The volume while quiet mode is on. Speakers can't go above it. | 10% |
| Also turn on quiet mode with | An entity that turns quiet mode on while it is in the state you pick (usually *on*). | none |
| Night cap | Turns the night cap on. Same as the Night cap switch. | off |
| Also turn on the night cap with | An entity that turns the night cap on while it is on. | none |
| Night cap volume | The most speakers can be turned up to during night cap hours. | 25% |
| Night cap starts, ends | Clock times, or times from a time helper or sun sensor. | 22:00 to 07:00 |

## Entities

Each one you add creates these, shown here for one named *Living room*:

| Entity | What it does |
|---|---|
| `switch.adaptive_audio_living_room_adaptive_audio` | Turns Adaptive Audio on or off for these speakers. |
| `switch.adaptive_audio_living_room_quiet_mode` | Quiet mode. |
| `switch.adaptive_audio_living_room_night_cap` | The night cap. |
| `switch.adaptive_audio_living_room_adjust_while_playing` | Playing speakers follow the schedule. |
| `sensor.adaptive_audio_living_room_scheduled_volume` | The scheduled volume right now. Its attributes show whether quiet mode and the night cap are active, and which speakers you have taken over by hand. |
| `number.adaptive_audio_living_room_quiet_volume` | Change the quiet volume straight away. |
| `number.adaptive_audio_living_room_night_cap_volume` | Change the night cap volume straight away. |
| `button.adaptive_audio_living_room_set_volume_now` | Sets every speaker to the scheduled volume now. |

These work well in automations. For example, turn quiet mode on when a bedroom door closes, or
press *Set volume now* when you get home.

## Card

The card comes with the integration, so you don't need to add a resource. Add it from the card
picker (search for *Adaptive Audio*), or in YAML:

```yaml
type: custom:adaptive-audio-card
entity: sensor.adaptive_audio_living_room_scheduled_volume
title: Living room      # optional
show_history: true      # optional: shows each speaker's real volume today as dots
```

It shows the day's schedule as a chart, the time now, the night cap hours, the quiet volume and
each speaker's volume. Times use Home Assistant's time zone.

## Good to know

- A speaker has to support setting its volume from Home Assistant.
- Some apps, such as Spotify, set their own volume when they start playing. Whichever change
  arrives last wins.

## Troubleshooting

If the volume doesn't change when you expect it to, first check the
`sensor.…_scheduled_volume` attributes: a speaker listed under `taken_over` was changed by hand
and is being left alone, and `schedule_error` explains a schedule it couldn't read.

For more detail, turn on debug logging in `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.adaptive_audio: debug
```

Then [open an issue](https://github.com/LukasScarfe/adaptive-audio/issues) with what happened and
the log from around that time.
