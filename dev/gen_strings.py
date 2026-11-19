"""Write strings.json and translations/en.json (identical) from one source.

    python3 dev/gen_strings.py
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "adaptive_volume"
BACK = "Back"

TIME_ENTITY_HELP = (
    "Optional: follow a time entity instead, e.g. a time helper or Sun next rising / setting. "
    "The time below is used when this is empty or has no time."
)


def anchor(name, description):
    return {
        "name": name,
        "description": description,
        "data": {"entity": "Anchored to", "time": "Time", "ramp": "Ramp length"},
        "data_description": {
            "entity": TIME_ENTITY_HELP,
            "time": "The clock time, when not anchored to an entity.",
            "ramp": "How long the change takes, centred on the time. 0 = instant.",
        },
    }


def steps(create_label):
    return {
        "init": {
            "title": "Adaptive Volume",
            "description": "Set each part, then {save}. Nothing is kept until then.".replace(
                "{save}", create_label
            ),
            "menu_options": {
                "speakers": "Speakers and behaviour",
                "schedule": "Schedule",
                "quiet_cap": "Quiet and night cap",
                "save": create_label,
            },
        },
        "speakers": {
            "title": "Speakers and behaviour",
            "submit": BACK,
            "data": {
                "name": "Name",
                "players": "Speakers",
                "skip_sources": "Skip sources",
                "idle_gap": "Idle gap",
                "autoreset": "Hand-change reset",
            },
            "data_description": {
                "name": "e.g. Living room",
                "players": "Media players this instance looks after.",
                "skip_sources": "Comma-separated sources where Adaptive Volume never touches the volume, e.g. Line In.",
                "idle_gap": "Minutes a speaker must be not playing before its next play counts as a fresh start and gets the schedule's volume.",
                "autoreset": "With Adapt while playing on, a hand change stops adapting that speaker. 0 = until its next fresh start; otherwise resume after this many minutes.",
            },
        },
        "schedule": {
            "title": "Schedule",
            "description": "{image}\n\nToday's curve. Blue shading = ramps, red = cap hours, dotted = quiet volume. {sun}",
            "menu_options": {
                "type": "Schedule type and curve",
                "levels": "Times and levels",
                "points": "Points",
                "back": BACK,
            },
        },
        "type": {
            "title": "Schedule type and curve",
            "submit": BACK,
            "data": {"schedule_type": "Schedule type", "curve": "Curve"},
            "data_description": {
                "schedule_type": "Simple: Day, Evening and Night levels at Wake, Evening and Bedtime, like Adaptive Lighting. Custom: your own list of points.",
                "curve": "Sigmoid: an S-curve that eases in and out. Linear: a straight ramp. Steps: an instant change.",
            },
        },
        "levels": {
            "title": "Times and levels",
            "description": "{error}",
            "submit": BACK,
            "data": {
                "day_volume": "Day volume",
                "use_evening": "Use an evening level",
                "evening_volume": "Evening volume",
                "night_volume": "Night volume",
            },
            "data_description": {
                "day_volume": "From Wake.",
                "use_evening": "Off = two levels (Day and Night), like Adaptive Lighting.",
                "evening_volume": "From Evening, if used.",
                "night_volume": "From Bedtime.",
            },
            "sections": {
                "wake": anchor("Wake", "Night → Day."),
                "evening": anchor("Evening", "Day → Evening (if used)."),
                "bedtime": anchor("Bedtime", "Evening (or Day) → Night."),
            },
        },
        "points": {
            "title": "Points",
            "description": "{error}",
            "submit": BACK,
            "data": {"points": "Points"},
            "data_description": {
                "points": "One per line: a time and a volume. A time is a clock time or sunrise/sunset with an offset in minutes, e.g.\n07:00 20\nsunrise+30 25\nsunset-45 30\n22:00 15"
            },
        },
        "quiet_cap": {
            "title": "Quiet and night cap",
            "submit": BACK,
            "data": {
                "quiet_volume": "Quiet volume",
                "quiet_entity": "Quiet when this entity…",
                "quiet_state": "…is in this state",
                "cap_enabled": "Night cap",
                "cap_entity": "Night cap also on while this is on",
                "cap_volume": "Cap volume",
                "cap_start": "Cap starts",
                "cap_start_entity": "Cap starts at this entity's time",
                "cap_end": "Cap ends",
                "cap_end_entity": "Cap ends at this entity's time",
            },
            "data_description": {
                "quiet_volume": "Volume while quiet is on (the Quiet switch, or the linked entity). Also the maximum while quiet.",
                "quiet_entity": "Optional: quiet turns on by itself while this entity is in the state below.",
                "quiet_state": "The state that means quiet (default on).",
                "cap_enabled": "The same as the Night cap switch. During cap hours, turning a speaker above the cap volume pulls it straight back.",
                "cap_entity": "Optional: a boolean (e.g. an input_boolean) that turns the night cap on while it is on, even with the switch off.",
                "cap_volume": "The maximum during cap hours. Fresh starts never go above it either.",
                "cap_start_entity": "Optional: a time helper or sensor; the time above is used when this is empty.",
                "cap_end_entity": "Optional: a time helper or sensor; the time above is used when this is empty.",
            },
        },
    }


config_steps = steps("Create")
options_steps = steps("Save")
del options_steps["speakers"]["data"]["name"], options_steps["speakers"]["data_description"]["name"]

errors = {
    "bad_schedule": "This schedule can't be used: {error}",
    "need_speakers": "Give this instance a name and pick at least one speaker first.",
}

strings = {
    "title": "Adaptive Volume",
    "config": {"step": config_steps, "error": errors},
    "options": {"step": options_steps, "error": errors},
    "selector": {
        "schedule_type": {"options": {"simple": "Simple (Wake / Evening / Bedtime)", "custom": "Custom points"}},
        "curve": {"options": {"sigmoid": "Sigmoid (S-curve)", "linear": "Linear", "steps": "Steps"}},
    },
    "entity": {
        "switch": {
            "enabled": {"name": "Adaptive volume"},
            "quiet": {"name": "Quiet"},
            "adapt": {"name": "Adapt while playing"},
            "night_cap": {"name": "Night cap"},
        },
        "sensor": {"target": {"name": "Target volume"}},
        "number": {"quiet_volume": {"name": "Quiet volume"}, "cap_volume": {"name": "Cap volume"}},
        "button": {"apply": {"name": "Apply volume now"}},
    },
}

text = json.dumps(strings, indent=2, ensure_ascii=False) + "\n"
(ROOT / "strings.json").write_text(text)
(ROOT / "translations" / "en.json").write_text(text)
print("wrote strings.json and translations/en.json")
