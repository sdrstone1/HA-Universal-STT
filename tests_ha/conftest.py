"""Real HA fixtures; run separately from the unit suite's HA substitutes."""

import asyncio
import base64
import io
import json
import shutil
import subprocess
import wave
from types import MappingProxyType

import pytest
import pytest_asyncio
from aiohttp import web
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.universal_stt.const import DOMAIN


@pytest.fixture(scope="session")
def audio():
    """Generate a real 100 ms waveform and MP3; FFmpeg is a required dependency."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "Install FFmpeg before running the actual HA tests"
    pcm = b"\x00\x01\xff\x7f" * 1200
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    wav_bytes = output.getvalue()
    mp3 = subprocess.run(
        [ffmpeg, "-v", "error", "-i", "pipe:0", "-f", "mp3", "pipe:1"],
        input=wav_bytes,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    return {"pcm": pcm, "wav": wav_bytes, "mp3": mp3, "ffmpeg": ffmpeg}


@pytest_asyncio.fixture
async def hass(tmp_path, unused_tcp_port):
    """Boot installed HA core/platforms using an isolated loopback HTTP port."""
    instance = HomeAssistant(str(tmp_path))
    instance.config.skip_pip = True
    loader.async_setup(instance)
    instance.config_entries = config_entries.ConfigEntries(instance, {})
    try:
        await bootstrap.async_load_base_functionality(instance)
        await async_process_ha_core_config(
            instance,
            {
                "latitude": 37.5,
                "longitude": 127.0,
                "elevation": 0,
                "time_zone": "Asia/Seoul",
                "country": "KR",
                "currency": "KRW",
                "language": "ko",
                "unit_system": "metric",
                "auth_mfa_modules": [],
            },
        )
        assert await async_setup_component(
            instance,
            "http",
            {"http": {"server_host": "127.0.0.1", "server_port": unused_tcp_port}},
        )
        assert await async_setup_component(instance, "stt", {})
        assert await async_setup_component(instance, "tts", {})
        yield instance
    finally:
        await instance.async_stop(force=True)


class LocalProvider:
    """Replace only upstream HTTP; real client sessions and providers remain active."""

    def __init__(self, audio):
        self.audio = dict(audio)
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stall = False
        self.truncate = False
        self.status = 200
        self.connections = []
        self.speech_mime = "audio/mpeg"
        self.speech_format = "mp3"
        self.speech_first_size = 256

    @staticmethod
    def event(payload):
        return b"data: " + json.dumps(payload).encode() + b"\r\n\r\n"

    def delta(self, pcm):
        return self.event(
            {
                "event_type": "step.delta",
                "delta": {
                    "type": "audio",
                    "mime_type": "audio/l16",
                    "sample_rate": 24000,
                    "channels": 1,
                    "data": base64.b64encode(pcm).decode(),
                },
            }
        )

    async def respond(self, request):
        if request.content_type == "multipart/form-data":
            body = {}
            reader = await request.multipart()
            async for part in reader:
                value = bytes(await part.read())
                body[part.name] = value if part.filename else value.decode()
        else:
            body = await request.json()
        self.requests.append((request.path, body, dict(request.headers)))
        self.connections.append(request.transport)
        self.entered.set()
        if self.status != 200:
            return web.Response(status=self.status, text="provider failure")
        if request.path.endswith(("/transcriptions", "/stt")):
            return web.json_response({"text": "runtime transcript"})
        if request.path.endswith("/interactions"):
            if body["input"][0]["type"] == "audio":
                return web.json_response(
                    self.completed({"type": "text", "text": "runtime transcript"})
                )
            if not body.get("stream"):
                return web.json_response(
                    self.completed(
                        {
                            "type": "audio",
                            "mime_type": "audio/wav",
                            "data": base64.b64encode(self.audio["wav"]).decode(),
                        }
                    )
                )
            mime = "text/event-stream"
            pcm = self.audio["pcm"]
            first, last = self.delta(pcm[:2400]), self.delta(pcm[2400:])
            if not self.truncate:
                last += self.event(
                    {"event_type": "interaction.completed", "interaction": {"status": "completed"}}
                )
        else:
            mime = self.speech_mime
            data = self.audio[self.speech_format]
            first, last = data[: self.speech_first_size], data[self.speech_first_size :]
        response = web.StreamResponse(headers={"Content-Type": mime})
        await response.prepare(request)
        try:
            await response.write(first)
            if self.stall:
                await self.release.wait()
            await response.write(last)
            await response.write_eof()
        except (ConnectionResetError, RuntimeError):
            # Tests intentionally close sockets through the real unload boundary.
            pass
        return response

    @staticmethod
    def completed(part):
        return {"status": "completed", "steps": [{"type": "model_output", "content": [part]}]}


@pytest_asyncio.fixture
async def provider(audio):
    upstream = LocalProvider(audio)
    app = web.Application()
    app.router.add_post("/{path:.*}", upstream.respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    upstream.base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    try:
        yield upstream
    finally:
        upstream.release.set()
        await runner.cleanup()


@pytest_asyncio.fixture
async def add_entry(hass, provider):
    async def add(service="custom", mode="both", **changes):
        settings = {
            "provider": service,
            "base_url": provider.base,
            "api_key": "local-test-key",
            "mode": mode,
            "model": "transcription-model",
            "tts_model": "xai-tts" if service == "xai" else "speech-model",
            "voice": "eve" if service == "xai" else "Kore",
            "voices": ["Kore", "eve"],
            **changes,
        }
        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="Test Universal Voice",
            data=settings,
            options={},
            source="user",
            unique_id=f"runtime-test-{len(hass.config_entries.async_entries(DOMAIN))}",
            discovery_keys=MappingProxyType({}),
            subentries_data=None,
        )
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED
        return entry

    return add


def entity_ids(hass, entry):
    """Read IDs from HA's registry, never reconstruct an entity slug."""
    return {
        row.domain: row.entity_id
        for row in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
