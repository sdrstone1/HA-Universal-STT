"""Test stored snapshot, credential editing, and pure provider contract boundaries."""

import importlib
import sys
import types
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

package = types.ModuleType("settings_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
settings_module = importlib.import_module("settings_test_package.settings")
contracts = importlib.import_module("settings_test_package.contracts")
VoiceSettings = settings_module.VoiceSettings


def stored_custom():
    return {
        "provider": "custom",
        "base_url": "https://voice.example/v1",
        "mode": "both",
        "api_key": "shared-secret",
        "model": "recognizer",
        "tts_model": "speaker",
        "voice": "voice-a",
        "voices": ["voice-a"],
        "stt_models_url": "https://voice.example/stt-models",
        "tts_models_url": "https://voice.example/tts-models",
        "stt_models_api_key": "stt-catalog-secret",
        "tts_models_api_key": "tts-catalog-secret",
        "stt_url": "https://voice.example/transcribe",
        "tts_url": "https://voice.example/speak",
        "stt_api_key": "stt-secret",
        "tts_api_key": "tts-secret",
        "tts_streaming": True,
    }


class SnapshotTests(unittest.TestCase):
    def test_nonempty_options_are_a_complete_snapshot(self):
        entry = types.SimpleNamespace(data=stored_custom(), options={"model": "edited"})
        raw = settings_module.settings_for(entry)
        self.assertEqual(raw, {"model": "edited"})
        typed = VoiceSettings.from_entry(entry)
        self.assertEqual(typed.model, "edited")
        self.assertEqual(typed.api_key, "")
        self.assertEqual(typed.mode, "stt")
        self.assertFalse(typed.tts_streaming)

    def test_empty_options_use_data_and_both_helpers_remain_independent(self):
        data = stored_custom()
        entry = types.SimpleNamespace(data=data, options={})
        raw = settings_module.settings_for(entry)
        typed = VoiceSettings.from_entry(entry)
        raw["voices"].append("later")
        raw["api_key"] = "replacement"
        self.assertEqual(data["voices"], ["voice-a"])
        self.assertEqual(typed.voices, ("voice-a",))
        data["voices"].append("outside")
        self.assertEqual(typed.voices, ("voice-a",))
        exported = typed.as_dict()
        exported["voices"].append("edited-copy")
        self.assertEqual(typed.voices, ("voice-a",))
        with self.assertRaises(FrozenInstanceError):
            typed.api_key = "changed"

    def test_legacy_projection_distinguishes_absent_from_explicit_empty(self):
        data = {
            "models_url": "https://voice.example/catalog",
            "models_api_key": "legacy-secret",
            "stt_models_url": "",
            "stt_models_api_key": "",
        }
        original = deepcopy(data)
        typed = VoiceSettings.from_mapping(data)
        self.assertEqual(typed.stt_models_url, "")
        self.assertEqual(typed.stt_models_api_key, "")
        self.assertEqual(typed.tts_models_url, data["models_url"])
        self.assertEqual(typed.tts_models_api_key, data["models_api_key"])
        self.assertEqual(data, original)

    def test_all_credentials_are_absent_from_repr(self):
        data = stored_custom()
        text = repr(VoiceSettings.from_mapping(data))
        for key, value in data.items():
            if "api_key" in key:
                self.assertNotIn(value, text)

    def test_url_queries_and_private_paths_are_absent_from_repr(self):
        data = stored_custom()
        data["base_url"] = "https://voice.example/private-base-token"
        for key in ("stt_models_url", "tts_models_url", "stt_url", "tts_url"):
            data[key] = f"https://voice.example/private-{key}?token=secret-{key}"
        text = repr(VoiceSettings.from_mapping(data))
        for key in ("base_url", "stt_models_url", "tts_models_url", "stt_url", "tts_url"):
            self.assertNotIn(data[key], text)
            self.assertNotIn(f"private-{key}", text)
            self.assertNotIn(f"secret-{key}", text)
        self.assertNotIn("private-base-token", text)

    def test_existing_missing_mode_and_new_draft_default_are_distinct(self):
        self.assertEqual(settings_module.mode_for({}), "stt")
        self.assertEqual(VoiceSettings.from_mapping({}).mode, "stt")
        self.assertEqual(settings_module.apply_connection_edit({}, {})["mode"], "both")

    def test_typed_settings_reject_invalid_values_without_echoing_secrets(self):
        for edits in (
            {"provider": "unknown"},
            {"mode": "unknown"},
            {"tts_streaming": "false"},
            {"voices": "one-voice"},
            {"voices": [123]},
            {"api_key": {"credential": "secret"}},
        ):
            with self.subTest(edits=edits), self.assertRaises(ValueError) as caught:
                VoiceSettings.from_mapping(edits)
            self.assertNotIn("secret", str(caught.exception))


class ConnectionEditTests(unittest.TestCase):
    def test_blank_secret_preserves_same_connection_and_clear_overrides_replacement(self):
        current = stored_custom()
        keys = [key for key in current if "api_key" in key]
        result = settings_module.apply_connection_edit(current, dict.fromkeys(keys, ""))
        for key in keys:
            self.assertEqual(result[key], current[key])
            with self.subTest(key=key):
                cleared = settings_module.apply_connection_edit(
                    current, {key: "replacement", f"clear_{key}": True}
                )
                self.assertEqual(cleared[key], "")
        self.assertEqual(current, stored_custom())

    def test_provider_and_base_changes_remove_old_secrets_and_model_selection(self):
        current = stored_custom()
        for edits in (
            {"provider": "openai", "base_url": "https://ignored.example/v1"},
            {"base_url": "https://replacement.example/v1"},
            # A path change on the same origin also represents a new connection.
            {"base_url": "https://voice.example/v2"},
        ):
            with self.subTest(edits=edits):
                result = settings_module.apply_connection_edit(current, edits)
                for key in current:
                    if "api_key" in key:
                        self.assertEqual(result[key], "")
                for key in ("model", "tts_model", "voice", "voices"):
                    self.assertNotIn(key, result)
        preset = settings_module.apply_connection_edit(current, {"provider": "openai"})
        self.assertEqual(preset["base_url"], "https://api.openai.com/v1")

    def test_replacement_keys_are_explicit_even_after_destination_change(self):
        current = stored_custom()
        edits = {"base_url": "https://replacement.example/v1"}
        for key in current:
            if "api_key" in key:
                edits[key] = f"replacement-{key}"
        result = settings_module.apply_connection_edit(current, edits)
        for key in edits:
            if "api_key" in key:
                self.assertEqual(result[key], edits[key])

    def test_one_endpoint_change_clears_only_its_dedicated_key(self):
        current = stored_custom()
        for url_field, key_field in (
            ("stt_models_url", "stt_models_api_key"),
            ("tts_models_url", "tts_models_api_key"),
            ("stt_url", "stt_api_key"),
            ("tts_url", "tts_api_key"),
        ):
            with self.subTest(url_field=url_field):
                result = settings_module.apply_connection_edit(
                    current, {url_field: "https://voice.example/changed?version=2"}
                )
                self.assertEqual(result[key_field], "")
                for other in current:
                    if "api_key" in other and other != key_field:
                        self.assertEqual(result[other], current[other])
                self.assertEqual(result["model"], current["model"])

    def test_blank_catalog_clears_key_and_blank_inference_selects_default(self):
        current = stored_custom()
        result = settings_module.apply_connection_edit(
            current, {"stt_models_url": "", "stt_url": ""}
        )
        self.assertEqual(result["stt_models_api_key"], "")
        self.assertEqual(result["stt_api_key"], "")
        endpoint = VoiceSettings.from_mapping(result).inference_endpoint("stt")
        self.assertEqual(endpoint.url, current["base_url"] + "/audio/transcriptions")
        self.assertEqual(endpoint.headers, {"Authorization": "Bearer shared-secret"})

    def test_normalized_base_url_keeps_key_when_only_trailing_slash_changes(self):
        current = stored_custom()
        result = settings_module.apply_connection_edit(
            current, {"base_url": " https://voice.example/v1/ ", "api_key": ""}
        )
        self.assertEqual(result["api_key"], current["api_key"])
        self.assertEqual(result["model"], current["model"])

    def test_legacy_edit_preserves_both_keys_but_feature_empty_wins(self):
        current = {
            "provider": "custom",
            "base_url": "https://voice.example/v1",
            "models_url": "https://voice.example/catalog",
            "models_api_key": "legacy-secret",
        }
        result = settings_module.apply_connection_edit(
            current, {"stt_models_url": "", "models_url": current["models_url"]}
        )
        self.assertEqual(result["stt_models_url"], "")
        self.assertEqual(result["stt_models_api_key"], "")
        self.assertEqual(result["tts_models_api_key"], "legacy-secret")
        self.assertIn("models_url", result)  # Drafts do not finalize the legacy cleanup.

    def test_invalid_edit_leaves_saved_and_draft_values_unchanged(self):
        current = stored_custom()
        original = deepcopy(current)
        edits = {"api_key": "replacement", "tts_url": "https://user:secret@host/speech"}
        submitted = deepcopy(edits)
        with self.assertRaises(ValueError):
            settings_module.apply_connection_edit(current, edits)
        self.assertEqual(current, original)
        self.assertEqual(edits, submitted)

    def test_presets_ignore_invalid_old_custom_urls_and_keep_valid_shared_key(self):
        old = {
            "provider": "openrouter",
            "api_key": "saved",
            "base_url": "https://openrouter.ai/api/v1",
            "stt_url": "file:///private",
            "tts_models_url": "not-a-url",
        }
        result = settings_module.apply_connection_edit(old, {"mode": "both"})
        self.assertEqual(result["api_key"], "saved")
        self.assertEqual(result["tts_models_url"], "")
        self.assertEqual(result["stt_url"], "")

    def test_inactive_custom_urls_do_not_block_active_feature(self):
        old = {
            "provider": "custom",
            "base_url": "https://voice.example/v1",
            "mode": "stt",
            "tts_url": "file:///private",
            "tts_models_url": "not-a-url",
        }
        result = settings_module.apply_connection_edit(old, {})
        self.assertEqual(result["tts_url"], old["tts_url"])
        self.assertNotIn("tts_url", settings_module.clean_settings(result))

    def test_base_change_clears_hidden_feature_keys_without_validating_hidden_urls(self):
        old = {**stored_custom(), "mode": "stt", "tts_url": "not-a-url"}
        result = settings_module.apply_connection_edit(old, {"base_url": "https://new.example/v1"})
        self.assertEqual(result["tts_url"], old["tts_url"])
        self.assertEqual(result["tts_api_key"], "")
        self.assertEqual(result["tts_models_api_key"], "")

    def test_missing_preset_base_preserves_key_at_its_provider_default(self):
        old = {"api_key": "saved", "model": "legacy"}
        result = settings_module.apply_connection_edit(
            old, {"provider": "openrouter", "mode": "both"}
        )
        self.assertEqual(result["api_key"], "saved")
        self.assertEqual(result["model"], "legacy")

    def test_cleanup_only_removes_legacy_inactive_and_noncustom_fields_on_copy(self):
        for provider in ("custom", "openai"):
            for mode in ("stt", "tts", "both"):
                with self.subTest(provider=provider, mode=mode):
                    current = {
                        **stored_custom(),
                        "provider": provider,
                        "mode": mode,
                        "models_url": "https://voice.example/legacy",
                        "models_api_key": "legacy-secret",
                        "language": "ko",
                    }
                    original = deepcopy(current)
                    result = settings_module.clean_settings(current)
                    self.assertEqual(current, original)
                    for key in ("models_url", "models_api_key", "language"):
                        self.assertNotIn(key, result)
                    for feature in ("stt", "tts"):
                        active_custom = provider == "custom" and mode in {feature, "both"}
                        self.assertEqual(f"{feature}_url" in result, active_custom)
                        self.assertEqual(f"{feature}_models_url" in result, active_custom)
                    self.assertEqual("model" in result, mode != "tts")
                    self.assertEqual("tts_model" in result, mode != "stt")
                    self.assertEqual("tts_streaming" in result, mode != "stt")


class EndpointTests(unittest.TestCase):
    def test_url_security_validation_without_sending_requests(self):
        rejected = (
            "file:///tmp/audio",
            "https://",
            "https://user:secret@host/audio",
            "https://host/audio#fragment",
            "https://host/audio#",
            "https://host:invalid/audio",
            "https://host:65536/audio",
            "https://host:0/audio",
            "https://host\\evil/audio",
            "https://ho\nst/audio",
            "https://host/audio path",
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                contracts.Endpoint(url)
            self.assertNotIn("secret", str(caught.exception))
        for url in ("https://host/v1?", "https://host/v1?key=value"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                contracts.normalize_base_url(url)
        self.assertEqual(
            contracts.Endpoint(" http://localhost:8000/audio?quality=high ").url,
            "http://localhost:8000/audio?quality=high",
        )

    def test_shared_key_uses_scheme_host_and_effective_port_and_dedicated_key_wins(self):
        base = "https://voice.example/v1"
        for url, expected in (
            ("https://VOICE.example:443/catalog?audio=1", "shared"),
            ("https://voice.example/catalog", "shared"),
            ("http://voice.example/catalog", ""),
            ("https://other.example/catalog", ""),
            ("https://voice.example:444/catalog", ""),
        ):
            with self.subTest(url=url):
                endpoint = contracts.Endpoint.resolve(url, base, "shared")
                self.assertEqual(endpoint.api_key, expected)
                explicit = contracts.Endpoint.resolve(url, base, "shared", "dedicated")
                self.assertEqual(explicit.headers, {"Authorization": "Bearer dedicated"})
        endpoint = contracts.Endpoint.resolve("http://localhost:80/audio", "http://localhost/v1")
        self.assertEqual(endpoint.headers, {})

    def test_headers_are_independent_and_gemini_header_does_not_use_bearer(self):
        endpoint = contracts.Endpoint("https://host/interactions", "google-secret", "google")
        self.assertEqual(endpoint.headers, {"x-goog-api-key": "google-secret"})
        endpoint.headers.clear()
        self.assertEqual(endpoint.headers, {"x-goog-api-key": "google-secret"})
        self.assertNotIn("google-secret", repr(endpoint))
        with self.assertRaises(ValueError):
            contracts.Endpoint("https://host/audio", "key\r\ninjected")

    def test_endpoint_repr_does_not_expose_query_authentication_or_private_path(self):
        endpoint = contracts.Endpoint("https://host/private-token/audio?token=query-secret")
        self.assertNotIn("private-token", repr(endpoint))
        self.assertNotIn("query-secret", repr(endpoint))

    def test_provider_default_endpoints_and_custom_cross_origin_isolation(self):
        for provider, stt, tts in (
            ("openrouter", "audio/transcriptions", "audio/speech"),
            ("openai", "audio/transcriptions", "audio/speech"),
            ("xai", "stt", "tts"),
            ("gemini", "interactions", "interactions"),
        ):
            with self.subTest(provider=provider):
                typed = VoiceSettings.from_mapping({"provider": provider, "api_key": "key"})
                self.assertEqual(typed.inference_endpoint("stt").url, typed.base_url + "/" + stt)
                self.assertEqual(typed.inference_endpoint("tts").url, typed.base_url + "/" + tts)
        data = {**stored_custom(), "tts_api_key": "", "tts_url": "https://other.example/speech"}
        typed = VoiceSettings.from_mapping(data)
        self.assertEqual(typed.inference_endpoint("tts").headers, {})
        self.assertEqual(typed.catalog_endpoint("tts").api_key, "tts-catalog-secret")
        self.assertIsNone(VoiceSettings.from_mapping({}).catalog_endpoint("stt"))


class CatalogTests(unittest.TestCase):
    def test_snapshot_owns_choices_and_distinguishes_provider_and_model_voice_scope(self):
        models = {"model": "Label"}
        voices = {"model": ["model-voice"], "empty": []}
        snapshot = contracts.CatalogSnapshot(
            models, voices, ["provider-voice"], "live", "documented"
        )
        models["later"] = "Later"
        voices["model"].append("later")
        self.assertEqual(dict(snapshot.models), {"model": "Label"})
        self.assertEqual(snapshot.voices_for("model"), ("model-voice",))
        self.assertEqual(snapshot.voices_for("empty"), ())
        self.assertEqual(snapshot.voices_for("manual-model"), ("provider-voice",))
        with self.assertRaises(TypeError):
            snapshot.models["later"] = "Later"
        with self.assertRaises(TypeError):
            snapshot.model_voices["model"] = ()
        self.assertEqual(snapshot.models_source, "live")
        self.assertEqual(snapshot.voices_source, "documented")
