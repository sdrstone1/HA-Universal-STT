"""Home Assistant selectors and forms; no provider requests or storage mutations."""

import voluptuous as vol
from homeassistant.helpers import selector


def choice(values):
    if not values:
        return str
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[{"value": key, "label": label} for key, label in values.items()],
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def secret_field():
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def selection_schema(current):
    """Choose the service first so the next HA form has only relevant fields."""
    return vol.Schema(
        {
            vol.Required(
                "provider", default=current.get("provider", "openai")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "openai", "label": "OpenAI"},
                        {"value": "gemini", "label": "Google Gemini"},
                        {"value": "xai", "label": "xAI (Grok)"},
                        {"value": "openrouter", "label": "OpenRouter"},
                        {"value": "custom", "label": "OpenAI-compatible"},
                    ]
                )
            ),
            vol.Required("mode", default=current.get("mode", "both")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "both", "label": "STT + TTS"},
                        {"value": "stt", "label": "STT"},
                        {"value": "tts", "label": "TTS"},
                    ]
                )
            ),
        }
    )


def connection_schema(current):
    fields = {
        vol.Optional("api_key", default=""): secret_field(),
        vol.Optional("discover", default=True): bool,
    }
    if current.get("api_key"):
        fields[vol.Optional("clear_api_key", default=False)] = bool
    if current.get("mode") in {"tts", "both"}:
        fields[vol.Optional("tts_streaming", default=current.get("tts_streaming", False))] = bool
    if current.get("provider") == "custom":
        fields[vol.Required("base_url", default=current.get("base_url", ""))] = str
        for feature in ("stt", "tts"):
            if current.get("mode") not in {feature, "both"}:
                continue
            for prefix in (f"{feature}_models", feature):
                fields[vol.Optional(f"{prefix}_url", default=current.get(f"{prefix}_url", ""))] = (
                    str
                )
                key = f"{prefix}_api_key"
                fields[vol.Optional(key, default="")] = secret_field()
                if current.get(key):
                    fields[vol.Optional(f"clear_{key}", default=False)] = bool
    return vol.Schema(fields)
