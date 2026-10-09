"""Validate administrator-edited audio policy before any provider request."""

import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from test_openrouter_format_probe import formats_module

errors = importlib.import_module("format_probe_package.errors")
VALID = {
    "version": 1,
    "defaults": {"request_format": "pcm"},
    "models": {
        "exact/model": {
            "supported_formats": ["pcm", "mp3"],
            "request_format": "mp3",
            "pcm": {"rate": 24000, "channels": 1},
            "source": "https://example.org/audio-contract",
        }
    },
}


class AudioFormatConfigTests(unittest.TestCase):
    def load(self, value, *, raw=False):
        # Fixtures stay inside the graph workspace rather than the global temp root.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "formats.json"
            path.write_text(value if raw else json.dumps(value), encoding="utf-8")
            return formats_module.load_audio_formats(path)

    def test_bundled_default_and_override_have_no_unverified_pcm_fallback(self):
        config = formats_module.load_audio_formats()
        self.assertEqual(config.default_request_format, "pcm")
        self.assertEqual(config.request_format_for("minimax/speech-2.8-hd"), "mp3")
        self.assertEqual(config.request_format_for("minimax/speech-2.8-hd-extra"), "pcm")
        self.assertIsNone(config.get("google/gemini-tts"))
        for rule in config.values():
            self.assertIsNone(rule.rate)
            self.assertIsNone(rule.channels)

    def test_explicit_policy_is_immutable_and_model_ids_are_exact(self):
        config = self.load(VALID)
        self.assertEqual(config.request_format_for("exact/model"), "mp3")
        self.assertEqual(config.request_format_for("exact/model-extra"), "pcm")
        rule = config["exact/model"]
        self.assertEqual((rule.rate, rule.channels), (24000, 1))
        with self.assertRaises(TypeError):
            config.models["new/model"] = rule
        with self.assertRaises(AttributeError):
            rule.channels = 2

    def test_malformed_configuration_errors_are_fixed_and_private(self):
        cases = [[], None, {"version": 1}, {**VALID, "extra": "PRIVATE"}]
        for field, value in (
            ("version", True),
            ("version", 2),
            ("defaults", []),
            ("defaults", {"request_format": "flac"}),
            ("models", []),
        ):
            item = copy.deepcopy(VALID)
            item[field] = value
            cases.append(item)
        for field, value in (
            ("supported_formats", []),
            ("supported_formats", ["pcm", "pcm"]),
            ("supported_formats", ["flac"]),
            ("supported_formats", "pcm"),
            ("request_format", None),
            ("request_format", "wav"),
            ("source", "file:///PRIVATE"),
            ("pcm", {}),
            ("pcm", {"rate": True, "channels": 1}),
            ("pcm", {"rate": 7999, "channels": 1}),
            ("pcm", {"rate": 24000, "channels": 9}),
            ("pcm", {"rate": "24000", "channels": 1}),
            ("extra", "PRIVATE"),
        ):
            item = copy.deepcopy(VALID)
            item["models"]["exact/model"][field] = value
            cases.append(item)
        for model in ("", " model", "model "):
            item = copy.deepcopy(VALID)
            item["models"] = {model: item["models"]["exact/model"]}
            cases.append(item)
        # The default must itself be documented as supported when no override exists.
        item = copy.deepcopy(VALID)
        item["models"]["exact/model"].pop("request_format")
        item["models"]["exact/model"]["supported_formats"] = ["mp3"]
        cases.append(item)
        for index, item in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(errors.ResponseError) as raised:
                self.load(item)
            self.assertEqual(str(raised.exception), "Invalid model audio format configuration")
            self.assertTrue(raised.exception.__suppress_context__)

    def test_duplicate_keys_invalid_json_and_missing_file_are_rejected(self):
        for text in (
            '{"version":1,"version":1,"defaults":{"request_format":"pcm"},"models":{}}',
            '{"version":1,"defaults":{"request_format":"pcm","request_format":"mp3"},"models":{}}',
            "PRIVATE not JSON",
        ):
            with self.subTest(text=text), self.assertRaises(errors.ResponseError):
                self.load(text, raw=True)
        with self.assertRaises(errors.ResponseError):
            formats_module.load_audio_formats(Path(__file__).with_name("nonexistent-policy.json"))
