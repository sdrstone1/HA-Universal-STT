"""Bounded Gemini Interactions SSE decoding and streaming WAV framing."""

import asyncio
import base64
import binascii
import json
import struct

from .const import MAX_SSE_EVENT_BYTES as MAX_EVENT_BYTES
from .const import MAX_SSE_WIRE_BYTES as MAX_WIRE_BYTES
from .const import MAX_TTS_AUDIO_BYTES as MAX_PCM_BYTES
from .errors import STTError


def wav_stream_header():
    """Use unknown RIFF/data lengths for non-seekable 24 kHz mono s16le audio."""
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        0xFFFFFFFF,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        24000,
        48000,
        2,
        16,
        b"data",
        0xFFFFFFFF,
    )


async def sse_events(content):
    """Parse LF/CRLF event boundaries independently of HTTP chunk boundaries."""
    pending = bytearray()
    data = []
    event_size = total = 0
    async for chunk in content:
        total += len(chunk)
        if total > MAX_WIRE_BYTES:
            raise STTError("Gemini stream exceeds wire limit")
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            event_size += len(line) + 1
            if event_size > MAX_EVENT_BYTES:
                raise STTError("Gemini stream event is too large")
            line = line.removesuffix(b"\r")
            if not line:
                if data:
                    try:
                        event = json.loads(b"\n".join(data))
                    except (ValueError, UnicodeError, RecursionError):
                        raise STTError("Invalid Gemini stream event") from None
                    if not isinstance(event, dict):
                        raise STTError("Invalid Gemini stream event")
                    yield event
                data, event_size = [], 0
            elif line.startswith(b"data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(b" ") else value)
        if len(pending) + event_size > MAX_EVENT_BYTES:
            raise STTError("Gemini stream event is too large")
    if pending or data:
        raise STTError("Truncated Gemini stream event")


async def wav_audio(events):
    """Validate PCM deltas and completion before accepting a successful stream."""
    size = 0
    carry = b""
    started = False
    async for event in events:
        kind = event.get("event_type")
        if kind == "interaction.completed":
            interaction = event.get("interaction")
            if not isinstance(interaction, dict) or interaction.get("status") != "completed":
                raise STTError("Gemini interaction did not complete")
            if not started or carry:
                raise STTError("Gemini returned empty or incomplete PCM audio")
            return
        if kind in {"error", "interaction.error", "interaction.failed"} or (
            kind == "interaction.status_update"
            and event.get("status") in {"failed", "cancelled", "requires_action"}
        ):
            raise STTError("Gemini streaming generation failed")
        if kind != "step.delta":
            continue
        delta = event.get("delta")
        if not isinstance(delta, dict):
            raise STTError("Invalid Gemini stream delta")
        if delta.get("type") != "audio":
            continue
        if (
            delta.get("mime_type", "audio/l16") != "audio/l16"
            or delta.get("sample_rate", 24000) != 24000
            or delta.get("channels", 1) != 1
        ):
            raise STTError("Gemini returned an unexpected audio format")
        encoded = delta.get("data", "")
        if not isinstance(encoded, str):
            raise STTError("Invalid Gemini audio data")
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise STTError("Invalid Gemini audio data") from None
        size += len(pcm)
        if size > MAX_PCM_BYTES:
            raise STTError("Gemini audio exceeds 20 MiB")
        pcm = carry + pcm
        end = len(pcm) - len(pcm) % 2
        carry = pcm[end:]
        if end:
            if not started:
                started = True
                yield wav_stream_header() + pcm[:end]
            else:
                yield pcm[:end]
    raise STTError("Gemini stream ended before completion")


class GeminiAudioStream:
    """Own decoder iterators and join pending pulls before closing generators."""

    extension = "wav"

    def __init__(self, wire):
        self._wire = wire
        self._events = sse_events(wire)
        self._audio = wav_audio(self._events)
        self._pending = None
        self._cleanup = None
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        if self._pending is not None:
            raise RuntimeError("Audio stream already has a pending consumer")
        try:
            self._pending = asyncio.create_task(anext(self._audio))
            return await self._pending
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pending = None

    async def aclose(self):
        self._closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._cleanup)

    async def _finish_close(self):
        # Transport closes its response before cancelling/joining the HTTP pull.
        await self._wire.aclose()
        pending = self._pending
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await self._audio.aclose()
        await self._events.aclose()
