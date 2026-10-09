"""Test the transport and audio without importing Home Assistant."""

import asyncio
import importlib
import io
import sys
import types
import unittest
import wave
from dataclasses import replace
from pathlib import Path

import aiohttp
from aiohttp import web

# Load only the standalone modules, not the HA-dependent package initializer.
package = types.ModuleType("stt_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
client_module = importlib.import_module("stt_test_package.client")
audio_module = importlib.import_module("stt_test_package.audio")
const_module = importlib.import_module("stt_test_package.const")
settings_module = importlib.import_module("stt_test_package.settings")
transport_module = importlib.import_module("stt_test_package.transport")
contracts_module = importlib.import_module("stt_test_package.contracts")
formats_module = importlib.import_module("stt_test_package.audio_formats")


async def chunks(*values):
    for value in values:
        yield value


class AudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_wav_contains_original_pcm_and_correct_header(self):
        pcm = b"\x00\x00\xff\x7f"
        data = await audio_module.collect_wav(chunks(pcm[:1], pcm[1:]))
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual(
                (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000)
            )
            self.assertEqual(wav.readframes(2), pcm)

    async def test_reject_empty_incomplete_and_oversize_audio(self):
        for pcm in (b"", b"\x00", b"\x00" * (const_module.MAX_AUDIO_BYTES + 2)):
            with self.subTest(length=len(pcm)), self.assertRaises(ValueError):
                await audio_module.collect_wav(chunks(pcm))


class URLTests(unittest.TestCase):
    def test_api_root(self):
        self.assertEqual(
            client_module.normalize_base_url(" http://localhost:8080/v1/ "),
            "http://localhost:8080/v1",
        )
        for value in (
            "file:///tmp/a",
            "https://",
            "https://user:secret@host/v1",
            "https://host/v1?key=secret",
            "https://host/#fragment",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client_module.normalize_base_url(value)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.payload = {"data": []}
        self.redirect_target_hit = False
        self.form = {}
        self.modality = "transcription"
        self.speech_body = b"ID3test-audio"
        self.speech_type = "audio/mpeg"
        self.speech_request = None
        app = web.Application()
        app.router.add_get("/v1/models", self.models)
        app.router.add_get("/catalog", self.catalog)
        app.router.add_post("/v1/audio/transcriptions", self.transcribe)
        app.router.add_post("/v1/audio/speech", self.speech)
        app.router.add_post("/custom/recognize", self.transcribe)
        app.router.add_post("/custom/speak", self.custom_speech)
        app.router.add_post("/v1/stt", self.transcribe)
        app.router.add_post("/v1/tts", self.speech)
        app.router.add_get("/v1/tts/voices", self.models)
        app.router.add_get("/redirect-target", self.redirect_target)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.session = aiohttp.ClientSession()
        self.client = client_module.create_voice_client(
            transport_module.Transport(self.session),
            settings_module.VoiceSettings(
                base_url=f"http://127.0.0.1:{port}/v1", api_key="test-key"
            ),
        )

        self.client.audio_formats = formats_module.load_audio_formats()

    def use_settings(self, **changes):
        self.client = client_module.create_voice_client(
            transport_module.Transport(self.session), replace(self.client.settings, **changes)
        )

    async def discover_catalog(self, modality="transcription"):
        self.catalog_result = await self.client.discover_models(modality)
        return self.catalog_result.models

    async def custom_catalog(self, url, api_key=""):
        endpoint = contracts_module.Endpoint.resolve(
            url, self.client.settings.base_url, self.client.settings.api_key, api_key
        )
        self.catalog_result = await self.client.discover_custom_models(endpoint)
        return self.catalog_result.models

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def models(self, request):
        self.assertEqual(request.query.get("output_modalities"), self.modality)
        self.assertEqual(request.headers.get("Authorization"), "Bearer test-key")
        if self.status == 302:
            raise web.HTTPFound("/redirect-target")
        return web.json_response(self.payload, status=self.status)

    async def catalog(self, request):
        self.catalog_headers = dict(request.headers)
        self.catalog_query = dict(request.query)
        if self.status == 302:
            raise web.HTTPFound("/redirect-target")
        return web.json_response(self.payload, status=self.status)

    async def custom_speech(self, request):
        self.endpoint_auth = request.headers.get("Authorization")
        self.endpoint_query = dict(request.query)
        self.speech_request = await request.json()
        return web.Response(body=self.speech_body, content_type=self.speech_type)

    async def test_custom_inference_urls_and_separate_keys(self):
        self.use_settings(provider="custom")
        origin = self.client.settings.base_url.removesuffix("/v1")
        self.use_settings(
            **{
                "stt_url": origin + "/custom/recognize",
                "tts_url": origin + "/custom/speak?quality=high",
                "tts_api_key": "tts-only",
            }
        )
        self.payload = {"text": "transcript"}
        self.assertEqual(await self.client.transcribe(b"wav", "stt-model", "ko"), "transcript")
        self.assertEqual(
            await self.client.synthesize("hello", "tts-model", "voice"), self.speech_body
        )
        self.assertEqual(self.endpoint_auth, "Bearer tts-only")
        self.assertEqual(self.endpoint_query, {"quality": "high"})
        self.assertEqual(self.speech_request["model"], "tts-model")

    async def test_custom_inference_cross_origin_key_isolation_and_default(self):
        self.use_settings(provider="custom")
        target = self.client.settings.base_url.removesuffix("/v1") + "/custom/speak"
        self.use_settings(base_url="https://other.example/v1")
        self.use_settings(tts_url=target)
        await self.client.synthesize("hello", "model", "voice")
        self.assertIsNone(self.endpoint_auth)
        self.use_settings(stt_url="", tts_url="", stt_api_key="", tts_api_key="")
        self.assertEqual(
            self.client.settings.inference_endpoint("stt").url,
            "https://other.example/v1/audio/transcriptions",
        )

    async def test_custom_catalog_formats_queries_and_same_origin_auth(self):
        url = self.client.settings.base_url.removesuffix("/v1") + "/catalog?kind=audio"
        self.payload = {
            "data": [{"id": "speech-a", "name": "A", "supported_voices": ["Kore", "Kore"]}, None]
        }
        self.assertEqual(await self.custom_catalog(url), {"speech-a": "A"})
        self.assertEqual(self.catalog_result.model_voices, {"speech-a": ("Kore",)})
        self.assertEqual(self.catalog_headers.get("Authorization"), "Bearer test-key")
        self.assertEqual(self.catalog_query, {"kind": "audio"})
        self.payload = {"models": ["local-a", {"name": "local-b", "displayName": "B"}]}
        self.assertEqual(await self.custom_catalog(url), {"local-a": "local-a", "local-b": "B"})

    async def test_custom_catalog_cross_origin_never_reuses_speech_key(self):
        url = self.client.settings.base_url.removesuffix("/v1") + "/catalog"
        self.use_settings(base_url="https://speech.example/v1")
        self.payload = {"data": []}
        await self.custom_catalog(url)
        self.assertNotIn("Authorization", self.catalog_headers)
        await self.custom_catalog(url, "catalog-only-key")
        self.assertEqual(self.catalog_headers.get("Authorization"), "Bearer catalog-only-key")
        self.assertEqual(
            self.client.settings.inference_endpoint("stt").headers,
            {"Authorization": "Bearer test-key"},
        )

    async def test_custom_catalog_errors_and_redirects(self):
        url = self.client.settings.base_url.removesuffix("/v1") + "/catalog"
        for payload in ({}, {"data": "bad"}, {"data": [{"unexpected": "shape"}]}):
            self.payload = payload
            with self.assertRaises(client_module.STTError):
                await self.custom_catalog(url)
        self.status = 302
        with self.assertRaises(client_module.STTError):
            await self.custom_catalog(url)
        self.assertFalse(self.redirect_target_hit)

    async def redirect_target(self, request):
        self.redirect_target_hit = True
        return web.json_response({"data": []})

    async def transcribe(self, request):
        reader = await request.multipart()
        while part := await reader.next():
            self.form[part.name] = bytes(await part.read())
            if part.name == "file":
                self.assertEqual(part.filename, "speech.wav")
                self.assertEqual(part.headers["Content-Type"], "audio/wav")
        return web.json_response(self.payload, status=self.status)

    async def speech(self, request):
        self.assertEqual(request.headers.get("Authorization"), "Bearer test-key")
        self.speech_request = await request.json()
        if self.status == 302:
            raise web.HTTPFound("/redirect-target")
        return web.Response(
            body=self.speech_body, content_type=self.speech_type, status=self.status
        )

    async def test_xai_transcription_catalog_uses_live_model_ids(self):
        self.use_settings(provider="xai")
        self.modality = None
        self.payload = {"data": [{"id": "grok-voice-transcribe-2.0"}, {"id": "grok-4"}, None]}
        self.assertEqual(
            await self.discover_catalog(),
            {"grok-voice-transcribe-2.0": "grok-voice-transcribe-2.0"},
        )
        self.payload = {"data": []}
        self.assertEqual(await self.discover_catalog(), {})

    async def test_xai_native_transcription_file_last(self):
        self.use_settings(provider="xai")
        self.payload = {"text": "안녕하세요"}
        result = await self.client.transcribe(b"wav", "grok-voice-transcribe-2.0", "ko")
        self.assertEqual(result, "안녕하세요")
        self.assertEqual(list(self.form), ["model", "language", "file"])
        self.assertEqual(self.form["language"], b"ko")

    async def test_xai_native_speech_and_voice_discovery(self):
        self.use_settings(provider="xai")
        self.modality = None
        self.payload = {"voices": [{"voice_id": "eve"}, {"voice_id": "eve"}, None]}
        self.assertEqual(await self.discover_catalog("speech"), {"xai-tts": "xAI Text to Speech"})
        self.assertEqual(self.catalog_result.voices_for("xai-tts"), ("eve",))
        result = await self.client.synthesize("안녕하세요", "xai-tts", "eve", language="ko")
        self.assertEqual(result, self.speech_body)
        self.assertEqual(
            self.speech_request,
            {
                "text": "안녕하세요",
                "voice_id": "eve",
                "language": "ko",
                "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000},
            },
        )

    async def test_openai_catalog_without_openrouter_parameters(self):
        self.use_settings(provider="openai")
        self.modality = None
        self.payload = {
            "data": [
                {"id": m}
                for m in (
                    "gpt-4o",
                    "gpt-4o-mini-tts",
                    "tts-1",
                    "gpt-4o-transcribe",
                    "gpt-4o-transcribe-diarize",
                    "whisper-1",
                )
            ]
        }
        self.assertEqual(set(await self.discover_catalog()), {"gpt-4o-transcribe", "whisper-1"})
        self.assertEqual(set(await self.discover_catalog("speech")), {"gpt-4o-mini-tts", "tts-1"})
        self.assertIn("marin", self.catalog_result.model_voices["gpt-4o-mini-tts"])
        self.assertNotIn("marin", self.catalog_result.model_voices["tts-1"])

    async def test_custom_speech_does_not_send_language(self):
        self.use_settings(provider="custom")
        await self.client.synthesize("안녕", "local-model", "voice", language="ko")
        self.assertNotIn("language", self.speech_request)

    async def test_tts_catalog_and_voice_ids(self):
        self.modality = "speech"
        self.payload = {
            "data": [
                {
                    "id": "tts/model",
                    "supported_voices": ["alloy", "alloy", None, "Kore"],
                    "architecture": {"output_modalities": ["speech"]},
                },
                {"id": "stt/model", "architecture": {"output_modalities": ["transcription"]}},
            ]
        }
        self.assertEqual(await self.discover_catalog("speech"), {"tts/model": "tts/model"})
        self.assertEqual(self.catalog_result.model_voices, {"tts/model": ("alloy", "Kore")})

    async def test_openrouter_tts_requests_default_pcm_but_accepts_mp3_response(self):
        audio = await self.client.synthesize("안녕하세요", "tts/model", "Kore")
        self.assertEqual(audio, self.speech_body)
        self.assertEqual(
            self.speech_request,
            {
                "input": "안녕하세요",
                "model": "tts/model",
                "voice": "Kore",
                "response_format": "pcm",
            },
        )

    async def test_tts_rejects_bad_response_and_errors(self):
        for status in (401, 403, 429, 500, 302):
            self.status = status
            with self.subTest(status=status), self.assertRaises(client_module.STTError):
                await self.client.synthesize("hello", "model", "voice")
        self.assertFalse(self.redirect_target_hit)
        self.status = 200
        for content_type, body in [("application/json", b'{"error":"oops"}'), ("audio/mpeg", b"")]:
            self.speech_type, self.speech_body = content_type, body
            with self.subTest(content_type=content_type), self.assertRaises(client_module.STTError):
                await self.client.synthesize("hello", "model", "voice")

    async def test_catalog_filters_non_stt_and_skips_malformed_entries(self):
        self.payload = {
            "data": [
                {
                    "id": "stt/model",
                    "name": "Speech",
                    "architecture": {"output_modalities": ["transcription"]},
                },
                {"id": "chat/model", "architecture": {"output_modalities": ["text"]}},
                {"id": "filtered/model"},
                None,
                {"name": "No ID"},
            ]
        }
        self.assertEqual(
            await self.discover_catalog(),
            {"filtered/model": "filtered/model", "stt/model": "Speech"},
        )

    async def test_transcription_upload(self):
        self.payload = {"text": "  거실 불 켜줘  "}
        wav = await audio_module.collect_wav(chunks(b"\x00\x00" * 100))
        self.assertEqual(await self.client.transcribe(wav, "stt/model", "ko"), "거실 불 켜줘")
        self.assertEqual(
            self.form,
            {"file": wav, "model": b"stt/model", "language": b"ko", "response_format": b"json"},
        )

    async def test_authentication_and_service_errors(self):
        for status in (401, 403, 429, 500):
            self.status = status
            error = (
                client_module.AuthenticationError
                if status in (401, 403)
                else client_module.STTError
            )
            with self.subTest(status=status), self.assertRaises(error):
                await self.discover_catalog()

    async def test_malformed_catalog(self):
        for payload in ([], {}, {"data": "invalid"}):
            self.payload = payload
            with self.subTest(payload=payload), self.assertRaises(client_module.STTError):
                await self.discover_catalog()

    async def test_missing_transcript(self):
        self.payload = {"text": None}
        with self.assertRaises(client_module.STTError):
            await self.client.transcribe(b"audio", "model", "ko")

    async def test_does_not_follow_redirects(self):
        self.status = 302
        with self.assertRaises(client_module.STTError):
            await self.discover_catalog()
        self.assertFalse(self.redirect_target_hit)

    async def test_cancellation_is_not_swallowed(self):
        task = asyncio.create_task(self.discover_catalog())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
