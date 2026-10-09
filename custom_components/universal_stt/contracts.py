"""Pure contracts shared by settings, providers, transport, and HA consumers."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit

Provider = Literal["openrouter", "openai", "xai", "gemini", "custom"]
VoiceMode = Literal["stt", "tts", "both"]
VoiceFeature = Literal["stt", "tts"]
CatalogSource = Literal["live", "documented", "manual"]
Authentication = Literal["bearer", "google"]


def _validated_url(value: str, *, base: bool) -> str:
    """Reject ambiguous destinations before URL parsing can discard control characters."""
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Use an HTTP(S) URL without whitespace or control characters")
    try:
        parts = urlsplit(value)
        port = parts.port
        valid = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and "#" not in value
            and (not base or "?" not in value)
            and (port is None or port > 0)
            and "\\" not in parts.netloc
        )
    except ValueError:
        raise ValueError("Use a valid HTTP(S) URL without embedded credentials") from None
    if not valid:
        raise ValueError("Use an HTTP(S) URL without credentials, fragment, or a base query")
    return value.rstrip("/") if base else value


def normalize_base_url(value: str) -> str:
    """Allow local HTTP servers, but no query on an API root."""
    return _validated_url(value, base=True)


def normalize_endpoint_url(value: str) -> str:
    """Accept a complete inference or catalog endpoint including its query."""
    return _validated_url(value, base=False)


def same_origin(first: str, second: str) -> bool:
    """Compare validated scheme, host, and effective port before sharing credentials."""

    def origin(value: str) -> tuple[str, str, int]:
        parts = urlsplit(normalize_endpoint_url(value))
        return (
            parts.scheme,
            parts.hostname,
            parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80),
        )

    return origin(first) == origin(second)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Validated destination and effective credential; never includes secrets in repr."""

    url: str = field(repr=False)
    api_key: str = field(default="", repr=False)
    authentication: Authentication = "bearer"

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", normalize_endpoint_url(self.url))
        if self.authentication not in {"bearer", "google"}:
            raise ValueError("Unsupported authentication scheme")
        if not isinstance(self.api_key, str) or any(
            ord(char) < 32 or ord(char) == 127 for char in self.api_key
        ):
            raise ValueError("Invalid API key")

    @classmethod
    def resolve(
        cls,
        url: str,
        base_url: str,
        shared_api_key: str = "",
        api_key: str = "",
        authentication: Authentication = "bearer",
    ) -> "Endpoint":
        """A dedicated key wins; the shared key is restricted to the base origin."""
        url = normalize_endpoint_url(url)
        base_url = normalize_base_url(base_url)
        key = api_key or (shared_api_key if same_origin(base_url, url) else "")
        return cls(url, key, authentication)

    @property
    def headers(self) -> dict[str, str]:
        """Return fresh headers so callers cannot mutate another endpoint's policy."""
        if not self.api_key:
            return {}
        if self.authentication == "google":
            return {"x-goog-api-key": self.api_key}
        return {"Authorization": f"Bearer {self.api_key}"}


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Discovery choices with explicit voice scope and provenance, never capabilities."""

    models: Mapping[str, str] = field(default_factory=dict)
    model_voices: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    provider_voices: tuple[str, ...] = ()
    models_source: CatalogSource = "manual"
    voices_source: CatalogSource = "manual"

    def __post_init__(self) -> None:
        sources = {"live", "documented", "manual"}
        if self.models_source not in sources or self.voices_source not in sources:
            raise ValueError("Invalid catalog source")
        object.__setattr__(self, "models", MappingProxyType(dict(self.models)))
        object.__setattr__(
            self,
            "model_voices",
            MappingProxyType({model: tuple(voices) for model, voices in self.model_voices.items()}),
        )
        object.__setattr__(self, "provider_voices", tuple(self.provider_voices))

    def voices_for(self, model: str) -> tuple[str, ...]:
        """A model-scoped list, including an empty list, takes precedence."""
        return self.model_voices.get(model, self.provider_voices)


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    """Request-local audio and extension, independent of a shared client default."""

    extension: str
    data: bytes


class AudioStream(Protocol):
    """Lazy byte output owned by its entry until explicitly closed or unloaded.

    Fixed-format HTTP starts on first iteration; dynamic output can prepare first.
    aclose is idempotent and concurrent calls share cleanup. Consumers must close
    in finally; breaking iteration alone
    does not promise resource release.
    """

    extension: str

    def __aiter__(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class VoiceClient(Protocol):
    """Compatibility facade consumed by the existing HA entities."""

    audio_format: str

    async def transcribe(self, wav: bytes, model: str, language: str) -> str: ...

    async def synthesize(
        self, text: str, model: str, voice: str, language: str = "auto"
    ) -> bytes: ...

    async def synthesize_audio(
        self, text: str, model: str, voice: str, language: str = "auto"
    ) -> SynthesizedAudio: ...
