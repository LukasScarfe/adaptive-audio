"""Constants for Adaptive Volume. All option keys and defaults live here."""

DOMAIN = "adaptive_volume"

CONF_NAME = "name"
CONF_PLAYERS = "players"
CONF_MODE = "mode"
CONF_POINTS = "points"
CONF_IDLE_GAP = "idle_gap"  # minutes not playing before the next play counts as a fresh start
CONF_SKIP_SOURCES = "skip_sources"  # comma-separated; e.g. "Line In"
CONF_QUIET_VOLUME = "quiet_volume"
CONF_QUIET_ENTITY = "quiet_entity"
CONF_QUIET_STATE = "quiet_state"
CONF_CAP_ENABLED = "cap_enabled"
CONF_CAP_START = "cap_start"
CONF_CAP_END = "cap_end"
CONF_CAP_VOLUME = "cap_volume"

# Options the number entities change live; changing only these doesn't reload the entry.
LIVE_OPTIONS = {CONF_QUIET_VOLUME, CONF_CAP_VOLUME}

DEFAULTS = {
    CONF_MODE: "curve",
    CONF_POINTS: "07:00 20\n10:00 40\n18:00 35\n22:00 15",
    CONF_IDLE_GAP: 10,
    CONF_SKIP_SOURCES: "",
    CONF_QUIET_VOLUME: 10,
    CONF_QUIET_STATE: "on",
    CONF_CAP_ENABLED: False,
    CONF_CAP_START: "22:00:00",
    CONF_CAP_END: "07:00:00",
    CONF_CAP_VOLUME: 25,
}

MODES = ["curve", "steps"]
