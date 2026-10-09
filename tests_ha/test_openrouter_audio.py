"""Actual HA/FFmpeg contracts for response-first OpenRouter containers and PCM."""

import asyncio
import io
import struct
import wave
from collections.abc import AsyncGenerator

import pytest
from conftest import entity_ids
from homeassistant.components import tts
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from test_audio import chunks, decode

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("streaming", (False, True))
@pytest.mark.parametrize("format", ("mp3", "wav", "pcm"))
async def test_response_format_reaches_real_ha_and_ffmpeg(
    hass, add_entry, provider, audio, streaming, format
):
    provider.speech_format = format
    provider.speech_mime = {
        "mp3": "application/octet-stream",
        "wav": "audio/wav",
        "pcm": "audio/pcm; rate=24000; channels=1",
    }[format]
    provider.speech_first_size = 257  # A split PCM sample must not lose bytes.
    entry = await add_entry(
        "openrouter", "tts", tts_streaming=streaming, tts_model="minimax/speech-2.8-hd"
    )
    entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
    async with asyncio.timeout(5):
        response = await entity.async_stream_tts_audio(
            tts.TTSAudioRequest("ko", {}, chunks("format contract"))
        )
        assert response.extension == ("mp3" if format == "mp3" else "wav")
        assert isinstance(response.data_gen, AsyncGenerator)
        raw = b"".join([part async for part in response.data_gen])
    if format in {"mp3", "wav"}:
        assert raw == audio[format]
    elif streaming:
        assert struct.unpack_from("<I", raw, 4)[0] == 0xFFFFFFFF
        assert struct.unpack_from("<I", raw, 40)[0] == 0xFFFFFFFF
        assert raw[44:] == audio["pcm"]
    else:
        with wave.open(io.BytesIO(raw)) as wav:
            assert wav.getnframes() == 2400
            assert wav.readframes(2400) == audio["pcm"]
    # Run the full HA cache/conversion path too, asking HA to decode to WAV.
    result = tts.async_create_stream(
        hass, entity_ids(hass, entry)["tts"], language="ko", options={"preferred_format": "wav"}
    )
    result.async_set_message("real decoder contract")
    async with asyncio.timeout(10):
        data = b"".join([part async for part in result.async_stream_result()])
        decoded = await decode(audio, data)
    assert decoded
    if format != "mp3":
        assert decoded == audio["pcm"]
    assert all(body["response_format"] == "mp3" for _, body, _ in provider.requests)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not entry.runtime_data.tasks
    assert not entry.runtime_data.responses and not entry.runtime_data.streams


@pytest.mark.parametrize("cancel", (False, True))
async def test_pcm_is_progressive_and_unconsumed_or_cancelled_output_is_released(
    hass, add_entry, provider, cancel
):
    provider.speech_format = "pcm"
    provider.speech_mime = "audio/pcm; rate=24000; channels=1"
    provider.speech_first_size = 2401
    provider.stall = True
    entry = await add_entry("openrouter", "tts", tts_streaming=True)
    entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
    async with asyncio.timeout(3):
        response = await entity.async_stream_tts_audio(
            tts.TTSAudioRequest("ko", {}, chunks("progressive contract"))
        )
        assert response.extension == "wav"
        assert len(provider.requests) == 1  # OpenRouter prepares before HA receives extension.
        assert entry.runtime_data.responses and entry.runtime_data.streams
        if cancel:
            assert (await anext(response.data_gen)).startswith(b"RIFF")
            data = await anext(response.data_gen)
            assert data
            # Prefix and pending channel frames may require more than one pull.
            while len(data) < 2400:
                data += await anext(response.data_gen)
            assert data == provider.audio["pcm"][:2400]
            pending = asyncio.create_task(anext(response.data_gen))
            await asyncio.sleep(0.01)
            assert not pending.done()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            # Closing before a first pull must close the already acquired response.
            await response.data_gen.aclose()
    assert not provider.release.is_set()
    assert not entry.runtime_data.tasks
    assert not entry.runtime_data.responses and not entry.runtime_data.streams
    assert not async_get_clientsession(hass).closed
    provider.release.set()


async def test_real_ha_rejects_pcm_missing_metadata_without_model_fallback(
    hass, add_entry, provider
):
    provider.speech_format = "pcm"
    provider.speech_mime = "audio/pcm"
    entry = await add_entry("openrouter", "tts", tts_streaming=True, tts_model="google/gemini-tts")
    entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
    async with asyncio.timeout(3):
        with pytest.raises(HomeAssistantError, match="Unable to generate TTS audio"):
            await entity.async_stream_tts_audio(
                tts.TTSAudioRequest("ko", {}, chunks("missing metadata"))
            )
    assert len(provider.requests) == 1
    assert provider.requests[0][1]["response_format"] == "pcm"
    assert not entry.runtime_data.tasks
    assert not entry.runtime_data.responses and not entry.runtime_data.streams


async def test_reload_reads_updated_request_policy(
    hass, add_entry, provider, monkeypatch, tmp_path
):
    import json

    import custom_components.universal_stt as entrypoint

    load_policy = entrypoint.load_audio_formats
    path = tmp_path / "audio-policy.json"
    policy = {"version": 1, "defaults": {"request_format": "pcm"}, "models": {}}
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(entrypoint, "load_audio_formats", lambda: load_policy(path))
    entry = await add_entry("openrouter", "tts")
    original = entry.runtime_data
    entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
    async with asyncio.timeout(5):
        assert (await entity.async_get_tts_audio("before reload", "ko", {}))[0] == "mp3"
        assert provider.requests[-1][1]["response_format"] == "pcm"
        policy["defaults"]["request_format"] = "mp3"
        path.write_text(json.dumps(policy), encoding="utf-8")
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
        assert (await entity.async_get_tts_audio("after reload", "ko", {}))[0] == "mp3"
    assert provider.requests[-1][1]["response_format"] == "mp3"
    assert original.closed
    assert entry.runtime_data is not original
    assert not original.tasks and not original.responses and not original.streams
