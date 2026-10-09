"""Exercise entity language forwarding with a minimal HA API substitute.

These tests run the production entity, but are not HA runtime integration tests.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

package = types.ModuleType("language_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
languages = importlib.import_module("language_test_package.languages")


class LanguageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Stub the HA interface only; execute the real entity and WAV collector.
        stt = types.ModuleType("homeassistant.components.stt")
        stt.SpeechToTextEntity = type("SpeechToTextEntity", (), {})
        stt.SpeechResult = lambda text, state: (text, state)
        stt.SpeechResultState = types.SimpleNamespace(SUCCESS="success", ERROR="error")
        components = types.ModuleType("homeassistant.components")
        components.stt = stt
        with patch.dict(
            sys.modules,
            {
                "homeassistant": types.ModuleType("homeassistant"),
                "homeassistant.components": components,
                "homeassistant.components.stt": stt,
            },
        ):
            module = importlib.import_module("language_test_package.stt")
        self.entity_class = module.UniversalSTT

    def make_entity(self, legacy=False):
        data = {"model": "custom-model"}
        if legacy:
            data["language"] = "ko"
        self.client = types.SimpleNamespace(transcribe=AsyncMock(return_value="transcript"))
        entry = types.SimpleNamespace(
            data=data, options={}, runtime_data=self.client, title="STT", entry_id="existing-id"
        )
        entity = self.entity_class(entry)
        # HA's metadata checks are outside the scope of this substitute.
        entity.check_metadata = lambda metadata: metadata.language in entity.supported_languages
        return entity

    async def test_new_and_existing_entries_follow_each_pipeline_request(self):
        async def audio():
            yield b"\x00\x00" * 10

        for legacy in (False, True):
            entity = self.make_entity(legacy)
            for language in ("ja", "de", "fr", "es", "zh", "ko", "en"):
                with self.subTest(legacy=legacy, language=language):
                    result = await entity.async_process_audio_stream(
                        types.SimpleNamespace(language=language), audio()
                    )
                    self.assertEqual(result, ("transcript", "success"))
                    args = self.client.transcribe.call_args.args
                    self.assertEqual(args[1:], ("custom-model", language))
                    self.assertTrue(args[0].startswith(b"RIFF"))
            self.assertEqual(entity._attr_unique_id, "existing-id")

    def test_language_list_is_unique_and_not_mutable_through_entity(self):
        entity = self.make_entity()
        self.assertEqual(len(languages.PIPELINE_LANGUAGES), 184)
        self.assertEqual(len(set(entity.supported_languages)), 184)
        entity.supported_languages.clear()
        self.assertIn("ja", entity.supported_languages)

    async def test_every_advertised_language_is_forwarded_without_model_filtering(self):
        entity = self.make_entity(legacy=True)
        for language in languages.PIPELINE_LANGUAGES:
            with self.subTest(language=language):

                async def audio():
                    yield b"\x00\x00"

                result = await entity.async_process_audio_stream(
                    types.SimpleNamespace(language=language), audio()
                )
                self.assertEqual(result, ("transcript", "success"))
                self.assertEqual(self.client.transcribe.call_args.args[2], language)
