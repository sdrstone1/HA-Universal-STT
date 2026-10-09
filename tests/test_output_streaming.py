"""Real HTTP streaming tests; no Home Assistant runtime or paid APIs required."""

import asyncio
import base64
import importlib
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web

package = types.ModuleType("stream_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
client_module = importlib.import_module("stream_test_package.client")
formats_module = importlib.import_module("stream_test_package.audio_formats")
gemini_module = importlib.import_module("stream_test_package.gemini")
stream_module = importlib.import_module("stream_test_package.gemini_stream")
settings_module = importlib.import_module("stream_test_package.settings")
transport_module = importlib.import_module("stream_test_package.transport")


def event(delta):
    return b"data: " + json.dumps(delta).encode() + b"\r\n\r\n"


def pcm_delta(data):
    return {
        "event_type": "step.delta",
        "delta": {
            "type": "audio",
            "mime_type": "audio/l16",
            "sample_rate": 24000,
            "channels": 1,
            "data": base64.b64encode(data).decode(),
        },
    }


COMPLETE = {"event_type": "interaction.completed", "interaction": {"status": "completed"}}


class StreamingHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.release = asyncio.Event()
        self.requests = []
        self.status = 200
        self.mime = "audio/mpeg"
        self.first = b"ID3first"
        self.last = b"last"
        self.transport = None
        app = web.Application()
        app.router.add_post("/{path:.*}", self.respond)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{self.runner.addresses[0][1]}"
        self.session = aiohttp.ClientSession()

    def make_client(self, provider="openrouter", key="", **changes):
        settings = settings_module.VoiceSettings(
            provider=provider, base_url=self.base, api_key=key, **changes
        )
        client = client_module.create_voice_client(
            transport_module.Transport(self.session), settings
        )
        if provider == "openrouter":
            client.audio_formats = formats_module.load_audio_formats()
        return client

    async def asyncTearDown(self):
        self.release.set()
        await self.session.close()
        await self.runner.cleanup()

    async def respond(self, request):
        self.transport = request.transport
        self.requests.append((request.path, await request.json(), dict(request.headers)))
        response = web.StreamResponse(status=self.status, headers={"Content-Type": self.mime})
        await response.prepare(request)
        try:
            await response.write(self.first)
            await self.release.wait()
            await response.write(self.last)
            await response.write_eof()
        except (ConnectionResetError, RuntimeError):
            pass  # The cancellation tests intentionally close the client connection.
        return response

    async def test_each_mp3_provider_delivers_before_server_finishes(self):
        for provider in ("openai", "openrouter", "xai", "custom"):
            with self.subTest(provider=provider):
                self.release = asyncio.Event()
                client = self.make_client(
                    provider,
                    "key",
                    tts_url=self.base + "/custom/speak" if provider == "custom" else "",
                )
                stream = client.synthesize_stream("hello", "model", "voice", "ko")
                try:
                    self.assertEqual(await asyncio.wait_for(anext(stream), 1), self.first)
                    self.assertFalse(self.release.is_set())
                    path, body, headers = self.requests[-1]
                    self.assertEqual(headers["Authorization"], "Bearer key")
                    self.assertNotIn("stream", body)
                    self.assertEqual(
                        path,
                        "/tts"
                        if provider == "xai"
                        else ("/custom/speak" if provider == "custom" else "/audio/speech"),
                    )
                    if provider == "xai":
                        self.assertEqual(body["language"], "ko")
                    self.release.set()
                    self.assertEqual(b"".join([p async for p in stream]), self.last)
                finally:
                    self.release.set()
                    await stream.aclose()

    async def test_close_and_cancellation_release_http_connection(self):
        client = self.make_client()
        stream = client.synthesize_stream("hello", "model", "voice")
        await anext(stream)
        await stream.aclose()
        self.assertFalse(self.session.connector._acquired)
        self.release.set()
        await asyncio.sleep(0)
        self.release = asyncio.Event()
        stream = client.synthesize_stream("hello", "model", "voice")
        await anext(stream)
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.session.connector._acquired)

    async def test_http_mime_empty_and_size_errors_are_not_silently_accepted(self):
        self.release.set()
        client = self.make_client()
        for status, mime, data in (
            (401, "audio/mpeg", b"bad"),
            (500, "audio/mpeg", b"bad"),
            (302, "audio/mpeg", b"bad"),
            (200, "application/json", b"{}"),
            (200, "audio/mpeg", b""),
            (200, "audio/mpeg", b"x" * (20 * 1024 * 1024 + 1)),
        ):
            with self.subTest(status=status, mime=mime, size=len(data)):
                self.status, self.mime, self.first, self.last = status, mime, data, b""
                with self.assertRaises(client_module.STTError):
                    await client.synthesize("hello", "model", "voice")

    async def test_gemini_delivers_pcm_with_wav_header_before_completion(self):
        self.mime = "text/event-stream"
        pcm = b"\x00\x00\xff\x7f"
        self.first = event(pcm_delta(pcm))
        self.last = event(pcm_delta(pcm)) + event(COMPLETE)
        client = self.make_client("gemini", "google-key")
        stream = client.synthesize_stream("hello", "models/gemini-tts", "Kore")
        first = await asyncio.wait_for(anext(stream), 1)
        self.assertEqual(first, stream_module.wav_stream_header() + pcm)
        self.assertFalse(self.release.is_set())
        path, body, headers = self.requests[0]
        self.assertEqual(path, "/interactions")
        self.assertTrue(body["stream"])
        self.assertFalse(body["store"])
        self.assertEqual(body["response_format"]["mime_type"], "audio/l16")
        self.assertEqual(headers["x-goog-api-key"], "google-key")
        self.assertNotIn("Authorization", headers)
        self.release.set()
        self.assertEqual(b"".join([p async for p in stream]), pcm)

    async def test_gemini_close_releases_http_connection(self):
        self.mime, self.first = "text/event-stream", event(pcm_delta(b"\0\0"))
        client = self.make_client("gemini")
        stream = client.synthesize_stream("hello", "gemini-tts", "Kore")
        await anext(stream)
        await stream.aclose()
        self.assertFalse(self.session.connector._acquired)


