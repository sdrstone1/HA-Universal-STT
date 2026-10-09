"""Installed HA entity registration, options reload, and resource ownership."""

import asyncio

import pytest
from conftest import entity_ids
from homeassistant import config_entries
from homeassistant.components import stt, tts
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

pytestmark = pytest.mark.asyncio
PROVIDERS = ("openrouter", "openai", "xai", "gemini", "custom")


@pytest.mark.parametrize("service", PROVIDERS)
@pytest.mark.parametrize("mode", ("stt", "tts", "both"))
async def test_setup_options_reload_and_unload_preserve_ids(
    hass, add_entry, provider, service, mode
):
    entry = await add_entry(service, mode)
    original = entity_ids(hass, entry)
    expected = {"stt", "tts"} if mode == "both" else {mode}
    assert set(original) == expected
    registry = er.async_get(hass)
    for domain, entity_id in original.items():
        row = registry.async_get(entity_id)
        assert row.unique_id == entry.entry_id + ("_tts" if domain == "tts" else "")
        assert hass.states.get(entity_id) is not None
    old_runtime = entry.runtime_data
    options = {**entry.data, "api_key": "replacement-local-key"}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data is not old_runtime
    assert old_runtime.closed
    assert not old_runtime.tasks and not old_runtime.responses and not old_runtime.streams
    assert entry.runtime_data.settings.api_key == "replacement-local-key"
    assert entity_ids(hass, entry) == original
    assert not provider.requests  # Loading or editing configuration is never a speech call.
    active_runtime = entry.runtime_data
    session = async_get_clientsession(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED
    assert active_runtime.closed
    assert not active_runtime.tasks and not active_runtime.responses and not active_runtime.streams
    assert not session.closed
    for domain, entity_id in original.items():
        entity = (
            stt.async_get_speech_to_text_entity(hass, entity_id)
            if domain == "stt"
            else tts.get_engine_instance(hass, entity_id)
        )
        assert entity is None
        assert registry.async_get(entity_id) is not None  # HA retains IDs on unload.


async def test_legacy_snapshot_upgrade_and_multiple_entries(hass, add_entry):
    entry = await add_entry()
    legacy = dict(entry.data)
    legacy.pop("mode")
    legacy.pop("tts_model")
    legacy.pop("voice")
    legacy["models_url"] = "http://127.0.0.1/legacy-catalog"
    legacy["language"] = "ko"
    hass.config_entries.async_update_entry(entry, data=legacy)
    await hass.config_entries.async_reload(entry.entry_id)
    ids = entity_ids(hass, entry)
    assert entry.runtime_data.settings.mode == "stt"
    assert entry.runtime_data.settings.stt_models_url == legacy["models_url"]
    assert stt.async_get_speech_to_text_entity(hass, ids["stt"]) is not None
    assert tts.get_engine_instance(hass, ids["tts"]) is None
    # Options are a full snapshot; removed legacy data cannot reappear by merging.
    options = {
        **entry.data,
        "mode": "both",
        "tts_model": "speech-model",
        "voice": "Kore",
        "stt_models_url": "",
        "tts_models_url": "",
    }
    options.pop("models_url")
    options.pop("language")
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    assert entity_ids(hass, entry) == ids
    assert entry.runtime_data.settings.stt_models_url == ""
    assert dict(entry.data) == legacy
    second = await add_entry("openai", "tts")
    assert entity_ids(hass, second)["tts"] != ids["tts"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert second.state is config_entries.ConfigEntryState.LOADED
    assert tts.get_engine_instance(hass, entity_ids(hass, second)["tts"]) is not None


async def test_actual_config_and_options_flow_complete_snapshots(hass, provider):
    """Exercise HA flow managers/selectors and their real entry creation/update hooks."""
    flow = await hass.config_entries.flow.async_init("universal_stt", context={"source": "user"})
    assert flow["type"] == "form" and flow["step_id"] == "user"
    connection = {
        "provider": "custom",
        "mode": "both",
        "base_url": provider.base,
        "api_key": "flow-local-key",
        "discover": False,
        "tts_streaming": True,
    }
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"provider": connection["provider"], "mode": connection["mode"]}
    )
    assert flow["step_id"] == "connection"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {key: value for key, value in connection.items() if key not in {"provider", "mode"}},
    )
    assert flow["step_id"] == "model"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"model": "stt-model"})
    assert flow["step_id"] == "tts"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"tts_model": "tts-model"}
    )
    assert flow["step_id"] == "voice"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"voice": "Kore"})
    assert flow["type"] == "create_entry"
    entry = flow["result"]
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    original_ids = entity_ids(hass, entry)
    runtime = entry.runtime_data
    assert runtime.settings.tts_streaming is True
    original_data = dict(entry.data)
    # A partly completed options flow must leave storage and runtime untouched.
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["step_id"] == "init"
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"provider": "custom", "mode": "stt"}
    )
    assert options["step_id"] == "connection"
    options = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {
            key: value
            for key, value in {**connection, "api_key": ""}.items()
            if key not in {"provider", "mode", "tts_streaming"}
        },
    )
    assert options["step_id"] == "model"
    assert dict(entry.data) == original_data and not entry.options
    assert entry.runtime_data is runtime
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"model": "new-stt-model"}
    )
    assert options["type"] == "create_entry"
    await hass.async_block_till_done()
    assert runtime.closed and entry.runtime_data is not runtime
    assert entry.runtime_data.settings.api_key == "flow-local-key"  # Blank preserves same origin.
    assert entry.runtime_data.settings.mode == "stt"
    assert entry.runtime_data.settings.model == "new-stt-model"
    assert "tts_model" not in entry.options and "tts_streaming" not in entry.options
    assert dict(entry.data) == original_data
    assert entity_ids(hass, entry) == original_ids  # Disabled TTS keeps its registered ID.
    assert tts.get_engine_instance(hass, original_ids["tts"]) is None
    assert stt.async_get_speech_to_text_entity(hass, original_ids["stt"]) is not None
    assert not provider.requests


@pytest.mark.parametrize("streaming", (False, True))
async def test_unload_closes_provider_consumed_by_ha_cache(hass, add_entry, provider, streaming):
    provider.stall = True
    entry = await add_entry("gemini" if streaming else "custom", "tts", tts_streaming=streaming)
    runtime = entry.runtime_data
    entity_id = entity_ids(hass, entry)["tts"]
    session = async_get_clientsession(hass)
    # Use actual HA cache-loader ownership, rather than a manually pulled entity iterator.
    result = tts.async_create_stream(
        hass,
        entity_id,
        language="ko",
        options={"preferred_format": "wav" if streaming else "mp3"},
    )
    result.async_set_message("unload test")
    await asyncio.wait_for(provider.entered.wait(), 2)
    if not streaming:
        # Complete Gemini JSON has no stalled read; the custom MP3 path does.
        assert runtime.tasks
    async with asyncio.timeout(2):
        while not runtime.responses:
            await asyncio.sleep(0)
    assert not provider.release.is_set()
    started = asyncio.get_running_loop().time()
    assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), 5.5)
    assert asyncio.get_running_loop().time() - started < 5.5
    assert runtime.closed
    assert not runtime.tasks and not runtime.responses and not runtime.streams
    assert runtime.shutdown_error is None
    assert not session.closed
    assert tts.get_engine_instance(hass, entity_id) is None
    # Do not cancel HA background tasks or release the stalled server before these assertions.
    async with asyncio.timeout(2):
        while not provider.connections[0].is_closing():
            await asyncio.sleep(0)
    provider.release.set()
