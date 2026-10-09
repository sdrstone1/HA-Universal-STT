"""Real HA STT/TTS calls, bounded input, HTTP streaming, and FFmpeg decoding."""

import asyncio
import base64
import io
import wave

import pytest
from conftest import entity_ids
from homeassistant.components import stt, tts
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.universal_stt import stt as stt_entity
from custom_components.universal_stt import tts as tts_entity

pytestmark = pytest.mark.asyncio
PROVIDERS = ("openrouter", "openai", "xai", "gemini", "custom")


async def chunks(*values):
    for value in values:
        yield value


async def decode(audio, data):
    process = await asyncio.create_subprocess_exec(
        audio["ffmpeg"],
        "-v",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-ar",
        "24000",
        "-ac",
        "1",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pcm, error = await asyncio.wait_for(process.communicate(data), 10)
    assert process.returncode == 0, error.decode()
    return pcm


def metadata(**changes):
    return stt.SpeechMetadata(
        **{
            "language": "ko",
            "format": stt.AudioFormats.WAV,
            "codec": stt.AudioCodecs.PCM,
            "bit_rate": stt.AudioBitRates.BITRATE_16,
            "sample_rate": stt.AudioSampleRates.SAMPLERATE_16000,
            "channel": stt.AudioChannels.CHANNEL_MONO,
            **changes,
        }
    )


@pytest.mark.parametrize("service", PROVIDERS)
async def test_stt_actual_entity_uploads_valid_wav(hass, add_entry, provider, service):
    entry = await add_entry(service, "stt")
    entity = stt.async_get_speech_to_text_entity(hass, entity_ids(hass, entry)["stt"])
    pcm = b"\x00\x01" * 1600
    result = await entity.async_process_audio_stream(metadata(), chunks(pcm[:5], pcm[5:]))
    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "runtime transcript"
    assert len(provider.requests) == 1
    path, body, headers = provider.requests[0]
    if service == "gemini":
        assert path == "/interactions"
        assert body["store"] is False
        assert body["model"] == "transcription-model"
        wav_data = base64.b64decode(body["input"][0]["data"])
        assert headers["x-goog-api-key"] == "local-test-key"
    else:
        assert path == ("/stt" if service == "xai" else "/audio/transcriptions")
        assert body["language"] == "ko"
        assert body["model"] == "transcription-model"
        wav_data = body["file"]
        assert headers["Authorization"] == "Bearer local-test-key"
    with wave.open(io.BytesIO(wav_data)) as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        assert wav.readframes(wav.getnframes()) == pcm
    assert not entry.runtime_data.responses and not entry.runtime_data.tasks


async def test_stt_invalid_input_fails_before_provider(hass, add_entry, provider):
    entry = await add_entry(mode="stt")
    entity = stt.async_get_speech_to_text_entity(hass, entity_ids(hass, entry)["stt"])
    for meta, parts in (
        (metadata(sample_rate=stt.AudioSampleRates.SAMPLERATE_48000), [b"\0\0"]),
        (metadata(), []),
        (metadata(), [b"\0"]),
        (metadata(), [b"\0" * (16000 * 2 * 120 + 2)]),
    ):
        result = await entity.async_process_audio_stream(meta, chunks(*parts))
        assert result.result is stt.SpeechResultState.ERROR
    assert not provider.requests


@pytest.mark.parametrize("service", PROVIDERS)
@pytest.mark.parametrize("streaming", (False, True))
async def test_tts_real_ha_audio_pipeline_and_decoder(
    hass, add_entry, provider, audio, service, streaming
):
    entry = await add_entry(service, "tts", tts_streaming=streaming)
    entity_id = entity_ids(hass, entry)["tts"]
    entity = tts.get_engine_instance(hass, entity_id)
    assert entity.async_supports_streaming_input() is True
    result = tts.async_create_stream(
        hass,
        entity_id,
        language="ko",
        options={"preferred_format": "wav" if service == "gemini" else "mp3"},
    )
    result.async_set_message_stream(chunks("안녕", "하세요"))
    data = b"".join([part async for part in result.async_stream_result()])
    decoded = await decode(audio, data)
    if service == "gemini":
        assert decoded == audio["pcm"]
        assert len(decoded) / (24000 * 2) == 0.1
    else:
        assert decoded  # Real MP3 decoder acceptance, including HA's stream path.
    assert len(provider.requests) == 1
    path, body, _ = provider.requests[0]
    if service == "gemini":
        assert path == "/interactions"
        assert bool(body.get("stream")) is streaming
        assert body["store"] is False
    elif service == "xai":
        assert path == "/tts"
        assert body["text"] == "안녕하세요"
        assert body["language"] == "ko"
        assert "model" not in body
    else:
        assert path == "/audio/speech"
        assert body["input"] == "안녕하세요"
        assert body["model"] == "speech-model"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not entry.runtime_data.tasks
    assert not entry.runtime_data.responses and not entry.runtime_data.streams


@pytest.mark.parametrize("streaming", (False, True))
async def test_output_setting_cannot_bypass_input_limits(hass, add_entry, provider, streaming):
    entry = await add_entry(mode="tts", tts_streaming=streaming)
    entity_id = entity_ids(hass, entry)["tts"]
    closed = []

    async def oversized():
        try:
            yield "가" * 21846  # Above 64 KiB in UTF-8, below 64 Ki characters.
            pytest.fail("HA must stop consuming after the integration rejects overflow")
        finally:
            closed.append(True)

    result = tts.async_create_stream(hass, entity_id, language="ko")
    result.async_set_message_stream(oversized())
    with pytest.raises(HomeAssistantError, match="Unable to generate TTS audio"):
        _ = [part async for part in result.async_stream_result()]
    assert closed == [True]
    entity = tts.get_engine_instance(hass, entity_id)
    assert await entity.async_get_tts_audio(" ", "ko", None) == (None, None)
    assert await entity.async_get_tts_audio("가" * 21846, "ko", None) == (None, None)
    assert not provider.requests


@pytest.mark.parametrize("streaming", (False, True))
async def test_input_collection_timeout_reaches_actual_ha(
    hass, add_entry, provider, monkeypatch, streaming
):
    monkeypatch.setattr(tts_entity, "AUDIO_COLLECTION_TIMEOUT", 0.01)
    entry = await add_entry(mode="tts", tts_streaming=streaming)
    closed = []

    async def stalled_input():
        try:
            yield "input test"
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    result = tts.async_create_stream(hass, entity_ids(hass, entry)["tts"], language="ko")
    result.async_set_message_stream(stalled_input())
    with pytest.raises(HomeAssistantError, match="Unable to generate TTS audio"):
        async with asyncio.timeout(2):
            _ = [part async for part in result.async_stream_result()]
    assert closed == [True]
    assert not provider.requests


async def test_stt_timeout_and_provider_error_are_final(hass, add_entry, provider, monkeypatch):
    monkeypatch.setattr(stt_entity, "AUDIO_COLLECTION_TIMEOUT", 0.01)
    entry = await add_entry(mode="stt")
    entity = stt.async_get_speech_to_text_entity(hass, entity_ids(hass, entry)["stt"])

    async def stalled_input():
        yield b"\0\0"
        await asyncio.Event().wait()

    async with asyncio.timeout(2):
        result = await entity.async_process_audio_stream(metadata(), stalled_input())
    assert result.result is stt.SpeechResultState.ERROR
    assert not provider.requests
    provider.status = 500
    result = await entity.async_process_audio_stream(metadata(), chunks(b"\0\0"))
    assert result.result is stt.SpeechResultState.ERROR
    assert len(provider.requests) == 1


@pytest.mark.parametrize("cancel", (False, True))
async def test_direct_output_close_and_cancel_release_provider(hass, add_entry, provider, cancel):
    provider.stall = True
    entry = await add_entry("gemini", "tts", tts_streaming=True)
    entity = tts.get_engine_instance(hass, entity_ids(hass, entry)["tts"])
    response = await entity.async_stream_tts_audio(
        tts.TTSAudioRequest("ko", {}, chunks("consumer cleanup"))
    )
    assert not provider.requests  # Output acquisition is lazy.
    assert (await anext(response.data_gen)).startswith(b"RIFF")
    assert entry.runtime_data.responses
    if cancel:
        pending = asyncio.create_task(anext(response.data_gen))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        await response.data_gen.aclose()
    assert not entry.runtime_data.tasks and not entry.runtime_data.responses
    assert not entry.runtime_data.streams
    assert not async_get_clientsession(hass).closed
    assert not provider.release.is_set()
    provider.release.set()


async def test_stream_delivers_before_completion_and_unload_cleans_up(hass, add_entry, provider):
    provider.stall = True
    entry = await add_entry("gemini", "tts", tts_streaming=True)
    entity_id = entity_ids(hass, entry)["tts"]
    result = tts.async_create_stream(
        hass, entity_id, language="ko", options={"preferred_format": "wav"}
    )
    result.async_set_message("stream test")
    output = result.async_stream_result()
    first = await asyncio.wait_for(anext(output), 2)
    assert first.startswith(b"RIFF")
    assert not provider.release.is_set()
    assert entry.runtime_data.responses
    # Outer consumption can stop while HA's cache loader continues to own the provider.
    await output.aclose()
    runtime = entry.runtime_data
    assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), 5.5)
    assert not runtime.tasks and not runtime.responses and not runtime.streams
    provider.release.set()


async def test_truncated_gemini_stream_fails_without_retry(hass, add_entry, provider):
    provider.truncate = True
    entry = await add_entry("gemini", "tts", tts_streaming=True)
    result = tts.async_create_stream(
        hass, entity_ids(hass, entry)["tts"], language="ko", options={"preferred_format": "wav"}
    )
    result.async_set_message("truncation test")
    with pytest.raises(HomeAssistantError, match="Unable to stream TTS audio"):
        _ = [part async for part in result.async_stream_result()]
    assert len(provider.requests) == 1
    assert not entry.runtime_data.responses and not entry.runtime_data.streams
