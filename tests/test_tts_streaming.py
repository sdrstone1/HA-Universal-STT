"""Bound HA message streams and close lazy provider output at the consumer boundary."""

import asyncio
import importlib
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_tts_entity import TTSAudioRequest, load_tts_module


class TTSStreamingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_tts_module()
        self.runtime_module = importlib.import_module("tts_test_package.runtime")
        self.errors = importlib.import_module("tts_test_package.errors")
        self.output_closed = False
        self.input_closed = False
        self.output_started = asyncio.Event()
        self.input_started = asyncio.Event()
        self.release_output = asyncio.Event()
        self.client = types.SimpleNamespace(
            audio_format="mp3",
            synthesize=AsyncMock(return_value=b"ID3complete"),
            synthesize_stream=Mock(side_effect=lambda *args: self.wrap_output(self.output(*args))),
        )
        self.runtime = self.runtime_module.EntryRuntime(types.SimpleNamespace(provider="custom"))
        self.runtime.client = self.client
        self.entry = types.SimpleNamespace(
            entry_id="stable-id",
            runtime_data=self.runtime,
            data={},
            options={"tts_model": "configured", "voice": "Kore", "tts_streaming": True},
        )
        self.entity = self.module.UniversalTTS(self.entry, "ko")

    def wrap_output(self, source):
        client_module = importlib.import_module("tts_test_package.client")
        stream = client_module.AudioResponseStream(source)
        stream.extension = self.client.audio_format
        return stream

    async def output(self, text, model, voice, language):
        try:
            self.output_started.set()
            yield b"ID3first"
            yield b"last"
        finally:
            self.output_closed = True

    async def input(self, parts=("안녕", "하세요"), *, stalled=False, error=None):
        try:
            self.input_started.set()
            for part in parts:
                yield part
            if stalled:
                await asyncio.Event().wait()
            if error is not None:
                raise error
        finally:
            self.input_closed = True

    def request(self, parts=("안녕", "하세요"), options=None, **kwargs):
        return TTSAudioRequest("ko", options or {}, self.input(parts, **kwargs))

    def assert_registry_empty(self):
        self.assertFalse(self.runtime.tasks)
        self.assertFalse(self.runtime.streams)
        self.assertFalse(self.runtime.responses)

    async def test_stream_is_lazy_and_closes_after_eof(self):
        response = await self.entity.async_stream_tts_audio(self.request())
        self.assertTrue(self.input_closed)
        self.assertEqual(response.extension, "mp3")
        self.client.synthesize_stream.assert_not_called()
        self.assert_registry_empty()
        self.assertEqual([chunk async for chunk in response.data_gen], [b"ID3first", b"last"])
        self.client.synthesize_stream.assert_called_once_with(
            "안녕하세요", "configured", "Kore", "ko"
        )
        self.client.synthesize.assert_not_awaited()
        self.assertTrue(self.output_closed)
        self.assert_registry_empty()

    async def test_never_consumed_response_can_close_without_provider_registration(self):
        response = await self.entity.async_stream_tts_audio(self.request())
        await response.data_gen.aclose()
        self.client.synthesize_stream.assert_not_called()
        self.client.synthesize.assert_not_awaited()
        self.assert_registry_empty()

    async def test_explicit_consumer_close_releases_provider(self):
        response = await self.entity.async_stream_tts_audio(self.request())
        self.assertEqual(await anext(response.data_gen), b"ID3first")
        self.assertEqual(len(self.runtime.streams), 1)
        await response.data_gen.aclose()
        await response.data_gen.aclose()
        self.assertTrue(self.output_closed)
        self.assert_registry_empty()

    async def test_output_disabled_still_collects_bounded_input_and_returns_one_chunk(self):
        self.entry.options["tts_streaming"] = False
        entity = self.module.UniversalTTS(self.entry, "ko")
        self.assertTrue(entity.async_supports_streaming_input())
        response = await entity.async_stream_tts_audio(self.request())
        self.assertTrue(self.input_closed)
        self.assertEqual([chunk async for chunk in response.data_gen], [b"ID3complete"])
        self.client.synthesize.assert_awaited_once_with("안녕하세요", "configured", "Kore", "ko")
        self.client.synthesize_stream.assert_not_called()
        self.assert_registry_empty()

    async def test_empty_invalid_or_oversized_input_is_rejected_and_closed(self):
        cases = (
            (),
            ("", " "),
            (b"invalid",),
            (None,),
            ("\udfff",),
            ("x" * 32768,) * 3,
            ("한" * 11000,) * 2,
        )
        for streaming in (True, False):
            self.entry.options["tts_streaming"] = streaming
            entity = self.module.UniversalTTS(self.entry, "ko")
            for parts in cases:
                self.input_closed = False
                with self.subTest(streaming=streaming, count=len(parts)):
                    with self.assertLogs(self.module.__name__, "WARNING"):
                        with self.assertRaises(self.module.HomeAssistantError) as caught:
                            await entity.async_stream_tts_audio(self.request(parts))
                    self.assertEqual(str(caught.exception), "Unable to generate TTS audio")
                    self.assertTrue(self.input_closed)
        self.client.synthesize.assert_not_awaited()
        self.client.synthesize_stream.assert_not_called()
        self.assert_registry_empty()

    async def test_exact_utf8_limit_is_accepted_without_treating_empty_chunks_as_text(self):
        message = "한" * 21845 + "x"
        response = await self.entity.async_stream_tts_audio(self.request(("", message, "")))
        self.assertEqual(len(message.encode()), 64 * 1024)
        await anext(response.data_gen)
        await response.data_gen.aclose()
        self.client.synthesize_stream.assert_called_once_with(message, "configured", "Kore", "ko")
        self.assert_registry_empty()

    async def test_wrong_model_revision_voice_or_language_never_reaches_provider(self):
        cases = (
            ("ko", {"model": "other"}),
            ("ko", {"connection_revision": "stale"}),
            ("ko", {self.entity._connection_scope_option: False}),
            ("ko", {"voice": " "}),
            ("invalid", {}),
        )
        for language, options in cases:
            self.input_closed = False
            request = self.request(options=options)
            request.language = language
            with self.assertLogs(self.module.__name__, "WARNING"):
                with self.assertRaises(self.module.HomeAssistantError):
                    await self.entity.async_stream_tts_audio(request)
            self.assertTrue(self.input_closed)
        self.client.synthesize_stream.assert_not_called()
        self.client.synthesize.assert_not_awaited()

    async def test_stalled_input_times_out_and_closes_without_provider(self):
        with patch.object(self.module, "AUDIO_COLLECTION_TIMEOUT", 0.01):
            with self.assertLogs(self.module.__name__, "WARNING"):
                with self.assertRaises(self.module.HomeAssistantError):
                    await self.entity.async_stream_tts_audio(self.request(stalled=True))
        self.assertTrue(self.input_closed)
        self.client.synthesize_stream.assert_not_called()
        self.client.synthesize.assert_not_awaited()

    async def test_immediate_empty_chunks_remain_cancellable_and_time_bounded(self):
        async def endless_empty_input():
            try:
                while True:
                    yield ""
            finally:
                self.input_closed = True

        request = TTSAudioRequest("ko", {}, endless_empty_input())
        with patch.object(self.module, "AUDIO_COLLECTION_TIMEOUT", 0.01):
            with self.assertLogs(self.module.__name__, "WARNING"):
                with self.assertRaises(self.module.HomeAssistantError):
                    await self.entity.async_stream_tts_audio(request)
        self.assertTrue(self.input_closed)
        self.client.synthesize_stream.assert_not_called()
        self.client.synthesize.assert_not_awaited()

    async def test_input_cancellation_propagates_and_closes_generator(self):
        task = asyncio.create_task(self.entity.async_stream_tts_audio(self.request(stalled=True)))
        await self.input_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.input_closed)
        self.client.synthesize_stream.assert_not_called()
        self.assert_registry_empty()

    async def delayed_cleanup_input(self, cleanup_started, release_cleanup):
        try:
            self.input_started.set()
            yield "hello"
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
            self.input_closed = True

    async def test_input_timeout_waits_for_upstream_cleanup_before_returning_error(self):
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        request = TTSAudioRequest(
            "ko", {}, self.delayed_cleanup_input(cleanup_started, release_cleanup)
        )
        with patch.object(self.module, "AUDIO_COLLECTION_TIMEOUT", 0.01):
            with self.assertLogs(self.module.__name__, "WARNING"):
                task = asyncio.create_task(self.entity.async_stream_tts_audio(request))
                await cleanup_started.wait()
                self.assertFalse(task.done())
                self.assertFalse(self.input_closed)
                self.client.synthesize.assert_not_awaited()
                self.client.synthesize_stream.assert_not_called()
                release_cleanup.set()
                with self.assertRaises(self.module.HomeAssistantError):
                    await task
        self.assertTrue(self.input_closed)
        self.assert_registry_empty()

    async def test_caller_cancellation_waits_for_upstream_cleanup_and_propagates(self):
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        request = TTSAudioRequest(
            "ko", {}, self.delayed_cleanup_input(cleanup_started, release_cleanup)
        )
        task = asyncio.create_task(self.entity.async_stream_tts_audio(request))
        await self.input_started.wait()
        await asyncio.sleep(0)
        task.cancel()
        await cleanup_started.wait()
        self.assertFalse(task.done())
        self.assertFalse(self.input_closed)
        self.client.synthesize.assert_not_awaited()
        self.client.synthesize_stream.assert_not_called()
        release_cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.input_closed)
        self.assert_registry_empty()

    async def test_input_failure_and_complete_failure_have_safe_errors_and_logs(self):
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            with self.assertRaises(self.module.HomeAssistantError) as caught:
                await self.entity.async_stream_tts_audio(
                    self.request(error=ValueError("PRIVATE-CONTENT"))
                )
        self.assertNotIn("PRIVATE-CONTENT", str(caught.exception) + " ".join(logs.output))
        self.assertTrue(self.input_closed)
        self.entry.options["tts_streaming"] = False
        entity = self.module.UniversalTTS(self.entry, "ko")
        self.client.synthesize.side_effect = self.errors.STTError("PRIVATE-CONTENT")
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            with self.assertRaises(self.module.HomeAssistantError) as caught:
                await entity.async_stream_tts_audio(self.request(("PRIVATE-CONTENT",)))
        self.assertNotIn("PRIVATE-CONTENT", str(caught.exception) + " ".join(logs.output))
        self.assert_registry_empty()

    async def test_partial_provider_failure_closes_without_retry_or_fallback(self):
        async def failing_output(*args):
            try:
                yield b"ID3first"
                raise self.errors.STTError("PRIVATE-CONTENT")
            finally:
                self.output_closed = True

        self.client.synthesize_stream.side_effect = lambda *args: self.wrap_output(
            failing_output(*args)
        )
        response = await self.entity.async_stream_tts_audio(self.request())
        self.assertEqual(await anext(response.data_gen), b"ID3first")
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            with self.assertRaises(self.module.HomeAssistantError) as caught:
                await anext(response.data_gen)
        self.assertNotIn("PRIVATE-CONTENT", str(caught.exception) + " ".join(logs.output))
        self.client.synthesize_stream.assert_called_once()
        self.client.synthesize.assert_not_awaited()
        self.assertTrue(self.output_closed)
        self.assert_registry_empty()

    async def test_pending_output_cancellation_closes_provider_and_propagates(self):
        async def blocked_output(*args):
            try:
                self.output_started.set()
                await self.release_output.wait()
                yield b"audio"
            finally:
                self.output_closed = True

        self.client.synthesize_stream.side_effect = lambda *args: self.wrap_output(
            blocked_output(*args)
        )
        response = await self.entity.async_stream_tts_audio(self.request())
        task = asyncio.create_task(anext(response.data_gen))
        await self.output_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.output_closed)
        self.assert_registry_empty()

    async def test_wav_extension_and_voice_are_preserved(self):
        self.client.audio_format = "wav"
        response = await self.entity.async_stream_tts_audio(self.request(options={"voice": "Puck"}))
        self.assertEqual(response.extension, "wav")
        await anext(response.data_gen)
        await response.data_gen.aclose()
        self.client.synthesize_stream.assert_called_once_with(
            "안녕하세요", "configured", "Puck", "ko"
        )
        self.assert_registry_empty()
