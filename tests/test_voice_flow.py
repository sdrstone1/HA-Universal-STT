"""Exercise production config steps with HA interfaces replaced by small adapters.

Voluptuous schemas are real. These tests do not simulate a full HA instance.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

package = types.ModuleType("voice_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package


class FlowAdapter:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


def modules():
    ha = types.ModuleType("homeassistant")
    config = types.ModuleType("homeassistant.config_entries")
    config.ConfigFlow = FlowAdapter
    config.OptionsFlow = FlowAdapter
    core = types.ModuleType("homeassistant.core")
    core.callback = lambda f: f
    helpers = types.ModuleType("homeassistant.helpers")
    selectors = types.ModuleType("homeassistant.helpers.selector")
    selectors.SelectSelectorConfig = lambda **kwargs: kwargs
    selectors.TextSelectorConfig = lambda **kwargs: kwargs
    selectors.SelectSelector = lambda config: str
    selectors.TextSelector = lambda config: str
    selectors.SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown")
    selectors.TextSelectorType = types.SimpleNamespace(PASSWORD="password")
    aio = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aio.async_get_clientsession = lambda hass: None
    session = types.ModuleType("voice_test_package.http_session")
    session.async_get_voice_session = lambda hass: None
    ha.config_entries = config
    helpers.selector = selectors
    return {m.__name__: m for m in (ha, config, core, helpers, selectors, aio, session)}


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clients = importlib.import_module("voice_test_package.client")
        self.gemini = importlib.import_module("voice_test_package.gemini")
        self.contracts = importlib.import_module("voice_test_package.contracts")
        with patch.dict(sys.modules, modules()):
            self.module = importlib.import_module("voice_test_package.config_flow")

    async def connect(self, flow, data):
        step = (
            flow.async_step_init
            if isinstance(flow, self.module.OptionsFlow)
            else flow.async_step_user
        )
        selection = {key: data[key] for key in ("provider", "mode")}
        connection = await step(selection)
        self.assertEqual(connection["step_id"], "connection")
        return await flow.async_step_connection(
            {key: value for key, value in data.items() if key not in selection}
        )

    async def start(self, mode):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        result = await self.connect(
            flow, {"provider": "custom", "mode": mode, "base_url": "http://localhost:8000/v1"}
        )
        return flow, result

    async def test_stt_tts_and_combined_setup(self):
        for mode in ("stt", "tts", "both"):
            flow, result = await self.start(mode)
            if mode != "tts":
                self.assertEqual(result["step_id"], "model")
                result = await flow.async_step_model({"model": "stt/model"})
            if mode != "stt":
                self.assertEqual(result["step_id"], "tts")
                result = await flow.async_step_tts({"tts_model": "tts/model"})
                self.assertEqual(result["step_id"], "voice")
                result = await flow.async_step_voice({"voice": "custom-voice"})
            self.assertEqual(result["type"], "create_entry")
            self.assertEqual(result["data"]["mode"], mode)
            self.assertEqual("model" in result["data"], mode != "tts")
            self.assertEqual("tts_model" in result["data"], mode != "stt")

    async def test_existing_stt_can_add_tts_without_replacing_key_or_stt_model(self):
        old = {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "secret",
            "model": "stt/model",
            "language": "ko",
        }
        entry = types.SimpleNamespace(data=old, options={})
        flow = self.module.OptionsFlow(entry)
        flow.hass = object()
        form = await flow.async_step_init({"provider": "openrouter", "mode": "both"})
        data = {
            "provider": "openrouter",
            "mode": "both",
            **form["data_schema"]({"discover": False}),
        }
        await self.connect(flow, data)
        await flow.async_step_model({"model": old["model"]})
        await flow.async_step_tts({"tts_model": "tts/model"})
        result = await flow.async_step_voice({"voice": "alloy"})
        self.assertEqual(result["data"]["api_key"], "secret")
        self.assertEqual(result["data"]["model"], old["model"])
        self.assertNotIn("language", result["data"])
        self.assertEqual(entry.data, old)  # Not mutated during editing.

    async def test_blank_ids_and_voice_are_rejected(self):
        flow, _ = await self.start("both")
        self.assertEqual(
            (await flow.async_step_model({"model": " "}))["errors"]["base"], "invalid_model"
        )
        await flow.async_step_model({"model": "stt"})
        self.assertEqual(
            (await flow.async_step_tts({"tts_model": " "}))["errors"]["base"], "invalid_model"
        )
        await flow.async_step_tts({"tts_model": "tts"})
        self.assertEqual(
            (await flow.async_step_voice({"voice": " "}))["errors"]["base"], "invalid_voice"
        )

    async def test_discovery_failure_can_be_bypassed(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {"provider": "openrouter", "mode": "tts", "api_key": "key"}
        with patch.object(
            self.clients.STTClient,
            "discover_models",
            AsyncMock(side_effect=self.module.STTError("offline")),
        ):
            result = await self.connect(flow, data)
        self.assertEqual(result["errors"]["base"], "cannot_connect")
        result = await self.connect(flow, {**data, "discover": False})
        self.assertEqual(result["step_id"], "tts")

    async def test_xai_tts_skips_nonexistent_model_selector(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        result = await self.connect(
            flow, {"provider": "xai", "mode": "tts", "api_key": "xai-key", "discover": False}
        )
        self.assertEqual(result["step_id"], "voice")
        result = await flow.async_step_voice({"voice": "eve"})
        self.assertEqual(result["data"]["base_url"], "https://api.x.ai/v1")
        self.assertEqual(result["data"]["tts_model"], "xai-tts")

    async def test_provider_switch_never_reuses_credentials_or_models(self):
        entry = types.SimpleNamespace(
            options={},
            data={
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "model": "old-model",
                "voice": "old-voice",
            },
        )
        flow = self.module.OptionsFlow(entry)
        flow.hass = object()
        await self.connect(flow, {"provider": "openai", "mode": "stt", "discover": False})
        self.assertEqual(flow._settings["api_key"], "")
        self.assertNotIn("model", flow._settings)
        self.assertNotIn("voice", flow._settings)
        self.assertEqual(flow._settings["base_url"], "https://api.openai.com/v1")

    async def test_custom_catalog_fetches_once_and_allows_manual_model(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {
            "provider": "custom",
            "mode": "both",
            "base_url": "http://localhost/v1",
            "models_url": "http://localhost/catalog?type=audio",
            "api_key": "key",
        }
        with patch.object(
            self.clients.STTClient,
            "discover_custom_models",
            AsyncMock(return_value=self.contracts.CatalogSnapshot(models={"known": "Known model"})),
        ) as fetch:
            result = await self.connect(flow, data)
        fetch.assert_awaited_once_with(self.contracts.Endpoint(data["models_url"], "key"))
        self.assertEqual(result["step_id"], "model")
        self.assertEqual(flow._stt_models, {"known": "Known model"})
        self.assertEqual(flow._tts_models, flow._stt_models)
        await flow.async_step_model({"model": "not-in-catalog"})
        await flow.async_step_tts({"tts_model": "another-model"})
        result = await flow.async_step_voice({"voice": "voice"})
        self.assertEqual(result["data"]["stt_models_url"], data["models_url"])
        self.assertEqual(result["data"]["model"], "not-in-catalog")

    async def test_custom_catalog_failure_and_disabled_discovery(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {
            "provider": "custom",
            "mode": "stt",
            "base_url": "http://localhost/v1",
            "models_url": "http://localhost/catalog",
        }
        with patch.object(
            self.clients.STTClient,
            "discover_custom_models",
            AsyncMock(side_effect=self.module.STTError("bad catalog")),
        ) as fetch:
            result = await self.connect(flow, data)
            self.assertEqual(result["errors"]["base"], "cannot_connect")
            result = await self.connect(flow, {**data, "discover": False})
            self.assertEqual(result["step_id"], "model")
            self.assertEqual(fetch.await_count, 1)

    async def test_catalog_key_is_retained_only_for_same_connection_and_url(self):
        data = {
            "provider": "custom",
            "mode": "stt",
            "base_url": "http://localhost/v1",
            "models_url": "http://localhost/catalog",
            "models_api_key": "catalog-secret",
        }
        entry = types.SimpleNamespace(data=data, options={})
        for url, expected in [
            (data["models_url"], "catalog-secret"),
            ("http://other-server/catalog", ""),
        ]:
            flow = self.module.OptionsFlow(entry)
            flow.hass = object()
            await self.connect(
                flow, {**data, "models_url": url, "models_api_key": "", "discover": False}
            )
            self.assertEqual(flow._settings["stt_models_api_key"], expected)

    async def test_separate_catalogs_and_one_blank_side(self):
        data = {
            "provider": "custom",
            "mode": "both",
            "base_url": "http://localhost/v1",
            "stt_models_url": "http://localhost/stt-models",
            "tts_models_url": "http://localhost/tts-models",
        }
        flow = self.module.ConfigFlow()
        flow.hass = object()
        with patch.object(
            self.clients.STTClient,
            "discover_custom_models",
            AsyncMock(
                side_effect=[
                    self.contracts.CatalogSnapshot(models={"recognizer": "STT"}),
                    self.contracts.CatalogSnapshot(models={"speaker": "TTS"}),
                ]
            ),
        ) as fetch:
            await self.connect(flow, data)
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(flow._stt_models, {"recognizer": "STT"})
        self.assertEqual(flow._tts_models, {"speaker": "TTS"})
        with patch.object(
            self.clients.STTClient,
            "discover_custom_models",
            AsyncMock(return_value=self.contracts.CatalogSnapshot(models={"recognizer": "STT"})),
        ) as fetch:
            await self.connect(flow, {**data, "tts_models_url": ""})
        fetch.assert_awaited_once_with(self.contracts.Endpoint(data["stt_models_url"]))
        self.assertEqual(flow._tts_models, {})

    async def test_old_shared_catalog_populates_both_fields(self):
        old = {
            "provider": "custom",
            "base_url": "http://localhost/v1",
            "mode": "both",
            "models_url": "http://localhost/catalog",
            "models_api_key": "secret",
        }
        flow = self.module.OptionsFlow(types.SimpleNamespace(data=old, options={}))
        flow.hass = object()
        form = await flow.async_step_init({"provider": "custom", "mode": "both"})
        data = {"provider": "custom", "mode": "both", **form["data_schema"]({"discover": False})}
        self.assertEqual(data["stt_models_url"], old["models_url"])
        self.assertEqual(data["tts_models_url"], old["models_url"])
        await self.connect(flow, data)
        saved = flow._clean_settings()
        self.assertEqual(saved["stt_models_api_key"], "secret")
        self.assertEqual(saved["tts_models_api_key"], "secret")
        self.assertNotIn("models_url", saved)

    async def test_gemini_uses_native_discovery(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        with patch.object(
            self.gemini.GeminiClient,
            "discover_models",
            AsyncMock(
                return_value=self.contracts.CatalogSnapshot(models={"gemini-3.8-flash": "Flash"})
            ),
        ) as fetch:
            result = await self.connect(
                flow, {"provider": "gemini", "mode": "stt", "api_key": "google-key"}
            )
        fetch.assert_awaited_once()
        self.assertEqual(result["step_id"], "model")
        self.assertEqual(
            flow._settings["base_url"], "https://generativelanguage.googleapis.com/v1beta"
        )

    async def test_custom_inference_settings_save_and_key_clears_on_url_change(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {
            "provider": "custom",
            "mode": "both",
            "base_url": "https://speech.example/v1",
            "stt_url": "https://speech.example/recognize",
            "tts_url": "https://tts.example/speak",
            "tts_api_key": "tts-secret",
            "discover": False,
        }
        await self.connect(flow, data)
        await flow.async_step_model({"model": "stt"})
        await flow.async_step_tts({"tts_model": "tts"})
        result = await flow.async_step_voice({"voice": "voice"})
        self.assertEqual(result["data"]["tts_url"], data["tts_url"])
        self.assertEqual(result["data"]["tts_api_key"], "tts-secret")
        edit = self.module.OptionsFlow(types.SimpleNamespace(data=result["data"], options={}))
        edit.hass = object()
        await self.connect(
            edit, {**data, "tts_url": "https://new.example/speak", "tts_api_key": ""}
        )
        self.assertEqual(edit._settings["tts_api_key"], "")

    async def test_invalid_inference_url_rejected_before_fetch(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        result = await self.connect(
            flow,
            {
                "provider": "custom",
                "mode": "tts",
                "base_url": "https://example.com/v1",
                "tts_url": "file:///tmp/audio",
            },
        )
        self.assertEqual(result["errors"]["base"], "invalid_url")

    async def test_custom_dedup_uses_effective_auth_including_shared_fallback(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {
            "provider": "custom",
            "mode": "both",
            "base_url": "https://voice.example/v1",
            "api_key": "shared",
            "stt_models_url": "https://voice.example/catalog",
            "tts_models_url": "https://voice.example/catalog",
            "tts_models_api_key": "shared",
        }
        with patch.object(
            self.clients.STTClient,
            "discover_custom_models",
            AsyncMock(return_value=self.contracts.CatalogSnapshot(models={"model": "Model"})),
        ) as fetch:
            await self.connect(flow, data)
        fetch.assert_awaited_once_with(self.contracts.Endpoint(data["stt_models_url"], "shared"))
        self.assertEqual(flow._stt_models, flow._tts_models)

    async def test_explicit_blank_catalog_and_inactive_feature_are_not_fetched(self):
        flow = self.module.ConfigFlow()
        flow.hass = object()
        data = {
            "provider": "custom",
            "mode": "stt",
            "base_url": "https://voice.example/v1",
            "models_url": "https://voice.example/legacy",
            "stt_models_url": "",
            "tts_models_url": "https://voice.example/tts",
        }
        with patch.object(self.clients.STTClient, "discover_custom_models", AsyncMock()) as fetch:
            await self.connect(flow, data)
        fetch.assert_not_awaited()
        self.assertEqual(flow._stt_models, {})
        result = await flow.async_step_model({"model": "manual"})
        self.assertNotIn("models_url", result["data"])
        self.assertNotIn("tts_models_url", result["data"])

    async def test_streaming_defaults_false_and_only_completed_tts_snapshot_stores_it(self):
        for enabled in (False, True):
            flow = self.module.ConfigFlow()
            flow.hass = object()
            form = await flow.async_step_user({"provider": "openai", "mode": "tts"})
            data = {"provider": "openai", "mode": "tts", **form["data_schema"]({"discover": False})}
            self.assertFalse(data["tts_streaming"])
            data["tts_streaming"] = enabled
            await self.connect(flow, data)
            await flow.async_step_tts({"tts_model": "gpt-4o-mini-tts"})
            result = await flow.async_step_voice({"voice": "marin"})
            self.assertEqual(result["data"]["tts_streaming"], enabled)

    async def test_failed_or_cancelled_discovery_preserves_entry_snapshot_and_safe_errors(self):
        import asyncio
        from copy import deepcopy

        old = {
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "saved",
            "model": "stt",
            "language": "ko",
        }
        entry = types.SimpleNamespace(data=old, options={})
        original = deepcopy(old)
        for error in (self.module.STTError("secret-response"), asyncio.CancelledError()):
            flow = self.module.OptionsFlow(entry)
            flow.hass = object()
            with patch.object(
                self.clients.STTClient, "discover_models", AsyncMock(side_effect=error)
            ):
                data = {"provider": "openai", "mode": "both", "api_key": "replacement"}
                if isinstance(error, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):
                        await self.connect(flow, data)
                else:
                    result = await self.connect(flow, data)
                    self.assertEqual(result["errors"], {"base": "cannot_connect"})
                    self.assertNotIn("secret-response", str(result["errors"]))
            self.assertEqual(entry.data, original)
            self.assertEqual(entry.options, {})

    async def test_voice_scope_and_factory_identity(self):
        self.assertIs(self.module.create_voice_client, self.clients.create_voice_client)
        flow = self.module.ConfigFlow()
        flow.hass = object()
        await self.connect(flow, {"provider": "openai", "mode": "tts", "discover": False})
        flow._tts_catalog = self.contracts.CatalogSnapshot(
            model_voices={"empty-model": ()}, provider_voices=("provider-voice",)
        )
        await flow.async_step_tts({"tts_model": "empty-model"})
        self.assertEqual(flow._settings["voices"], [])
        await flow.async_step_tts({"tts_model": "manual-model"})
        self.assertEqual(flow._settings["voices"], ["provider-voice"])
