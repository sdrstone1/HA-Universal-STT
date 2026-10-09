"""Expose a transcription service to Home Assistant Assist."""

import asyncio
import logging

from homeassistant.components import stt

from .audio import collect_wav
from .const import AUDIO_COLLECTION_TIMEOUT
from .errors import STTError
from .languages import PIPELINE_LANGUAGES
from .settings import settings_for

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Add one STT entity for the selected model."""
    async_add_entities([UniversalSTT(entry)])


class UniversalSTT(stt.SpeechToTextEntity):
    """Buffer a bounded utterance, then send it for transcription."""

    def __init__(self, entry):
        self._client = entry.runtime_data
        self._model = settings_for(entry)["model"]
        self._attr_name = f"HA Universal Voice STT ({self._model})"
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self):
        return list(PIPELINE_LANGUAGES)

    @property
    def supported_formats(self):
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self):
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self):
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self):
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self):
        return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(self, metadata, stream):
        if not self.check_metadata(metadata):
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            async with asyncio.timeout(AUDIO_COLLECTION_TIMEOUT):
                wav = await collect_wav(stream)
            text = await self._client.transcribe(wav, self._model, metadata.language)
        except (STTError, ValueError, TimeoutError) as err:
            _LOGGER.warning("STT request failed (%s)", type(err).__name__)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)
