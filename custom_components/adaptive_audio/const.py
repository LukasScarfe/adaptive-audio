"""Constants for Adaptive Audio. All option keys and defaults live here."""

DOMAIN = "adaptive_audio"

CONF_NAME = "name"
CONF_PLAYERS = "players"
CONF_IDLE_GAP = "idle_gap"  # minutes not playing before the next play counts as a fresh start
CONF_SKIP_SOURCES = "skip_sources"  # comma-separated; e.g. "Line In"
CONF_AUTORESET = "autoreset"  # minutes after a hand change to resume adapting; 0 = next fresh start
CONF_MAX_RATE = "max_rate"  # % per minute at most while adjusting during playback

# Schedule
CONF_SCHEDULE_TYPE = "schedule_type"  # "simple" or "custom"
CONF_CURVE = "curve"  # "steps", "linear" or "sigmoid"
CONF_STEEPNESS = "steepness"  # no longer in the UI; fixed at the default
CONF_ALIGN = "align"  # no longer in the UI; ramps are centred
CONF_DAY_VOLUME = "day_volume"
CONF_EVENING_VOLUME = "evening_volume"
CONF_NIGHT_VOLUME = "night_volume"
CONF_USE_EVENING = "use_evening"
ANCHORS = ("wake", "evening", "bedtime")  # option keys, each a dict of the fields below
A_ENTITY = "entity"  # optional time entity (time helper, sun sensor); overrides A_TIME
A_KIND = "kind"  # 0.2 option: "fixed", "sunrise" or "sunset"
A_TIME = "time"
A_OFFSET = "offset"  # 0.2 options, still honoured for sun anchors
A_EARLIEST = "earliest"
A_LATEST = "latest"
A_RAMP = "ramp"
CONF_POINTS = "points"  # custom schedule text
CONF_MODE = "mode"  # 0.1 option: "curve"/"steps" with custom points

# Quiet and cap
CONF_QUIET_VOLUME = "quiet_volume"
CONF_QUIET_ENTITY = "quiet_entity"
CONF_QUIET_STATE = "quiet_state"
CONF_CAP_ENABLED = "cap_enabled"
CONF_CAP_ENTITY = "cap_entity"  # optional: the cap is also on while this entity is on
CONF_CAP_START = "cap_start"
CONF_CAP_START_ENTITY = "cap_start_entity"  # optional time entity, overrides cap_start
CONF_CAP_END = "cap_end"
CONF_CAP_END_ENTITY = "cap_end_entity"
CONF_CAP_VOLUME = "cap_volume"

# Options the number and Night cap entities change live; changing only these doesn't reload.
LIVE_OPTIONS = {CONF_QUIET_VOLUME, CONF_CAP_VOLUME, CONF_CAP_ENABLED}

# Options the UI no longer offers; dropped when an entry is saved.
RETIRED_OPTIONS = ("adapt_step", CONF_STEEPNESS, CONF_ALIGN, CONF_MODE)

SCHEDULE_TYPES = ["simple", "custom"]
CURVES = ["sigmoid", "linear", "steps"]

DEFAULTS = {
    CONF_IDLE_GAP: 10,
    CONF_SKIP_SOURCES: "",
    CONF_AUTORESET: 0,
    CONF_MAX_RATE: 10,
    CONF_SCHEDULE_TYPE: "simple",
    CONF_CURVE: "sigmoid",
    CONF_STEEPNESS: 6,
    CONF_ALIGN: "centre",
    CONF_DAY_VOLUME: 40,
    CONF_EVENING_VOLUME: 30,
    CONF_NIGHT_VOLUME: 15,
    CONF_USE_EVENING: True,
    "wake": {A_TIME: "07:30:00", A_RAMP: 60},
    "evening": {A_TIME: "19:00:00", A_RAMP: 60},
    "bedtime": {A_TIME: "22:00:00", A_RAMP: 90},
    CONF_POINTS: "07:00 20\n10:00 40\n18:00 35\n22:00 15",
    CONF_QUIET_VOLUME: 10,
    CONF_QUIET_STATE: "on",
    CONF_CAP_ENABLED: False,
    CONF_CAP_START: "22:00:00",
    CONF_CAP_END: "07:00:00",
    CONF_CAP_VOLUME: 25,
}

CURVE_SAMPLE_MINUTES = 10  # the sensor's 24 h `curve` attribute: one value per 10 min

TESTER_URL = "https://lukasscarfe.github.io/adaptive-audio/"  # the GitHub Pages tester (site/)

URL_BASE = "/adaptive_audio_static"
CARD_URL = f"{URL_BASE}/adaptive-audio-card.js"
