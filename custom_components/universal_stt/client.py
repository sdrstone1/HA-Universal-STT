"""OpenAI-compatible audio provider and static provider composition."""

import aiohttp

from .catalog import compatible_catalog, custom_catalog
from .const import MAX_TTS_AUDIO_BYTES, MAX_TTS_TEXT_BYTES, PROVIDER_URLS  # noqa: F401
from .contracts import Endpoint, SynthesizedAudio, normalize_base_url, same_origin  # noqa: F401
from .contracts import normalize_endpoint_url as normalize_catalog_url  # noqa: F401
from .errors import AuthenticationError, STTError  # noqa: F401

MP3_TYPES = frozenset({"audio/mpeg", "audio/mp3", "application/octet-stream"})


def validate_speech(text, model, voice):
    """Validate before network acquisition; never include input contents in errors."""
    if any(not isinstance(value, str) or not value.strip() for value in (text, model, voice)):
        raise STTError("Text, model, and voice must not be empty")
    if len(text.encode("utf-8")) > MAX_TTS_TEXT_BYTES:
        raise STTError("Speech text exceeds 64 KiB")


class AudioResponseStream:
    """Attach a format to the transport's lazy, concurrently closable byte stream."""

    extension = "mp3"

    def __init__(self, stream):
        self._stream = stream

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await anext(self._stream)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        await self._stream.aclose()


class STTClient:
    """OpenRouter, OpenAI, and custom servers share compatible audio payloads."""

    audio_format = "mp3"

    def __init__(self, transport, settings):
        self.transport = transport
        self.settings = settings
        self.audio_formats = None

    async def discover_custom_models(self, endpoint: Endpoint):
        return custom_catalog(await self.transport.request_json("GET", endpoint))

    async def discover_models(self, modality="transcription"):
        if modality not in {"transcription", "speech"}:
            raise ValueError("Invalid audio modality")
        settings = self.settings
        endpoint = Endpoint(f"{normalize_base_url(settings.base_url)}/models", settings.api_key)
        kwargs = (
            {"params": {"output_modalities": modality}} if settings.provider == "openrouter" else {}
        )
        payload = await self.transport.request_json("GET", endpoint, **kwargs)
        return compatible_catalog(payload, settings.provider, modality)

    def speech_body(self, text, model, voice, language):
        body = {"model": model, "input": text, "voice": voice}
        if self.settings.provider == "openrouter":
            if self.audio_formats is None:
                raise STTError("OpenRouter audio format configuration is not loaded")
            body["response_format"] = self.audio_formats.request_format_for(model)
        else:
            body["response_format"] = "mp3"
        return body

    def synthesize_stream(self, text, model, voice, language="auto"):
        validate_speech(text, model, voice)
        response = self.transport.stream(
            "POST",
            self.settings.inference_endpoint("tts"),
            max_bytes=MAX_TTS_AUDIO_BYTES,
            content_types=None if self.settings.provider == "openrouter" else MP3_TYPES,
            log_audio_format=self.settings.provider == "openrouter",
            json=self.speech_body(text, model, voice, language),
        )
        if self.settings.provider == "openrouter":
            from .openrouter_audio import OpenRouterAudioStream

            return OpenRouterAudioStream(response, model, self.audio_formats)
        return AudioResponseStream(response)

    async def synthesize_audio(self, text, model, voice, language="auto"):
        """Expose detected formats without mutating the compatibility default."""
        if self.settings.provider == "openrouter":
            return await self.synthesize_stream(text, model, voice, language).collect()
        return SynthesizedAudio(
            self.audio_format, await self.synthesize(text, model, voice, language)
        )

    async def synthesize(self, text, model, voice, language="auto"):
        if self.settings.provider == "openrouter":
            return (await self.synthesize_audio(text, model, voice, language)).data
        stream = self.synthesize_stream(text, model, voice, language)
        try:
            result = bytearray()
            async for chunk in stream:
                result.extend(chunk)
            return bytes(result)
        finally:
            await stream.aclose()

    async def transcribe(self, wav, model, language):
        form = aiohttp.FormData()
        form.add_field("model", model)
        form.add_field("language", language)
        form.add_field("response_format", "json")
        form.add_field("file", wav, filename="speech.wav", content_type="audio/wav")
        payload = await self.transport.request_json(
            "POST", self.settings.inference_endpoint("stt"), data=form
        )
        text = payload.get("text")
        if not isinstance(text, str):
            raise STTError("Service response has no transcript")
        return text.strip()


def create_voice_client(transport, settings):
    """The same explicit composition is used by options discovery and entry setup."""
    if settings.provider == "gemini":
        from .gemini import GeminiClient

        return GeminiClient(transport, settings)
    if settings.provider == "xai":
        from .xai import XAIClient

        return XAIClient(transport, settings)
    return STTClient(transport, settings)
