"""Request-local OpenRouter response detection and progressive PCM/WAV output."""

import asyncio
import logging

from .audio_formats import validate_pcm_value
from .const import MAX_TTS_AUDIO_BYTES
from .contracts import SynthesizedAudio
from .errors import FailureCategory, FailureDiagnostic, FailurePhase, ResponseError, STTError
from .pcm_audio import PCMFrames, wav_header

MP3_TYPES = {"audio/mpeg", "audio/mp3"}
WAV_TYPES = {"audio/wav", "audio/x-wav", "audio/wave"}
PREFIX_SIZE = 12
_LOGGER = logging.getLogger(__name__)


def _metadata(header):
    if len(header) > 1024:
        raise ResponseError("Invalid audio response metadata")
    parts = header.split(";")
    mime = parts[0].strip().lower()
    params = {}
    for part in parts[1:]:
        key, separator, value = part.strip().partition("=")
        key = key.lower()
        if not separator or not key or key in params:
            raise ResponseError("Invalid audio response metadata")
        params[key] = value.strip().strip('"')
    return mime, params


def _signature(prefix):
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
        return "wav"
    if prefix[:3] == b"ID3":
        return "mp3"
    if len(prefix) >= 4:
        # MPEG audio frame: sync, nonreserved version/layer/rate and real bitrate.
        if (
            prefix[0] == 255
            and prefix[1] & 224 == 224
            and prefix[1] & 24 != 8
            and prefix[1] & 6 != 0
            and prefix[2] & 240 not in {0, 240}
            and prefix[2] & 12 != 12
        ):
            return "mp3"
    return None


def _pcm_parameter(params, key, fallback):
    if key in params:
        value = params[key]
        if not value.isascii() or not value.isdecimal() or len(value) > 6:
            raise ResponseError("Invalid PCM audio metadata")
        return validate_pcm_value(int(value), key)
    if fallback is None:
        raise ResponseError("PCM response is missing rate or channels metadata")
    return validate_pcm_value(fallback, key)


def _log_pcm_metadata(params):
    """Log only validated numbers or fixed states, never raw header values."""
    values = {}
    for key in ("rate", "channels"):
        if key not in params:
            values[key] = "missing"
            continue
        try:
            values[key] = _pcm_parameter(params, key, None)
        except ResponseError:
            values[key] = "invalid"
    _LOGGER.warning(
        "OpenRouter PCM response metadata (rate=%s channels=%s source=response_header)",
        values["rate"],
        values["channels"],
    )


class OpenRouterAudioStream:
    """Prepare at most twelve prefix bytes, then return this closable iterator itself.

    The transport deadline starts on preparation and covers every later read.
    A deadline timer also releases an acquired response if output is never consumed.
    """

    def __init__(self, stream, model, formats):
        self._stream = stream
        self._model = model
        self._formats = formats
        self.extension = ""
        self._prefix = b""
        self._pcm = None
        self._rate = self._channels = None
        self._header_sent = False
        self._prepared = False
        self._closed = False
        self._expired = False
        self._pending = None
        self._cleanup = None
        self._expiry = None

    @property
    def deadline(self):
        return self._stream.deadline

    def __aiter__(self):
        return self

    def _expire(self):
        self._expired = True
        self._closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish_close())

    async def prepare(self):
        if self._closed:
            raise ResponseError("Audio stream is closed")
        if self._prepared:
            return self
        if self._pending is not None:
            raise RuntimeError("Audio stream already has a pending consumer")
        try:
            self._pending = asyncio.create_task(self._prepare())
            await self._pending
            self._prepared = True
            self._expiry = asyncio.get_running_loop().call_at(self.deadline, self._expire)
            return self
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pending = None

    async def _prepare(self):
        prefix = bytearray()
        while len(prefix) < PREFIX_SIZE:
            try:
                prefix.extend(await self._stream.read_chunk(PREFIX_SIZE - len(prefix)))
            except StopAsyncIteration:
                break
            mime, _ = _metadata(self._stream.content_type_header)
            # Explicit PCM needs one channel frame, not a full file or prefix.
            if mime == "audio/pcm":
                break
            if _signature(prefix) == "mp3":
                break
        self._prefix = bytes(prefix)
        mime, params = _metadata(self._stream.content_type_header)
        observed = _signature(self._prefix)
        if mime in MP3_TYPES:
            if observed != "mp3":
                raise ResponseError("MP3 response has an invalid audio signature")
            self.extension = "mp3"
        elif mime in WAV_TYPES:
            if observed != "wav":
                raise ResponseError("WAV response has an invalid audio signature")
            self.extension = "wav"
        elif mime == "audio/pcm":
            _log_pcm_metadata(params)
            # A recognizable container contradicts the raw PCM media type.
            if observed is not None:
                raise ResponseError("PCM response contains a different audio format")
            rule = self._formats.get(self._model) if self._formats else None
            self._rate = _pcm_parameter(params, "rate", rule.rate if rule else None)
            self._channels = _pcm_parameter(params, "channels", rule.channels if rule else None)
            if any(key in params for key in ("bits", "bitdepth", "encoding", "endianness")):
                allowed = {
                    "bits": "16",
                    "bitdepth": "16",
                    "encoding": "s16le",
                    "endianness": "little",
                }
                if any(
                    params[key].lower() != value for key, value in allowed.items() if key in params
                ):
                    raise ResponseError("Unsupported PCM encoding")
            self._pcm = PCMFrames(self._channels)
            self.extension = "wav"
        elif mime in {"", "application/octet-stream"} and observed is not None:
            self.extension = observed
        else:
            raise ResponseError("Unsupported or unidentified audio response format")
        if not self._prefix:
            raise ResponseError("Service returned empty audio")

    async def __anext__(self):
        if self._expired:
            raise STTError(
                "Audio response deadline exceeded",
                diagnostic=FailureDiagnostic(FailureCategory.TIMEOUT, FailurePhase.READ),
            )
        if self._closed:
            raise StopAsyncIteration
        if not self._prepared:
            await self.prepare()
        if self._pending is not None:
            raise RuntimeError("Audio stream already has a pending consumer")
        try:
            self._pending = asyncio.create_task(self._next())
            return await self._pending
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pending = None

    async def _next(self):
        if self._pcm is not None and not self._header_sent:
            self._header_sent = True
            return wav_header(self._rate, self._channels)
        while True:
            if self._prefix:
                chunk, self._prefix = self._prefix, b""
            else:
                try:
                    chunk = await anext(self._stream)
                except StopAsyncIteration:
                    if self._pcm is not None:
                        self._pcm.finish()
                    raise
            if self._pcm is None:
                return chunk
            frames = self._pcm.feed(chunk)
            if self._pcm.size + 44 > MAX_TTS_AUDIO_BYTES:
                raise ResponseError("WAV audio exceeds byte limit")
            if frames:
                return frames

    async def collect(self):
        await self.prepare()
        data = bytearray()
        try:
            async for chunk in self:
                data.extend(chunk)
            if self._pcm is not None:
                data[:44] = wav_header(self._rate, self._channels, len(data) - 44)
            return SynthesizedAudio(self.extension, bytes(data))
        finally:
            await self.aclose()

    async def aclose(self):
        self._closed = True
        if self._expiry is not None:
            self._expiry.cancel()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._cleanup)

    async def _finish_close(self):
        await self._stream.aclose()
        pending = self._pending
        if pending is not None and pending is not asyncio.current_task():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
