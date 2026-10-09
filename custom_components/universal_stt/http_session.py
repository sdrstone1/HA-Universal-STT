"""A cookie-free voice session sharing HA's managed connector and shutdown."""

import aiohttp
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN

SESSION_KEY = f"{DOMAIN}_http_session"


@callback
def async_get_voice_session(hass):
    """Reuse one session across flows/entries; only HA shutdown detaches it."""
    session = hass.data.get(SESSION_KEY)
    if session is None or session.closed:
        # HA's automatic cleanup also attaches to the current entry's unload.
        # A shared integration session must instead live until HA closes.
        session = async_create_clientsession(
            hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
        )
        hass.data[SESSION_KEY] = session

        @callback
        def close_session(_event):
            session.detach()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, close_session)
    return session
