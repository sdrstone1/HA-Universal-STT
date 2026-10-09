"""Response-first OpenRouter format contracts over isolated loopback HTTP."""

import asyncio
import importlib
import io
import sys
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web
from test_transport import Owner

package = types.ModuleType("format_probe_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
clients = importlib.import_module("format_probe_package.client")
settings_module = importlib.import_module("format_probe_package.settings")
transport_module = importlib.import_module("format_probe_package.transport")
formats_module = importlib.import_module("format_probe_package.audio_formats")
audio_module = importlib.import_module("format_probe_package.openrouter_audio")
runtime_module = importlib.import_module("format_probe_package.runtime")
errors = importlib.import_module("format_probe_package.errors")

PRIVATE = "secret-key private text https://private.example PRIVATE-VOICE"
PCM = b"\x00\x01\xff\x7f" * 6


def make_wav(pcm=PCM, rate=24000, channels=1):
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return result.getvalue()


class OpenRouterFormatProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.mime = "audio/mpeg; token=secret-header"
        self.body = b"ID3local-test-audio"
        self.requests = []
        self.owner = Owner()
        self.stall = False
        self.release = asyncio.Event()
        app = web.Application()
        app.router.add_post("/{path:.*}", self.respond)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{self.runner.addresses[0][1]}"
        self.session = aiohttp.ClientSession()

    async def asyncTearDown(self):
        self.release.set()
        await self.session.close()
        await self.runner.cleanup()

    async def respond(self, request):
        if request.path.endswith("/transcriptions"):
            await request.read()
            return web.json_response({"text": "local transcript"})
        body = await request.json()
        self.requests.append(body)
        mime, data = self.mime, self.body
        if self.mime == "by-model":
            mime, data = (
                ("audio/pcm; rate=16000; channels=2", PCM)
                if body["model"] == "pcm-model"
                else ("audio/mpeg", b"ID3parallel")
            )
        if not self.stall:
            return web.Response(status=self.status, body=data, headers={"Content-Type": mime})
        response = web.StreamResponse(status=self.status, headers={"Content-Type": mime})
        await response.prepare(request)
        try:
            await response.write(data[:3])
            await self.release.wait()
            await response.write(data[3:])
            await response.write_eof()
        except (ConnectionResetError, RuntimeError):
            pass  # Cancellation and unload intentionally close the local socket.
        return response

    def make_client(self, provider="openrouter", owner=None):
        settings = settings_module.VoiceSettings(
            provider=provider, base_url=self.base, api_key="key"
        )
        client = clients.create_voice_client(
            transport_module.Transport(self.session, owner or self.owner), settings
        )
        if provider == "openrouter":
            client.audio_formats = formats_module.load_audio_formats()
        return client

    def assert_released(self):
        self.assertFalse(self.owner.tasks)
        self.assertFalse(self.owner.responses)
        self.assertFalse(self.session.connector._acquired)

    async def test_request_policy_is_exact_and_response_format_is_independent(self):
        for model, expected in (
            ("mistralai/voxtral-mini-tts-2603", "pcm"),
            ("google/gemini-tts", "pcm"),
            ("minimax/speech-2.8-hd", "mp3"),
            ("minimax/speech-2.8-hd-extra", "pcm"),
        ):
            for streamed in (False, True):
                with self.subTest(model=model, streamed=streamed):
                    client = self.make_client()
                    with self.assertLogs(transport_module.__name__, "WARNING") as logs:
                        if streamed:
                            stream = client.synthesize_stream(PRIVATE, model, "voice")
                            await stream.prepare()
                            self.assertEqual(stream.extension, "mp3")
                            try:
                                data = b"".join([chunk async for chunk in stream])
                            finally:
                                await stream.aclose()
                        else:
                            result = await client.synthesize_audio(PRIVATE, model, "voice")
                            self.assertEqual(result.extension, "mp3")
                            data = result.data
                    self.assertEqual(data, self.body)
                    self.assertEqual(self.requests[-1]["response_format"], expected)
                    self.assertNotIn("language", self.requests[-1])
                    self.assertEqual(len(logs.output), 1)
                    self.assertIn("http_status=200 media_type=audio/mpeg", logs.output[0])
                    self.assertNotIn("secret-header", logs.output[0])
                    self.assertNotIn(PRIVATE, logs.output[0])
                    self.assert_released()

    async def test_container_signatures_pass_through_even_without_a_model_rule(self):
        for mime, data, extension in (
            ("audio/wav", make_wav(), "wav"),
            ("audio/x-wav", make_wav(), "wav"),
            ("application/octet-stream", make_wav(), "wav"),
            ("application/octet-stream", b"\xff\xfb\x90\x00frames", "mp3"),
            ("", b"ID3unknown-mime", "mp3"),
        ):
            with self.subTest(mime=mime):
                self.mime, self.body = mime, data
                result = await self.make_client().synthesize_audio("hello", "unlisted", "voice")
                self.assertEqual((result.extension, result.data), (extension, data))
                self.assert_released()

    async def test_pcm_collection_has_exact_header_and_response_metadata(self):
        self.mime, self.body = "audio/pcm; rate=48000; channels=2; encoding=s16le", PCM
        result = await self.make_client().synthesize_audio(
            "hello", "minimax/speech-2.8-hd", "voice"
        )
        self.assertEqual(result.extension, "wav")
        self.assertEqual(self.requests[-1]["response_format"], "mp3")
        with wave.open(io.BytesIO(result.data)) as wav:
            self.assertEqual(
                (wav.getframerate(), wav.getnchannels(), wav.getnframes()), (48000, 2, 6)
            )
            self.assertEqual(wav.readframes(6), PCM)
        self.assert_released()

    async def test_invalid_headers_formats_and_partial_pcm_fail_safely_without_retry(self):
        cases = (
            ("audio/pcm", PCM),
            ("audio/pcm; rate=24000", PCM),
            ("audio/pcm; rate=PRIVATE; channels=1", PCM),
            ("audio/pcm; rate=24000; channels=0", PCM),
            ("audio/pcm; rate=24000; rate=48000; channels=1", PCM),
            ("audio/pcm; rate=24000; channels=1; bits=24", PCM),
            ("audio/pcm; rate=24000; channels=1; endianness=big", PCM),
            ("audio/pcm; rate=24000; channels=2", PCM + b"\0"),
            ("audio/pcm; rate=24000; channels=1", b"ID3contradiction"),
            ("audio/mpeg", make_wav()),
            ("audio/wav", b"ID3contradiction"),
            ("application/octet-stream", PCM),
            ("application/octet-stream", b"\xff\xe8\x00\x00invalid-frame"),
            ("application/json", PRIVATE.encode()),
        )
        for mime, data in cases:
            for streamed in (False, True):
                with self.subTest(mime=mime, streamed=streamed):
                    self.mime, self.body = mime, data
                    before = len(self.requests)
                    with self.assertLogs("format_probe_package", "WARNING") as logs:
                        with self.assertRaises(errors.STTError) as raised:
                            if streamed:
                                stream = self.make_client().synthesize_stream(
                                    PRIVATE, "google/gemini-tts", "voice"
                                )
                                try:
                                    _ = [part async for part in stream]
                                finally:
                                    await stream.aclose()
                            else:
                                await self.make_client().synthesize_audio(
                                    PRIVATE, "google/gemini-tts", "voice"
                                )
                    self.assertEqual(len(self.requests), before + 1)
                    output = str(raised.exception) + " ".join(logs.output)
                    for secret in ("PRIVATE", "private text", "private.example", "secret-header"):
                        self.assertNotIn(secret, output)
                    self.assert_released()

    async def test_pcm_logs_contain_validated_metadata_or_fixed_missing_invalid_states(self):
        for params, expected in (
            ("rate=24000; channels=2", "rate=24000 channels=2"),
            ("rate=24000", "rate=24000 channels=missing"),
            ("rate=secret-header; channels=2", "rate=invalid channels=2"),
        ):
            self.mime, self.body = f"audio/pcm; {params}; token=secret-header", PCM
            with self.assertLogs(audio_module.__name__, "WARNING") as logs:
                try:
                    await self.make_client().synthesize_audio(PRIVATE, "unlisted", "voice")
                except errors.ResponseError:
                    self.assertNotEqual(params, "rate=24000; channels=2")
            self.assertIn(expected, " ".join(logs.output))
            self.assertIn("source=response_header", logs.output[0])
            self.assertNotIn("secret-header", " ".join(logs.output))
            self.assertNotIn(PRIVATE, " ".join(logs.output))
            self.assert_released()

    async def test_pcm_fallback_is_exact_and_valid_response_values_take_precedence(self):
        client = self.make_client()
        client.audio_formats = formats_module.AudioFormatConfig(
            "pcm", {"documented/model": formats_module.ModelAudioFormat(("pcm",), 16000, 1)}
        )
        self.mime, self.body = "audio/pcm", PCM
        result = await client.synthesize_audio("hello", "documented/model", "voice")
        with wave.open(io.BytesIO(result.data)) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels()), (16000, 1))
        with self.assertRaises(errors.ResponseError):
            await client.synthesize_audio("hello", "documented/model-extra", "voice")
        self.mime = "audio/pcm; rate=48000; channels=2"
        result = await client.synthesize_audio("hello", "documented/model", "voice")
        with wave.open(io.BytesIO(result.data)) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels()), (48000, 2))
        self.mime = "audio/pcm; rate=invalid; channels=1"
        with self.assertRaises(errors.ResponseError):
            await client.synthesize_audio("hello", "documented/model", "voice")
        self.assert_released()

    async def test_wav_header_counts_toward_total_audio_limit(self):
        self.mime, self.body = "audio/pcm; rate=24000; channels=1", PCM
        with patch.object(audio_module, "MAX_TTS_AUDIO_BYTES", 44 + len(PCM) - 1):
            with self.assertRaises(errors.ResponseError):
                await self.make_client().synthesize_audio("hello", "model", "voice")
        self.assert_released()

    async def test_cancellation_while_preparing_partial_wav_closes_owned_response(self):
        self.mime, self.body, self.stall = "audio/wav", make_wav(), True
        runtime = runtime_module.EntryRuntime(
            settings_module.VoiceSettings(provider="openrouter", base_url=self.base)
        )
        runtime.client = self.make_client(owner=runtime)
        async with asyncio.timeout(1):
            task = asyncio.create_task(runtime.prepare_synthesize_stream("hello", "model", "voice"))
            while not runtime.responses:
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(runtime.tasks or runtime.responses or runtime.streams)
        self.assertFalse(self.session.connector._acquired)

    async def test_concurrent_formats_are_request_local(self):
        self.mime = "by-model"
        client = self.make_client()
        pcm, mp3 = await asyncio.gather(
            client.synthesize_audio("hello", "pcm-model", "voice"),
            client.synthesize_audio("hello", "mp3-model", "voice"),
        )
        self.assertEqual(mp3.extension, "mp3")
        self.assertEqual(mp3.data, b"ID3parallel")
        self.assertEqual(pcm.extension, "wav")
        with wave.open(io.BytesIO(pcm.data)) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels()), (16000, 2))
            self.assertEqual(wav.readframes(6), PCM)
        self.assertEqual(client.audio_format, "mp3")
        self.assert_released()

    async def test_prepared_unconsumed_stream_expiry_and_unload_release_resources(self):
        self.stall = True
        for unload in (False, True):
            with self.subTest(unload=unload):
                settings = settings_module.VoiceSettings(provider="openrouter", base_url=self.base)
                runtime = runtime_module.EntryRuntime(settings)
                runtime.client = self.make_client(owner=runtime)
                with patch.object(transport_module, "HTTP_TIMEOUT", 0.03):
                    stream = await runtime.prepare_synthesize_stream("hello", "model", "voice")
                    self.assertTrue(runtime.responses)
                    self.assertTrue(runtime.streams)
                    if unload:
                        await runtime.shutdown()
                    else:
                        async with asyncio.timeout(1):
                            while runtime.responses or runtime.streams:
                                await asyncio.sleep(0.005)
                        with self.assertRaises(errors.STTError) as raised:
                            await anext(stream)
                        self.assertEqual(raised.exception.diagnostic.category.value, "timeout")
                await asyncio.gather(stream.aclose(), stream.aclose())
                self.assertFalse(runtime.tasks or runtime.responses or runtime.streams)
                self.assertFalse(self.session.connector._acquired)

    async def test_other_providers_keep_explicit_mp3_without_probe(self):
        for provider in ("openai", "custom"):
            with (
                self.subTest(provider=provider),
                self.assertNoLogs(transport_module.__name__, "WARNING"),
            ):
                self.assertEqual(
                    await self.make_client(provider).synthesize("hello", "model", "voice"),
                    self.body,
                )
            self.assertEqual(self.requests[-1]["response_format"], "mp3")
            self.assert_released()

    async def test_http_failure_is_private_and_stt_has_no_probe(self):
        self.status, self.mime, self.body = (
            400,
            "application/json; token=secret-header",
            PRIVATE.encode(),
        )
        with self.assertLogs(transport_module.__name__, "WARNING") as logs:
            with self.assertRaises(errors.STTError) as raised:
                await self.make_client().synthesize_audio(PRIVATE, "model", "voice")
        self.assertEqual(raised.exception.diagnostic.http_status, 400)
        self.assertIn("http_status=400 media_type=application/json", logs.output[0])
        self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(logs.output))
        self.assert_released()
        with self.assertNoLogs(transport_module.__name__, "WARNING"):
            self.assertEqual(
                await self.make_client().transcribe(b"wav", "stt/model", "ko"), "local transcript"
            )
