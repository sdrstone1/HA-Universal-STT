"""Test TTS entity behavior without a Home Assistant runtime."""

import importlib
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

package = types.ModuleType("tts_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package


@dataclass
class TTSAudioRequest:
    language: str
    options: dict
    message_gen: object


@dataclass
class TTSAudioResponse:
    extension: str
    data_gen: object


def load_tts_module():
    """Use the public HA request/response shapes without importing the HA runtime."""
    tts = types.ModuleType("homeassistant.components.tts")
    tts.TextToSpeechEntity = type("TextToSpeechEntity", (), {})
    tts.Voice = lambda **kwargs: types.SimpleNamespace(**kwargs)
    tts.TTSAudioRequest = TTSAudioRequest
    tts.TTSAudioResponse = TTSAudioResponse
    core = types.ModuleType("homeassistant.core")
    core.callback = lambda f: f
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    with patch.dict(
        sys.modules,
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.components": types.ModuleType("homeassistant.components"),
            "homeassistant.components.tts": tts,
            "homeassistant.core": core,
            "homeassistant.exceptions": exceptions,
        },
    ):
        return importlib.import_module("tts_test_package.tts")


class TTSEntityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_tts_module()
        self.errors = importlib.import_module("tts_test_package.errors")
        self.client = types.SimpleNamespace(
            synthesize=AsyncMock(return_value=b"ID3audio"), audio_format="mp3"
        )
        self.entry = types.SimpleNamespace(
            entry_id="stable-id",
            runtime_data=self.client,
            data={"model": "old-stt"},
            options={"tts_model": "tts-model", "voice": "Kore", "voices": ["Kore", "Puck"]},
        )
        self.entity = self.module.UniversalTTS(self.entry, "ko-KR")

    async def test_default_and_pipeline_voice_override(self):
        self.assertEqual(self.entity.default_language, "ko")
        self.assertEqual(self.entity._attr_unique_id, "stable-id_tts")
        self.assertEqual(self.entity.default_options["model"], "tts-model")
        self.assertEqual(self.entity.default_options["voice"], "Kore")
        self.assertEqual(
            [v.voice_id for v in self.entity.async_get_supported_voices("ko")], ["Kore", "Puck"]
        )
        self.assertEqual(
            await self.entity.async_get_tts_audio("안녕하세요", "ko", {}), ("mp3", b"ID3audio")
        )
        self.client.synthesize.assert_awaited_with("안녕하세요", "tts-model", "Kore", language="ko")
        await self.entity.async_get_tts_audio("こんにちは", "ja", {"voice": "Puck"})
        self.client.synthesize.assert_awaited_with("こんにちは", "tts-model", "Puck", language="ja")

    async def test_service_failure_returns_no_audio(self):
        self.client.synthesize.side_effect = self.errors.STTError("private text and credentials")
        with self.assertLogs(self.module.__name__, level="WARNING"):
            self.assertEqual(await self.entity.async_get_tts_audio("hello", "en", {}), (None, None))

    async def test_invalid_voice_does_not_make_request(self):
        self.assertEqual(
            await self.entity.async_get_tts_audio("hello", "en", {"voice": " "}), (None, None)
        )
        self.client.synthesize.assert_not_awaited()

    async def test_xai_regional_languages_are_preserved(self):
        self.entry.options.update(provider="xai", tts_model="xai-tts", voice="eve")
        entity = self.module.UniversalTTS(self.entry, "pt_PT")
        self.assertEqual(entity.default_language, "pt-PT")
        self.assertIn("ko", entity.supported_languages)
        self.assertIn("es-MX", entity.supported_languages)
        self.assertNotIn("af", entity.supported_languages)
        await entity.async_get_tts_audio("Olá", "pt-PT", {})
        self.client.synthesize.assert_awaited_with("Olá", "xai-tts", "eve", language="pt-PT")

    async def test_native_wav_format_is_forwarded_to_home_assistant(self):
        self.client.audio_format = "wav"
        self.client.synthesize.return_value = b"RIFFtest"
        self.assertEqual(
            await self.entity.async_get_tts_audio("hello", "en", {}), ("wav", b"RIFFtest")
        )

    async def test_invalid_request_options_are_rejected_before_provider(self):
        for options in (
            {"model": "different"},
            {"model": None},
            {"connection_revision": "old"},
            {"connection_revision": None},
            {"voice": 1},
            ["invalid"],
        ):
            with self.subTest(options=options), self.assertLogs(self.module.__name__, "WARNING"):
                self.assertEqual(
                    await self.entity.async_get_tts_audio("hello", "en", options), (None, None)
                )
        self.client.synthesize.assert_not_awaited()

    async def test_revision_is_stable_per_instance_and_changes_on_reload(self):
        options = self.entity.default_options
        self.assertEqual(options, self.entity.default_options)
        self.assertIn("connection_revision", self.entity.supported_options)
        self.assertRegex(options["connection_revision"], "^[0-9a-f]{32}$")
        replacement = self.module.UniversalTTS(self.entry, "ko")
        self.assertNotEqual(
            options["connection_revision"], replacement.default_options["connection_revision"]
        )
        self.assertNotIn("connection_revision", self.entry.options)
        await self.entity.async_get_tts_audio("hello", "en", options)
        self.client.synthesize.assert_awaited_once()
        self.client.synthesize.reset_mock()
        with self.assertLogs(self.module.__name__, "WARNING"):
            self.assertEqual(
                await replacement.async_get_tts_audio("hello", "en", options), (None, None)
            )
        self.client.synthesize.assert_not_awaited()

    async def test_text_validation_and_utf8_byte_limit(self):
        self.assertTrue(self.entity.async_supports_streaming_input())
        for message in ("", " \n", None, b"text", "\ud800", "x" * (64 * 1024 + 1), "한" * 21846):
            with (
                self.subTest(kind=type(message).__name__),
                self.assertLogs(self.module.__name__, "WARNING"),
            ):
                self.assertEqual(
                    await self.entity.async_get_tts_audio(message, "en", {}), (None, None)
                )
        self.client.synthesize.assert_not_awaited()
        self.assertEqual(
            await self.entity.async_get_tts_audio("x" * (64 * 1024), "en", None),
            ("mp3", b"ID3audio"),
        )

    async def test_instance_scope_key_prevents_old_cache_namespace_options(self):
        old_options = self.entity.default_options
        old_scope = next(key for key in old_options if key.startswith("connection_scope_"))
        self.assertIn(old_scope, self.entity.supported_options)
        self.assertIs(old_options[old_scope], True)
        self.assertEqual(old_options, self.entity.default_options)
        replacement = self.module.UniversalTTS(self.entry, "ko")
        new_scope = next(
            key for key in replacement.default_options if key.startswith("connection_scope_")
        )
        # HA rejects unsupported old full-options keys before looking up cached audio.
        self.assertNotIn(old_scope, replacement.supported_options)
        self.assertNotIn(old_scope, replacement.default_options)
        self.assertNotEqual(old_scope, new_scope)
        # Overriding only the old revision still leaves the new scope in HA defaults.
        revision_override = replacement.default_options | {
            "connection_revision": old_options["connection_revision"]
        }
        self.assertIn(new_scope, revision_override)
        self.assertNotEqual(old_options, revision_override)
        with self.assertLogs(self.module.__name__, "WARNING"):
            self.assertEqual(
                await replacement.async_get_tts_audio("hello", "en", revision_override),
                (None, None),
            )
        self.client.synthesize.assert_not_awaited()
        self.assertNotIn(old_scope, self.entry.options)
        self.assertNotIn(new_scope, self.entry.options)

    async def test_scope_value_overrides_are_rejected_before_provider(self):
        scope = next(
            key for key in self.entity.default_options if key.startswith("connection_scope_")
        )
        for value in (False, None, "true", 1):
            with self.subTest(value=value), self.assertLogs(self.module.__name__, "WARNING"):
                self.assertEqual(
                    await self.entity.async_get_tts_audio("hello", "en", {scope: value}),
                    (None, None),
                )
        self.client.synthesize.assert_not_awaited()
        self.assertEqual(
            await self.entity.async_get_tts_audio("hello", "en", {scope: True}),
            ("mp3", b"ID3audio"),
        )

    async def test_failures_do_not_log_contents_and_cancellation_propagates(self):
        import asyncio

        self.client.synthesize.side_effect = RuntimeError("PRIVATE-CONTENT")
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            self.assertEqual(
                await self.entity.async_get_tts_audio("PRIVATE-CONTENT", "en", {}), (None, None)
            )
        self.assertNotIn("PRIVATE-CONTENT", " ".join(logs.output))
        self.client.synthesize.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.entity.async_get_tts_audio("hello", "en", {})
