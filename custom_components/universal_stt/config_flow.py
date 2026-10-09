"""Configure voice features using pure edit policy and one provider factory."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .catalog import discover_for_settings
from .client import create_voice_client
from .const import DOMAIN, PROVIDER_URLS
from .contracts import CatalogSnapshot
from .errors import AuthenticationError, STTError
from .flow_forms import choice, connection_schema, selection_schema
from .http_session import async_get_voice_session
from .settings import (
    ConnectionURLValidationError,
    VoiceSettings,
    apply_connection_edit,
    clean_settings,
    mode_for,
    project_legacy_catalogs,
    settings_for,
)
from .transport import Transport


class VoiceFlow:
    """Keep drafts local and save only when all enabled feature steps finish."""

    def _initialize(self, settings=None):
        self._settings = project_legacy_catalogs(settings or {})
        self._settings.setdefault("tts_streaming", False)
        self._stt_models = {}
        self._tts_models = {}
        self._tts_catalog = CatalogSnapshot()
        self._selection_values = {}

    async def _selection(self, step_id, user_input):
        errors = {}
        if user_input is not None:
            provider = user_input.get("provider")
            mode = user_input.get("mode")
            if provider not in {*PROVIDER_URLS, "custom"} or mode not in {"stt", "tts", "both"}:
                errors["base"] = "invalid_config"
            else:
                self._selection_values = {"provider": provider, "mode": mode}
                return await self.async_step_connection()
        return self.async_show_form(
            step_id=step_id, data_schema=selection_schema(self._settings), errors=errors
        )

    def _connection_defaults(self):
        current = {**self._settings, **self._selection_values}
        if current["provider"] != self._settings.get("provider", "openrouter"):
            # Never offer old credentials or custom destinations for a new provider.
            current = dict(self._selection_values)
        return current

    async def async_step_connection(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                draft = apply_connection_edit(
                    self._settings, {**user_input, **self._selection_values}
                )
                settings = VoiceSettings.from_mapping(draft)
                for feature in ("stt", "tts"):
                    if settings.enabled(feature):
                        settings.inference_endpoint(feature)
                        settings.catalog_endpoint(feature)
            except ConnectionURLValidationError:
                errors["base"] = "invalid_url"
            except ValueError:
                errors["base"] = "invalid_config"
            else:
                # Keep validated edits locally for retry; entry storage is saved by _finish only.
                self._settings = draft
                self._stt_models, self._tts_models = {}, {}
                self._tts_catalog = CatalogSnapshot()
                try:
                    if user_input.get("discover", True):
                        client = create_voice_client(
                            Transport(async_get_voice_session(self.hass)), settings
                        )
                        catalogs = await discover_for_settings(client, settings)
                        self._stt_models = dict(catalogs.get("stt", CatalogSnapshot()).models)
                        self._tts_catalog = catalogs.get("tts", CatalogSnapshot())
                        self._tts_models = dict(self._tts_catalog.models)
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except (STTError, ValueError):
                    # Discovery/session errors are not evidence of an invalid URL.
                    errors["base"] = "cannot_connect"
                else:
                    if settings.mode == "tts":
                        return await self.async_step_tts()
                    return await self.async_step_model()
        return self.async_show_form(
            step_id="connection",
            data_schema=connection_schema(self._connection_defaults()),
            errors=errors,
        )

    async def async_step_model(self, user_input=None):
        errors = {}
        if user_input is not None:
            model = user_input["model"].strip()
            if model:
                self._settings["model"] = model
                if self._settings["mode"] == "both":
                    return await self.async_step_tts()
                return self._finish()
            errors["base"] = "invalid_model"
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required("model", default=self._settings.get("model", "")): choice(
                        self._stt_models
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_tts(self, user_input=None):
        if self._settings.get("provider") == "xai":
            self._settings["tts_model"] = "xai-tts"  # Internal ID, never sent to xAI.
            self._settings["voices"] = list(self._tts_catalog.voices_for("xai-tts"))
            self._settings.setdefault("voice", "eve")
            return await self.async_step_voice()
        errors = {}
        if user_input is not None:
            model = user_input["tts_model"].strip()
            if model:
                old_model = self._settings.get("tts_model")
                old_voices = self._settings.get("voices", [])
                self._settings["tts_model"] = model
                self._settings["voices"] = list(self._tts_catalog.voices_for(model))
                if (
                    model not in self._tts_catalog.model_voices
                    and not self._tts_catalog.provider_voices
                ):
                    self._settings["voices"] = old_voices if old_model == model else []
                if old_model != model:
                    self._settings.pop("voice", None)
                return await self.async_step_voice()
            errors["base"] = "invalid_model"
        return self.async_show_form(
            step_id="tts",
            data_schema=vol.Schema(
                {
                    vol.Required("tts_model", default=self._settings.get("tts_model", "")): choice(
                        self._tts_models
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_voice(self, user_input=None):
        errors = {}
        if user_input is not None:
            voice = user_input["voice"].strip()
            if voice:
                self._settings["voice"] = voice
                return self._finish()
            errors["base"] = "invalid_voice"
        voices = self._settings.get("voices", [])
        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Required("voice", default=self._settings.get("voice", "")): choice(
                        {v: v for v in voices}
                    ),
                }
            ),
            errors=errors,
        )

    def _clean_settings(self):
        return clean_settings(self._settings)


class ConfigFlow(VoiceFlow, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._initialize()

    async def async_step_user(self, user_input=None):
        return await self._selection("user", user_input)

    def _finish(self):
        return self.async_create_entry(title="HA Universal Voice", data=self._clean_settings())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow(config_entry)


class OptionsFlow(VoiceFlow, config_entries.OptionsFlow):
    def __init__(self, entry):
        settings = settings_for(entry)
        settings.setdefault("mode", mode_for(settings))
        settings.setdefault("provider", "openrouter")
        self._initialize(settings)

    async def async_step_init(self, user_input=None):
        return await self._selection("init", user_input)

    def _finish(self):
        return self.async_create_entry(title="", data=self._clean_settings())
