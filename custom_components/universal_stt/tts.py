"""Text-to-speech engine for Assist and tts.speak."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from types import TracebackType
from uuid import uuid4

from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    Voice,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import AUDIO_COLLECTION_TIMEOUT, MAX_TTS_TEXT_BYTES
from .contracts import SynthesizedAudio
from .errors import safe_failure_detail
from .languages import PIPELINE_LANGUAGES
from .settings import settings_for

_LOGGER = logging.getLogger(__name__)

# Published xAI TTS locales; other providers do not expose a common language catalog.
XAI_TTS_LANGUAGES = (
    "en",
    "ar-EG",
    "ar-SA",
    "ar-AE",
    "bn",
    "zh",
    "fr",
    "de",
    "hi",
    "id",
    "it",
    "ja",
    "ko",
    "pt-BR",
    "pt-PT",
    "ru",
    "es-MX",
    "es-ES",
    "tr",
    "vi",
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([UniversalTTS(entry, hass.config.language)])


class UniversalTTS(TextToSpeechEntity):
    """Bound input text and return complete or streamed audio for HA playback."""

    def __init__(self, entry, default_language):
        settings = settings_for(entry)
        self._client = entry.runtime_data
        self._model = settings["tts_model"]
        self._voice = settings["voice"]
        self._streaming = settings.get("tts_streaming", False)
        self._connection_revision = uuid4().hex
        self._connection_scope_option = f"connection_scope_{self._connection_revision}"
        self._voices = list(dict.fromkeys([self._voice, *settings.get("voices", [])]))
        is_xai = settings.get("provider") == "xai"
        self._languages = XAI_TTS_LANGUAGES if is_xai else PIPELINE_LANGUAGES
        language = default_language.replace("_", "-")
        if language not in self._languages:
            primary = language.split("-")[0].lower()
            language = next((v for v in self._languages if v.split("-")[0] == primary), "en")
        self._language = language
        model_name = "xAI Text to Speech" if is_xai else self._model
        self._attr_name = f"HA Universal Voice TTS ({model_name})"
        self._attr_unique_id = f"{entry.entry_id}_tts"

    @property
    def supported_languages(self):
        return list(self._languages)

    @property
    def default_language(self):
        return self._language

    @property
    def supported_options(self):
        return ["voice", "model", "connection_revision", self._connection_scope_option]

    @property
    def default_options(self):
        # A new entity instance intentionally misses the previous connection's cache.
        # HA checks option keys before cache lookup; an old revision value alone
        # cannot recreate a previous instance's cache namespace.
        return {
            "voice": self._voice,
            "model": self._model,
            "connection_revision": self._connection_revision,
            self._connection_scope_option: True,
        }

    @callback
    def async_get_supported_voices(self, language):
        return [Voice(voice_id=v, name=v) for v in self._voices]

    def _request_voice(self, language, options):
        if options is None:
            options = {}
        if not isinstance(options, Mapping):
            raise HomeAssistantError("Invalid TTS options")
        voice = options.get("voice", self._voice)
        if language not in self._languages or not isinstance(voice, str) or not voice.strip():
            raise HomeAssistantError("Invalid TTS language or voice")
        if options.get("model", self._model) != self._model:
            raise HomeAssistantError("TTS model does not match the configured model")
        if (
            options.get("connection_revision", self._connection_revision)
            != self._connection_revision
        ):
            raise HomeAssistantError("TTS connection revision is no longer current")
        if options.get(self._connection_scope_option, True) is not True:
            raise HomeAssistantError("TTS connection scope is no longer current")
        return voice

    @staticmethod
    def _text_size(message):
        if not isinstance(message, str):
            raise HomeAssistantError("TTS text must be a string")
        if len(message) > MAX_TTS_TEXT_BYTES:
            raise HomeAssistantError("TTS text exceeds 64 KiB")
        try:
            size = len(message.encode("utf-8"))
        except UnicodeEncodeError:
            raise HomeAssistantError("TTS text is not valid UTF-8") from None
        if size > MAX_TTS_TEXT_BYTES:
            raise HomeAssistantError("TTS text exceeds 64 KiB")
        return size

    @classmethod
    def _validate_message(cls, message):
        cls._text_size(message)
        if not message.strip():
            raise HomeAssistantError("TTS text must not be empty")

    async def _collect_message(self, message_gen):
        """Limit input collection, then await the upstream generator's own cleanup.

        The 130-second collection limit does not bound upstream finally cleanup.
        Cleanup stays in the caller task, and caller cancellation is propagated.
        """
        text = bytearray()
        size = 0
        try:
            async with asyncio.timeout(AUDIO_COLLECTION_TIMEOUT):
                async for part in message_gen:
                    size += self._text_size(part)
                    if size > MAX_TTS_TEXT_BYTES:
                        raise HomeAssistantError("TTS text exceeds 64 KiB")
                    text.extend(part.encode("utf-8"))
                    # Immediate (including empty) chunks must not starve timeout/cancel.
                    await asyncio.sleep(0)
                message = text.decode("utf-8")
                self._validate_message(message)
                return message
        finally:
            close = getattr(message_gen, "aclose", None)
            if close is not None:
                await close()

    @callback
    def async_supports_streaming_input(self):
        # HA must use our bounded input collector even when output streaming is off.
        return True

    async def _synthesize_audio(self, message, voice, language):
        method = getattr(self._client, "synthesize_audio", None)
        if method is not None:
            return await method(message, self._model, voice, language=language)
        return SynthesizedAudio(
            self._client.audio_format,
            await self._client.synthesize(message, self._model, voice, language=language),
        )

    async def async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse:
        try:
            message = await self._collect_message(request.message_gen)
            voice = self._request_voice(request.language, request.options)
            if not self._streaming:
                audio = await self._synthesize_audio(message, voice, request.language)

                async def complete_audio():
                    yield audio.data

                return TTSAudioResponse(audio.extension, complete_audio())
            if getattr(self._client, "requires_audio_prepare", False):
                stream = await self._client.prepare_synthesize_stream(
                    message, self._model, voice, language=request.language
                )
                # Return the closable iterator directly: an unstarted wrapper
                # generator would never run its finally when HA closes it.
                return TTSAudioResponse(stream.extension, TTSAudioIterator(stream=stream))
            return TTSAudioResponse(
                self._client.audio_format,
                TTSAudioIterator(
                    create_stream=lambda: self._client.synthesize_stream(
                        message, self._model, voice, language=request.language
                    )
                ),
            )
        except Exception as err:
            _LOGGER.warning("TTS request failed (%s)", safe_failure_detail(err))
            raise HomeAssistantError("Unable to generate TTS audio") from None

    async def async_get_tts_audio(self, message, language, options):
        try:
            self._validate_message(message)
            voice = self._request_voice(language, options)
            audio = await self._synthesize_audio(message, voice, language)
        except Exception as err:
            _LOGGER.warning("TTS request failed (%s)", safe_failure_detail(err))
            return None, None
        return audio.extension, audio.data


class TTSAudioIterator(AsyncGenerator[bytes, None]):
    """Provide HA's AsyncGenerator contract and close prepared output before first pull."""

    def __init__(self, *, stream=None, create_stream=None):
        self._stream = stream
        self._create_stream = create_stream
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        try:
            if self._stream is None:
                self._stream = self._create_stream()
            return await anext(self._stream)
        except (StopAsyncIteration, asyncio.CancelledError):
            await self.aclose()
            raise
        except Exception as err:
            await self.aclose()
            _LOGGER.warning("TTS stream failed (%s)", safe_failure_detail(err))
            raise HomeAssistantError("Unable to stream TTS audio") from None

    async def asend(self, value):
        if value is not None:
            raise TypeError("TTS audio generators accept only None")
        return await self.__anext__()

    async def athrow(self, exception, value=None, traceback=None):
        if isinstance(exception, BaseException):
            if value is not None:
                raise TypeError("Exception instances do not accept a separate value")
            error = exception
        elif isinstance(exception, type) and issubclass(exception, BaseException):
            if isinstance(value, exception):
                error = value
            elif value is None:
                error = exception()
            elif isinstance(value, tuple):
                error = exception(*value)
            else:
                error = exception(value)
        else:
            raise TypeError("athrow requires an exception instance or class")
        if traceback is not None and not isinstance(traceback, TracebackType):
            raise TypeError("athrow traceback must be a traceback or None")
        await self.aclose()
        if traceback is not None:
            raise error.with_traceback(traceback)
        raise error

    async def aclose(self):
        self._closed = True
        if self._stream is not None:
            await self._stream.aclose()
