"""Convert the Assist pipeline's raw PCM stream into a WAV file."""

import asyncio
import io
import wave
from collections.abc import AsyncIterable

from .const import MAX_AUDIO_BYTES


async def collect_wav(stream: AsyncIterable[bytes]) -> bytes:
    """Accept at most two minutes of 16 kHz, mono, signed 16-bit PCM."""
    pcm = bytearray()
    iterator = aiter(stream)
    try:
        async for chunk in iterator:
            if not isinstance(chunk, bytes):
                raise ValueError("Audio chunks must be bytes")
            if len(pcm) + len(chunk) > MAX_AUDIO_BYTES:
                raise ValueError("Audio exceeds the two-minute limit")
            pcm.extend(chunk)
            # An immediately yielding source, including empty chunks, must not
            # starve the collection deadline or caller cancellation.
            await asyncio.sleep(0)
    finally:
        # async-for does not close its iterator on an early exit or cancellation.
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
    if not pcm or len(pcm) % 2:
        raise ValueError("Empty or incomplete PCM audio")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return output.getvalue()
