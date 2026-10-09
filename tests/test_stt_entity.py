"""Verify STT audio bounds, cleanup, and entity contracts with HA substitutes."""

import asyncio
import importlib
import io
import sys
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

package = types.ModuleType("stt_entity_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
audio = importlib.import_module("stt_entity_test_package.audio")
const = importlib.import_module("stt_entity_test_package.const")


class SpeechToTextEntity:
    """Substitute only HA's advertised-capability metadata validation."""

    def check_metadata(self, metadata):
        return all(
            getattr(metadata, field) in getattr(self, capability)
            for field, capability in (
                ("language", "supported_languages"),
                ("format", "supported_formats"),
                ("codec", "supported_codecs"),
                ("bit_rate", "supported_bit_rates"),
                ("sample_rate", "supported_sample_rates"),
                ("channel", "supported_channels"),
            )
        )


def load_entity_module():
    stt = types.ModuleType("homeassistant.components.stt")
    stt.SpeechToTextEntity = SpeechToTextEntity
    stt.SpeechResult = lambda text, state: (text, state)
    stt.SpeechResultState = types.SimpleNamespace(SUCCESS="success", ERROR="error")
    stt.AudioFormats = types.SimpleNamespace(WAV="wav")
    stt.AudioCodecs = types.SimpleNamespace(PCM="pcm")
    stt.AudioBitRates = types.SimpleNamespace(BITRATE_16=16)
    stt.AudioSampleRates = types.SimpleNamespace(SAMPLERATE_16000=16000)
    stt.AudioChannels = types.SimpleNamespace(CHANNEL_MONO=1)
    components = types.ModuleType("homeassistant.components")
    components.stt = stt
    with patch.dict(
        sys.modules,
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.components": components,
            "homeassistant.components.stt": stt,
        },
    ):
        return importlib.import_module("stt_entity_test_package.stt")


def metadata(**changes):
    fields = dict(
        language="ko", format="wav", codec="pcm", bit_rate=16, sample_rate=16000, channel=1
    )
    fields.update(changes)
    return types.SimpleNamespace(**fields)


async def chunks(*values):
    for value in values:
        yield value


class STTEntityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_entity_module()
        self.client = types.SimpleNamespace(transcribe=AsyncMock(return_value="transcript"))
        self.entry = types.SimpleNamespace(
            data={"model": "legacy-model", "language": "en"},
            options={"model": "configured-model"},
            runtime_data=self.client,
            entry_id="existing-entry-id",
        )
        self.entity = self.module.UniversalSTT(self.entry)

    def assert_wav(self, payload, pcm):
        with wave.open(io.BytesIO(payload), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), len(pcm) // 2)
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)

    async def process_error(self, source, request_metadata=None):
        with self.assertLogs(self.module.__name__, level="WARNING"):
            result = await self.entity.async_process_audio_stream(
                request_metadata or metadata(), source
            )
        self.assertEqual(result, (None, "error"))
        self.client.transcribe.assert_not_awaited()

    async def test_setup_preserves_existing_unique_id_and_options_model(self):
        add = Mock()
        await self.module.async_setup_entry(None, self.entry, add)
        entity = add.call_args.args[0][0]
        self.assertEqual(entity._attr_unique_id, "existing-entry-id")
        self.assertIn("configured-model", entity._attr_name)
        self.assertEqual(
            await entity.async_process_audio_stream(metadata(), chunks(b"\x01\x02")),
            ("transcript", "success"),
        )
        wav, model, language = self.client.transcribe.call_args.args
        self.assertEqual((model, language), ("configured-model", "ko"))
        self.assert_wav(wav, b"\x01\x02")

    async def test_each_invalid_metadata_field_rejects_before_read_or_request(self):
        for field, value in (
            ("format", "mp3"),
            ("codec", "opus"),
            ("channel", 2),
            ("sample_rate", 48000),
            ("bit_rate", 8),
            ("language", "invalid-language"),
        ):
            with self.subTest(field=field):
                source = types.SimpleNamespace(__aiter__=AsyncMock())
                result = await self.entity.async_process_audio_stream(
                    metadata(**{field: value}), source
                )
                self.assertEqual(result, (None, "error"))
                source.__aiter__.assert_not_called()
                self.client.transcribe.assert_not_awaited()

    async def test_exact_two_minute_limit_is_complete_wav(self):
        pcm = b"\x01\x02" * (const.MAX_AUDIO_BYTES // 2)
        result = await self.entity.async_process_audio_stream(
            metadata(), chunks(pcm[:1], b"", pcm[1:])
        )
        self.assertEqual(result, ("transcript", "success"))
        self.assert_wav(self.client.transcribe.call_args.args[0], pcm)

    async def test_limit_plus_one_is_rejected_without_reading_next_chunk(self):
        closed = []
        continued = []

        async def source():
            try:
                yield b"\x00" * (const.MAX_AUDIO_BYTES + 1)
                continued.append(True)
                yield b"\x00"
            finally:
                closed.append(True)

        await self.process_error(source())
        self.assertEqual(closed, [True])
        self.assertEqual(continued, [])

    async def test_multi_chunk_overflow_is_rejected_instead_of_truncated(self):
        closed = []

        async def source():
            try:
                yield b"\x00" * (const.MAX_AUDIO_BYTES - 2)
                yield b"\x01\x02\x03\x04"
            finally:
                closed.append(True)

        await self.process_error(source())
        self.assertEqual(closed, [True])

    async def test_empty_odd_and_nonbyte_audio_never_reach_provider(self):
        for values in ((), (b"", b""), (b"\x00",), (b"\x00\x00", b"\x00"), ("audio",)):
            with self.subTest(values=values):
                await self.process_error(chunks(*values))

    async def test_alignment_applies_to_total_not_chunk_boundaries(self):
        pcm = b"\x01\x02\x03\x04"
        result = await self.entity.async_process_audio_stream(
            metadata(), chunks(pcm[:1], pcm[1:3], pcm[3:])
        )
        self.assertEqual(result, ("transcript", "success"))
        self.assert_wav(self.client.transcribe.call_args.args[0], pcm)

    async def test_collection_timeout_closes_input_without_provider_call(self):
        closed = asyncio.Event()

        async def source():
            try:
                yield b"\x00\x00"
                await asyncio.Event().wait()
            finally:
                closed.set()

        self.assertEqual(self.module.AUDIO_COLLECTION_TIMEOUT, const.AUDIO_COLLECTION_TIMEOUT)
        with patch.object(self.module, "AUDIO_COLLECTION_TIMEOUT", 0.01):
            await asyncio.wait_for(self.process_error(source()), 1)
        self.assertTrue(closed.is_set())

    async def test_cancellation_during_collection_propagates_and_closes_input(self):
        entered = asyncio.Event()
        closed = asyncio.Event()

        async def source():
            try:
                yield b"\x00\x00"
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        task = asyncio.create_task(self.entity.async_process_audio_stream(metadata(), source()))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(closed.is_set())
        self.client.transcribe.assert_not_awaited()

    async def test_immediate_empty_chunk_loop_times_out_and_closes_input(self):
        closed = asyncio.Event()

        async def source():
            try:
                while True:
                    yield b""
            finally:
                closed.set()

        with patch.object(self.module, "AUDIO_COLLECTION_TIMEOUT", 0.01):
            await asyncio.wait_for(self.process_error(source()), 1)
        self.assertTrue(closed.is_set())

    async def test_cancellation_during_transcription_propagates(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def transcribe(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.client.transcribe.side_effect = transcribe
        task = asyncio.create_task(
            self.entity.async_process_audio_stream(metadata(), chunks(b"\x00\x00"))
        )
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())

    async def test_failure_logs_only_type_and_returns_no_transcript(self):
        sensitive = "private transcript api_key=private audio data"
        for error in (self.module.STTError(sensitive), TimeoutError(sensitive)):
            with self.subTest(error=type(error).__name__):
                self.client.transcribe.side_effect = error
                with self.assertLogs(self.module.__name__, level="WARNING") as logs:
                    result = await self.entity.async_process_audio_stream(
                        metadata(), chunks(b"\x00\x00")
                    )
                self.assertEqual(result, (None, "error"))
                self.assertIn(type(error).__name__, " ".join(logs.output))
                self.assertNotIn(sensitive, " ".join(logs.output))

    async def test_collector_closes_actual_iterator_on_success_and_failure(self):
        for values in ((b"\x00\x00",), (b"\x00" * (const.MAX_AUDIO_BYTES + 1),)):
            with self.subTest(length=len(values[0])):
                iterator = types.SimpleNamespace(aclose=AsyncMock())
                source = chunks(*values)

                class Iterator:
                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        return await anext(source)

                    async def aclose(self):
                        await iterator.aclose()
                        await source.aclose()

                class Iterable:
                    def __aiter__(self):
                        return Iterator()

                if len(values[0]) > const.MAX_AUDIO_BYTES:
                    with self.assertRaises(ValueError):
                        await audio.collect_wav(Iterable())
                else:
                    self.assert_wav(await audio.collect_wav(Iterable()), values[0])
                iterator.aclose.assert_awaited_once()
