"""Signed 16-bit little-endian PCM framing for complete and progressive WAV."""

import struct

from .audio_formats import validate_pcm_value
from .errors import ResponseError


def wav_header(rate, channels, size=None):
    validate_pcm_value(rate, "rate")
    validate_pcm_value(channels, "channels")
    # FFmpeg accepts the conventional unknown RIFF/data size for progressive audio.
    riff_size, data_size = (0xFFFFFFFF, 0xFFFFFFFF) if size is None else (size + 36, size)
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        rate,
        rate * channels * 2,
        channels * 2,
        16,
        b"data",
        data_size,
    )


class PCMFrames:
    """Retain less than one channel frame between chunks; reject partial final frames."""

    def __init__(self, channels):
        self.frame_size = channels * 2
        self.carry = b""
        self.size = 0

    def feed(self, chunk):
        data = self.carry + chunk
        boundary = len(data) - len(data) % self.frame_size
        self.carry = data[boundary:]
        self.size += boundary
        return data[:boundary]

    def finish(self):
        if self.carry or not self.size:
            raise ResponseError("Empty or incomplete PCM audio frames")
