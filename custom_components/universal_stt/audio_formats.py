"""Validated OpenRouter request formats and PCM metadata defaults."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .errors import ResponseError

FORMAT_CONFIG = Path(__file__).with_name("model_audio_formats.json")


@dataclass(frozen=True, slots=True)
class ModelAudioFormat:
    supported_formats: tuple[str, ...]
    rate: int | None = None
    channels: int | None = None
    request_format: str | None = None


@dataclass(frozen=True, slots=True)
class AudioFormatConfig(Mapping):
    default_request_format: str
    models: Mapping

    def __getitem__(self, key):
        return self.models[key]

    def __iter__(self):
        return iter(self.models)

    def __len__(self):
        return len(self.models)

    def request_format_for(self, model):
        rule = self.get(model)
        return (rule.request_format if rule else None) or self.default_request_format


def validate_pcm_value(value, name):
    maximum = 192000 if name == "rate" else 8
    minimum = 8000 if name == "rate" else 1
    if type(value) is not int or not minimum <= value <= maximum:
        raise ResponseError("Invalid PCM audio metadata")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate audio format configuration key")
        result[key] = value
    return result


def load_audio_formats(path=FORMAT_CONFIG):
    """Read off the event loop; supported formats are informational, never a whitelist."""
    try:
        with Path(path).open(encoding="utf-8") as source:
            payload = json.load(source, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or set(payload) != {"version", "defaults", "models"}:
            raise ValueError
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError
        if not isinstance(payload["models"], dict):
            raise ValueError
        defaults = payload["defaults"]
        if not isinstance(defaults, dict) or set(defaults) != {"request_format"}:
            raise ValueError
        default_format = defaults["request_format"]
        if not isinstance(default_format, str) or default_format not in {"mp3", "wav", "pcm"}:
            raise ValueError
        models = {}
        for model, rule in payload["models"].items():
            if not isinstance(model, str) or not model.strip() or model != model.strip():
                raise ValueError
            if not isinstance(rule, dict) or set(rule) - {
                "supported_formats",
                "request_format",
                "pcm",
                "source",
            }:
                raise ValueError
            formats = rule.get("supported_formats")
            if (
                not isinstance(formats, list)
                or not formats
                or any(
                    type(item) is not str or item not in {"mp3", "wav", "pcm"} for item in formats
                )
                or len(formats) != len(set(formats))
            ):
                raise ValueError
            source = rule.get("source")
            if not isinstance(source, str) or not source.startswith("https://"):
                raise ValueError
            request_format = rule.get("request_format")
            if "request_format" in rule and (
                not isinstance(request_format, str) or request_format not in formats
            ):
                raise ValueError
            if (request_format or default_format) not in formats:
                raise ValueError
            rate = channels = None
            if "pcm" in rule:
                pcm = rule["pcm"]
                if not isinstance(pcm, dict) or set(pcm) != {"rate", "channels"}:
                    raise ValueError
                rate = validate_pcm_value(pcm["rate"], "rate")
                channels = validate_pcm_value(pcm["channels"], "channels")
            models[model] = ModelAudioFormat(tuple(formats), rate, channels, request_format)
        return AudioFormatConfig(default_format, MappingProxyType(models))
    except (OSError, ValueError, TypeError, RecursionError, ResponseError):
        raise ResponseError("Invalid model audio format configuration") from None
