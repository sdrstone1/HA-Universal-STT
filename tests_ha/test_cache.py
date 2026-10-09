"""Actual HA cache lookup cannot replay a previous connection's audio."""

import pytest
from conftest import entity_ids
from homeassistant.components import tts
from homeassistant.exceptions import HomeAssistantError

pytestmark = pytest.mark.asyncio


async def speak(hass, entity_id, options=None):
    result = tts.async_create_stream(
        hass, entity_id, language="ko", options={"preferred_format": "wav", **(options or {})}
    )
    result.async_set_message("same message")
    return b"".join([chunk async for chunk in result.async_stream_result()])


@pytest.mark.parametrize("change", ("key", "connection"))
async def test_cache_hit_reload_miss_and_old_options_rejected(hass, add_entry, provider, change):
    entry = await add_entry("gemini", "tts")
    entity_id = entity_ids(hass, entry)["tts"]
    entity = tts.get_engine_instance(hass, entity_id)
    old_options = dict(entity.default_options)
    first = await speak(hass, entity_id)
    assert first == provider.audio["wav"]
    assert await speak(hass, entity_id) == first
    assert len(provider.requests) == 1
    # Keep the WAV container valid but change PCM samples at the same endpoint.
    new_audio = first[:-4] + b"\x01\x00\x02\x00"
    assert new_audio != first
    provider.audio["wav"] = new_audio
    old_runtime = entry.runtime_data
    options = {**entry.data, "api_key": "new-local-key"}
    if change == "connection":
        # Same local server, distinct connection base and inference path.
        options["base_url"] = provider.base + "/changed"
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    assert entity_ids(hass, entry)["tts"] == entity_id
    replacement = tts.get_engine_instance(hass, entity_id)
    assert replacement is not entity
    assert replacement.default_options["model"] == old_options["model"]
    assert replacement.default_options["voice"] == old_options["voice"]
    assert replacement.default_options["connection_revision"] != old_options["connection_revision"]
    assert old_runtime.closed
    assert await speak(hass, entity_id) == new_audio
    assert len(provider.requests) == 2
    path, _, headers = provider.requests[-1]
    assert headers["x-goog-api-key"] == "new-local-key"
    assert path == ("/changed/interactions" if change == "connection" else "/interactions")
    manager = hass.data[tts.DATA_TTS_MANAGER]
    assert len(manager.mem_cache) == 2  # Both namespaces exist; no deliberate cache clear.
    with pytest.raises(HomeAssistantError, match="Invalid options"):
        await speak(hass, entity_id, old_options)
    with pytest.raises(HomeAssistantError, match="Unable to generate TTS audio"):
        await speak(hass, entity_id, {"connection_revision": old_options["connection_revision"]})
    assert len(provider.requests) == 2  # Neither stale request is sent upstream.
    assert await speak(hass, entity_id) == new_audio
    assert len(provider.requests) == 2
