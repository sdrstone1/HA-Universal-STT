"""Resolve old STT entries and editable voice options without changing IDs."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from typing import Protocol

from .const import OPENROUTER_URL, PROVIDER_URLS
from .contracts import (
    Endpoint,
    Provider,
    VoiceFeature,
    VoiceMode,
    normalize_base_url,
    normalize_endpoint_url,
)


class SettingsEntry(Protocol):
    """Only the configuration snapshots are needed; no HA dependency is required."""

    data: Mapping[str, object]
    options: Mapping[str, object]


def settings_for(entry: SettingsEntry) -> dict[str, object]:
    """Options are a complete snapshot after the first edit."""
    return deepcopy(dict(entry.options or entry.data))


def mode_for(settings: Mapping[str, object]):
    """Existing entries stay STT-only until the user configures TTS."""
    return settings.get("mode", "stt")


def project_legacy_catalogs(settings: Mapping[str, object]) -> dict[str, object]:
    """Project absent feature keys only; explicitly empty values disable fallback."""
    result = deepcopy(dict(settings))
    for feature in ("stt", "tts"):
        for suffix in ("url", "api_key"):
            result.setdefault(f"{feature}_models_{suffix}", result.get(f"models_{suffix}", ""))
    return result


def _text(settings: Mapping[str, object], key: str, default: str = "") -> str:
    value = settings.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    """Detached, immutable typed configuration; credentials are omitted from repr."""

    provider: Provider = "openrouter"
    base_url: str = field(default=OPENROUTER_URL, repr=False)
    api_key: str = field(default="", repr=False)
    mode: VoiceMode = "stt"
    model: str = ""
    tts_model: str = ""
    voice: str = ""
    voices: tuple[str, ...] = ()
    stt_models_url: str = field(default="", repr=False)
    tts_models_url: str = field(default="", repr=False)
    stt_models_api_key: str = field(default="", repr=False)
    tts_models_api_key: str = field(default="", repr=False)
    stt_url: str = field(default="", repr=False)
    tts_url: str = field(default="", repr=False)
    stt_api_key: str = field(default="", repr=False)
    tts_api_key: str = field(default="", repr=False)
    tts_streaming: bool = False

    def __post_init__(self) -> None:
        for definition in fields(self):
            if definition.name not in {"voices", "tts_streaming"} and not isinstance(
                getattr(self, definition.name), str
            ):
                raise ValueError(f"{definition.name} must be a string")
        if self.provider not in {*PROVIDER_URLS, "custom"}:
            raise ValueError("Invalid provider")
        if self.mode not in {"stt", "tts", "both"}:
            raise ValueError("Invalid voice mode")
        if not isinstance(self.tts_streaming, bool):
            raise ValueError("tts_streaming must be a boolean")
        if not isinstance(self.voices, (tuple, list)) or any(
            not isinstance(voice, str) for voice in self.voices
        ):
            raise ValueError("voices must contain string IDs")
        object.__setattr__(self, "voices", tuple(self.voices))

    @classmethod
    def from_entry(cls, entry: SettingsEntry) -> "VoiceSettings":
        """Select options or data without merging deleted settings back into options."""
        return cls.from_mapping(settings_for(entry))

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "VoiceSettings":
        snapshot = project_legacy_catalogs(settings)
        default_base = PROVIDER_URLS.get(_text(snapshot, "provider", "openrouter"), OPENROUTER_URL)
        strings = {
            key: _text(snapshot, key, default)
            for key, default in (
                ("provider", "openrouter"),
                ("base_url", default_base),
                ("api_key", ""),
                ("mode", "stt"),
                ("model", ""),
                ("tts_model", ""),
                ("voice", ""),
                ("stt_models_url", ""),
                ("tts_models_url", ""),
                ("stt_models_api_key", ""),
                ("tts_models_api_key", ""),
                ("stt_url", ""),
                ("tts_url", ""),
                ("stt_api_key", ""),
                ("tts_api_key", ""),
            )
        }
        return cls(
            **strings,
            voices=snapshot.get("voices", ()),
            tts_streaming=snapshot.get("tts_streaming", False),
        )

    def as_dict(self) -> dict[str, object]:
        """Produce an editable independent copy using the existing list storage shape."""
        result = asdict(self)
        result["voices"] = list(self.voices)
        return result

    def enabled(self, feature: VoiceFeature) -> bool:
        if feature not in {"stt", "tts"}:
            raise ValueError("Invalid voice feature")
        return self.mode in {feature, "both"}

    def inference_endpoint(self, feature: VoiceFeature) -> Endpoint:
        """Resolve provider defaults and custom authentication by the same policy."""
        if feature not in {"stt", "tts"}:
            raise ValueError("Invalid voice feature")
        if self.provider == "gemini":
            return Endpoint(
                f"{normalize_base_url(self.base_url)}/interactions", self.api_key, "google"
            )
        path = (
            feature
            if self.provider == "xai"
            else ("audio/transcriptions" if feature == "stt" else "audio/speech")
        )
        url = getattr(self, f"{feature}_url") if self.provider == "custom" else ""
        key = getattr(self, f"{feature}_api_key") if self.provider == "custom" else ""
        return Endpoint.resolve(
            url or f"{normalize_base_url(self.base_url)}/{path}", self.base_url, self.api_key, key
        )

    def catalog_endpoint(self, feature: VoiceFeature) -> Endpoint | None:
        """Only custom catalog URLs are stored; native catalogs are provider-owned."""
        if feature not in {"stt", "tts"}:
            raise ValueError("Invalid voice feature")
        url = getattr(self, f"{feature}_models_url")
        if self.provider != "custom" or not url:
            return None
        return Endpoint.resolve(
            url, self.base_url, self.api_key, getattr(self, f"{feature}_models_api_key")
        )


def _edited_key(
    current: Mapping[str, object], submitted: Mapping[str, object], key: str, preserve: bool
) -> str:
    """Explicit clearing takes precedence even when a replacement was supplied."""
    if submitted.get(f"clear_{key}", False):
        return ""
    replacement = _text(submitted, key)
    return replacement or (_text(current, key) if preserve else "")


class ConnectionURLValidationError(ValueError):
    """Only a submitted, relevant connection URL failed validation."""


def _connection_url(value: str, *, base: bool = False) -> str:
    try:
        return normalize_base_url(value) if base else normalize_endpoint_url(value)
    except ValueError:
        raise ConnectionURLValidationError("Use a valid HTTP(S) connection URL") from None


def _previous_url(value: str, *, base: bool = False) -> str | None:
    """Malformed old destinations cannot retain keys and must not block other services."""
    try:
        return normalize_base_url(value) if base else normalize_endpoint_url(value)
    except ValueError:
        return None


def apply_connection_edit(
    current: Mapping[str, object], submitted: Mapping[str, object]
) -> dict[str, object]:
    """Build a draft without mutating stored data or performing discovery or speech.

    Omitted URL fields retain their values; explicitly blank URLs select manual
    catalogs or default inference endpoints. Blank secrets preserve credentials
    only on the same provider, base URL, and (for dedicated keys) endpoint URL.
    Final cleanup belongs to clean_settings after the flow has completed.
    """
    old = project_legacy_catalogs(current)
    edits = project_legacy_catalogs(submitted)
    provider = _text(submitted, "provider", _text(old, "provider", "openrouter"))
    if provider not in {*PROVIDER_URLS, "custom"}:
        raise ValueError("Invalid provider")
    old_provider = _text(old, "provider", "openrouter")
    old_base = _text(old, "base_url", PROVIDER_URLS.get(old_provider, ""))
    default_base = old_base if provider == old_provider else ""
    base_url = PROVIDER_URLS.get(provider) or _connection_url(
        _text(submitted, "base_url", default_base), base=True
    )
    same_connection = provider == old_provider and base_url == _previous_url(old_base, base=True)
    result = deepcopy(old)
    if not same_connection:
        for key in ("model", "tts_model", "voice", "voices"):
            result.pop(key, None)
    mode = _text(submitted, "mode", _text(old, "mode", "stt" if current else "both"))
    if mode not in {"stt", "tts", "both"}:
        raise ValueError("Invalid voice mode")
    result.update(
        provider=provider,
        base_url=base_url,
        mode=mode,
        api_key=_edited_key(old, submitted, "api_key", same_connection),
    )
    for feature in ("stt", "tts"):
        for suffix in ("models_url", "url"):
            url_field = f"{feature}_{suffix}"
            key_field = f"{feature}_{'models_api_key' if suffix == 'models_url' else 'api_key'}"
            # Legacy submissions may populate absent feature fields, but not overwrite empties.
            supplied = url_field in submitted or (
                suffix == "models_url" and "models_url" in submitted
            )
            if provider != "custom":
                result.update({url_field: "", key_field: ""})
                continue
            if mode not in {feature, "both"}:
                # Keep inactive URLs unvalidated; a new connection must still drop old keys.
                if not same_connection:
                    result[key_field] = ""
                continue
            prior = old if provider == old_provider else {}
            url = _text(edits if supplied else prior, url_field).strip()
            url = _connection_url(url) if url else ""
            old_url = _text(old, url_field).strip()
            old_url = _previous_url(old_url) if old_url else ""
            preserve = same_connection and url == old_url
            key_edits = dict(submitted)
            if suffix == "models_url" and key_field not in submitted:
                if "models_api_key" in submitted:
                    key_edits[key_field] = submitted["models_api_key"]
            key = _edited_key(old, key_edits, key_field, preserve)
            if provider != "custom" or (suffix == "models_url" and not url):
                key = ""
            result.update({url_field: url, key_field: key})
    if "tts_streaming" in submitted:
        if not isinstance(submitted["tts_streaming"], bool):
            raise ValueError("tts_streaming must be a boolean")
        result["tts_streaming"] = submitted["tts_streaming"]
    return result


def clean_settings(settings: Mapping[str, object]) -> dict[str, object]:
    """Create the completed save snapshot; never run this on cancellation or failure."""
    result = project_legacy_catalogs(settings)
    for key in ("language", "models_url", "models_api_key"):
        result.pop(key, None)
    mode = mode_for(result)
    for feature in ("stt", "tts"):
        if result.get("provider") != "custom" or mode not in {feature, "both"}:
            for suffix in ("models_url", "models_api_key", "url", "api_key"):
                result.pop(f"{feature}_{suffix}", None)
    if mode == "stt":
        for key in ("tts_model", "voice", "voices", "tts_streaming"):
            result.pop(key, None)
    elif mode == "tts":
        result.pop("model", None)
    return result