class GeminiDecoderTests(unittest.IsolatedAsyncioTestCase):
    async def decode(self, wire, size=3):
        async def chunks(_):
            for offset in range(0, len(wire), size):
                yield wire[offset : offset + size]

        content = chunks(65536)
        return b"".join(
            [p async for p in stream_module.wav_audio(stream_module.sse_events(content))]
        )

    async def test_split_sse_events_and_split_pcm_samples(self):
        result = await self.decode(
            b": keepalive\r\n\r\n"
            + event(pcm_delta(b"\x00"))
            + event(pcm_delta(b"\x01\x02\x03"))
            + event(COMPLETE)
        )
        self.assertEqual(result, stream_module.wav_stream_header() + b"\x00\x01\x02\x03")

    async def test_bad_truncated_empty_and_wrong_format_streams_raise(self):
        wrong = pcm_delta(b"\0\0")
        wrong["delta"]["sample_rate"] = 16000
        invalid = pcm_delta(b"\0\0")
        invalid["delta"]["data"] = "!not-base64!"
        for wire in (
            b"data: {not json}\n\n",
            b"data: " + b"[" * 2000 + b"0" + b"]" * 2000 + b"\n\n",
            b"data: {}",
            event(COMPLETE),
            event(pcm_delta(b"\0\0")),
            event(pcm_delta(b"\0")) + event(COMPLETE),
            event(wrong) + event(COMPLETE),
            event(invalid) + event(COMPLETE),
            event({"event_type": "error", "error": {"message": "secret"}}),
            event({"event_type": "interaction.completed", "interaction": {"status": "cancelled"}}),
        ):
            with self.subTest(wire=wire), self.assertRaises(client_module.STTError):
                await self.decode(wire)

    async def test_event_wire_and_pcm_limits(self):
        wire = event(pcm_delta(b"\0" * 8)) + event(COMPLETE)
        for name, limit in (("MAX_EVENT_BYTES", 10), ("MAX_WIRE_BYTES", 10), ("MAX_PCM_BYTES", 4)):
            with self.subTest(limit=name), patch.object(stream_module, name, limit):
                with self.assertRaises(client_module.STTError):
                    await self.decode(wire)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    async def test_ffmpeg_decodes_streaming_wav_without_losing_samples(self):
        pcm = b"\x00\x01\xff\x7f" * 2400
        data = await self.decode(event(pcm_delta(pcm)) + event(COMPLETE), size=4096)
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "pipe:1"],
            input=data,
            capture_output=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(result.stdout, pcm)
