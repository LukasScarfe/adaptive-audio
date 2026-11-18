"""Constants for Adaptive Volume. All option keys and defaults live here."""

DOMAIN = "adaptive_volume"

CONF_NAME = "name"
CONF_PLAYERS = "players"
CONF_IDLE_GAP = "idle_gap"  # minutes not playing before the next play counts as a fresh start
CONF_SKIP_SOURCES = "skip_sources"  # comma-separated; e.g. "Line In"
CONF_ADAPT_STEP = "adapt_step"  # max % per minute while adapting during playback
CONF_AUTORESET = "autoreset"  # minutes after a hand change to resume adapting; 0 = next fresh start

# Schedule
CONF_SCHEDULE_TYPE = "schedule_type"  # "simple" or "custom"
CONF_CURVE = "curve"  # "steps", "linear" or "sigmoid"
CONF_STEEPNESS = "steepness"
CONF_ALIGN = "align"  # "centre" or "end"
CONF_DAY_VOLUME = "day_volume"
CONF_EVENING_VOLUME = "evening_volume"
CONF_NIGHT_VOLUME = "night_volume"
CONF_USE_EVENING = "use_evening"
ANCHORS = ("wake", "evening", "bedtime")  # option keys, each a dict of the fields below
A_KIND = "kind"  # "fixed", "sunrise" or "sunset"
A_TIME = "time"
A_OFFSET = "offset"
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
CONF_CAP_START = "cap_start"
CONF_CAP_END = "cap_end"
CONF_CAP_VOLUME = "cap_volume"

# Options the number entities change live; changing only these doesn't reload the entry.
LIVE_OPTIONS = {CONF_QUIET_VOLUME, CONF_CAP_VOLUME}

SCHEDULE_TYPES = ["simple", "custom"]
CURVES = ["sigmoid", "linear", "steps"]
ALIGNS = ["centre", "end"]
ANCHOR_KINDS = ["fixed", "sunrise", "sunset"]

DEFAULTS = {
    CONF_IDLE_GAP: 10,
    CONF_SKIP_SOURCES: "",
    CONF_ADAPT_STEP: 1,
    CONF_AUTORESET: 0,
    CONF_SCHEDULE_TYPE: "simple",
    CONF_CURVE: "sigmoid",
    CONF_STEEPNESS: 6,
    CONF_ALIGN: "centre",
    CONF_DAY_VOLUME: 40,
    CONF_EVENING_VOLUME: 30,
    CONF_NIGHT_VOLUME: 15,
    CONF_USE_EVENING: True,
    "wake": {A_KIND: "fixed", A_TIME: "07:30:00", A_OFFSET: 0, A_RAMP: 60},
    "evening": {A_KIND: "fixed", A_TIME: "19:00:00", A_OFFSET: 0, A_RAMP: 60},
    "bedtime": {A_KIND: "fixed", A_TIME: "22:00:00", A_OFFSET: 0, A_RAMP: 90},
    CONF_POINTS: "07:00 20\n10:00 40\n18:00 35\n22:00 15",
    CONF_QUIET_VOLUME: 10,
    CONF_QUIET_STATE: "on",
    CONF_CAP_ENABLED: False,
    CONF_CAP_START: "22:00:00",
    CONF_CAP_END: "07:00:00",
    CONF_CAP_VOLUME: 25,
}

CURVE_SAMPLE_MINUTES = 10  # the sensor's 24 h `curve` attribute: one value per 10 min

URL_BASE = "/adaptive_volume_static"
CARD_URL = f"{URL_BASE}/adaptive-volume-card.js"
PREVIEW_URL = "/api/adaptive_volume/preview/{key}.svg"
