"""Serves the preview image for Configure. The flow stores the pending options under a
random key and embeds a signed URL to /api/adaptive_volume/preview/<key>.svg in its
description, so the dialog shows the curve before you save."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS
from homeassistant.util import dt as dt_util

from . import curve, plot, schedule
from .const import (
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_START,
    CONF_CAP_VOLUME,
    CONF_QUIET_VOLUME,
    CURVE_SAMPLE_MINUTES,
    DOMAIN,
    PREVIEW_URL,
)
from .controller import sun_minutes

_STORE = f"{DOMAIN}_previews"


def render_options(hass: HomeAssistant, options: dict[str, Any]) -> str:
    now = dt_util.now()
    try:
        rise, set_ = sun_minutes(hass, now.date()) if curve.uses_sun(options) else (None, None)
        fn, marks = curve.builder(options, rise, set_)
        samples, error = curve.samples(fn), None
    except schedule.ScheduleError as err:
        samples, marks, error = [], [], str(err)
    cap_window = None
    if curve.opt(options, CONF_CAP_ENABLED):
        cap_window = [
            schedule.parse_clock(curve.opt(options, CONF_CAP_START)),
            schedule.parse_clock(curve.opt(options, CONF_CAP_END)),
        ]
    return plot.render(
        samples,
        CURVE_SAMPLE_MINUTES,
        marks,
        cap_window,
        float(curve.opt(options, CONF_CAP_VOLUME)) if cap_window else None,
        float(curve.opt(options, CONF_QUIET_VOLUME)),
        now.hour * 60 + now.minute,
        error,
    )


def preview_url(hass: HomeAssistant, key: str, options: dict[str, Any]) -> str:
    """Store the options and return a signed image URL for them (valid 10 min)."""
    hass.data.setdefault(_STORE, {})[key] = dict(options)
    # A changing query defeats the browser's image cache between previews.
    path = PREVIEW_URL.format(key=key) + f"?v={secrets.token_hex(3)}"
    return async_sign_path(hass, path, timedelta(minutes=10))


def forget(hass: HomeAssistant, key: str) -> None:
    hass.data.get(_STORE, {}).pop(key, None)


class PreviewView(HomeAssistantView):
    url = PREVIEW_URL
    name = "api:adaptive_volume:preview"
    requires_auth = True

    async def get(self, request: web.Request, key: str) -> web.Response:
        hass = request.app[KEY_HASS]
        options = hass.data.get(_STORE, {}).get(key)
        if options is None:
            return web.Response(status=404)
        return web.Response(
            body=render_options(hass, options),
            content_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )
