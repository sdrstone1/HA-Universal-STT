"""Exercise native Gemini requests against an isolated HTTP server."""

import base64
import importlib
import io
import unittest
import wave

import aiohttp
from aiohttp import web
from test_core import client_module, settings_module, transport_module

gemini = importlib.import_module("stt_test_package.gemini")


class GeminiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.pages = {
            "": {"models": [{"name": "models/gemini-3.8-flash"}], "nextPageToken": "next"},
            "next": {
                "models": [
                    {"name": "models/gemini-3.8-flash-tts"},
                    {"name": "models/gemini-live-audio"},
                    None,
                ]
            },
        }
        self.response = {
            "status": "completed",
            "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "  불 켜줘  "}]}
            ],
        }
        app = web.Application()
        app.router.add_get("/v1beta/models", self.models)
        app.router.add_get("/v1beta/voices", self.voices)
        self.voice_requests = []
        self.voice_pages = {
            "": {"voices": [{"id": "Kore"}], "next_page_token": "v2"},
            "v2": {"voices": [{"id": "Puck"}, {"id": "Kore"}, None]},
        }
        app.router.add_post("/v1beta/interactions", self.interactions)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.session = aiohttp.ClientSession()
        self.client = gemini.GeminiClient(
            transport_module.Transport(self.session),
            settings_module.VoiceSettings(
                provider="gemini",
                base_url=f"http://127.0.0.1:{self.runner.addresses[0][1]}/v1beta",
                api_key="google-key",
            ),
        )

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def models(self, request):
        self.assertEqual(request.headers.get("x-goog-api-key"), "google-key")
        self.assertNotIn("Authorization", request.headers)
        self.requests.append(dict(request.query))
        return web.json_response(self.pages[request.query.get("pageToken", "")])

    async def voices(self, request):
        self.assertEqual(request.headers.get("x-goog-api-key"), "google-key")
        self.voice_requests.append(dict(request.query))
        return web.json_response(self.voice_pages[request.query.get("page_token", "")])

    async def test_voice_pagination_rejects_cycles(self):
        self.voice_pages["v2"]["next_page_token"] = "v2"
        with self.assertRaises(client_module.STTError):
            await self.client.discover_voices()

    async def interactions(self, request):
        self.assertEqual(request.headers.get("x-goog-api-key"), "google-key")
        self.assertNotIn("Authorization", request.headers)
        self.body = await request.json()
        return web.json_response(self.response)

    async def test_catalog_pagination_shared_between_stt_and_tts(self):
        self.assertEqual(
            (await self.client.discover_models()).models, {"gemini-3.8-flash": "gemini-3.8-flash"}
        )
        self.assertEqual(
            (await self.client.discover_models("speech")).models,
            {"gemini-3.8-flash-tts": "gemini-3.8-flash-tts"},
        )
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[1]["pageToken"], "next")
        self.assertEqual(len(self.voice_requests), 2)
        self.assertEqual(self.voice_requests[1]["page_token"], "v2")
        self.assertEqual(
            (await self.client.discover_models("speech")).voices_for("gemini-3.8-flash-tts"),
            ("Kore", "Puck"),
        )

    async def test_repeated_page_token_is_rejected(self):
        self.pages["next"]["nextPageToken"] = "next"
        with self.assertRaises(client_module.STTError):
            await self.client.discover_models()
        self.assertIsNone(self.client._catalog)

    async def test_transcription_preserves_audio_and_returns_only_model_text(self):
        self.response["steps"].insert(
            0, {"type": "thought", "content": [{"type": "text", "text": "not the transcript"}]}
        )
        self.assertEqual(
            await self.client.transcribe(b"wav-input", "models/gemini-3.8-flash", "ko"), "불 켜줘"
        )
        self.assertEqual(base64.b64decode(self.body["input"][0]["data"]), b"wav-input")
        self.assertFalse(self.body["store"])
        self.assertIn("ko", self.body["system_instruction"])
        self.assertEqual(self.body["model"], "gemini-3.8-flash")

    async def test_speech_requests_wav_and_validates_decoded_audio(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x00\x00" * 24)
        data = output.getvalue()
        self.response["steps"] = [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "audio",
                        "mime_type": "audio/wav",
                        "data": base64.b64encode(data).decode(),
                    }
                ],
            }
        ]
        self.assertEqual(
            await self.client.synthesize("안녕하세요", "gemini-3.8-flash-tts", "Kore", "ko"), data
        )
        self.assertEqual(self.body["response_format"], {"type": "audio", "mime_type": "audio/wav"})
        self.assertEqual(self.body["generation_config"]["speech_config"], [{"voice": "Kore"}])
        self.assertEqual(self.client.audio_format, "wav")
        for invalid in (
            "!bad base64!",
            base64.b64encode(b"not a wav").decode(),
            base64.b64encode(data[:-2]).decode(),
            base64.b64encode(data[:24] + bytes(4) + data[28:]).decode(),
            base64.b64encode(data[:40] + bytes(4)).decode(),
        ):
            self.response["steps"][0]["content"][0]["data"] = invalid
            with self.assertRaises(client_module.STTError):
                await self.client.synthesize("hello", "gemini-3.8-flash-tts", "Kore")

    async def test_incomplete_and_missing_outputs_fail(self):
        for payload in ({"status": "failed"}, {"status": "completed", "steps": []}):
            self.response = payload
            with self.assertRaises(client_module.STTError):
                await self.client.transcribe(b"audio", "gemini-3.8-flash", "ko")
