"""Check transport-to-TTS diagnostics without exposing request or error contents."""

import importlib
import types
import unittest

import aiohttp
from test_transport import FakeResponse, FakeSession, Owner
from test_tts_entity import TTSAudioRequest, load_tts_module

PRIVATE = "secret-key private text https://private.example kore"


class TTSDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Keep shared exception identities outside load_tts_module's sys.modules patch.
        self.errors = importlib.import_module("tts_test_package.errors")
        self.module = load_tts_module()
        transport = importlib.import_module("tts_test_package.transport")
        contracts = importlib.import_module("tts_test_package.contracts")
        self.owner = Owner()
        self.response = FakeResponse(body=PRIVATE.encode())
        self.session = FakeSession(self.response)
        self.transport = transport.Transport(self.session, self.owner)
        self.endpoint = contracts.Endpoint("https://private.example/speech", "secret-key")
        self.client = types.SimpleNamespace(
            audio_format="mp3",
            synthesize=self.synthesize,
            synthesize_stream=self.synthesize_stream,
        )
        self.entry = types.SimpleNamespace(
            entry_id="test",
            runtime_data=self.client,
            data={},
            options={"tts_model": "model", "voice": "kore"},
        )

    async def synthesize(self, *args, **kwargs):
        return await self.transport.request_bytes("POST", self.endpoint)

    def synthesize_stream(self, *args, **kwargs):
        return self.transport.stream("POST", self.endpoint)

    async def input(self):
        yield PRIVATE

    async def assert_failure(self, streamed, detail):
        self.entry.options["tts_streaming"] = streamed
        entity = self.module.UniversalTTS(self.entry, "ko")
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            with self.assertRaises(self.module.HomeAssistantError) as raised:
                result = await entity.async_stream_tts_audio(
                    TTSAudioRequest("ko", {}, self.input())
                )
                await anext(result.data_gen)
        self.assertIn(detail, " ".join(logs.output))
        public_output = str(raised.exception) + " ".join(logs.output)
        for private in ("secret-key", "private text", "private.example", "kore"):
            self.assertNotIn(private, public_output)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertFalse(self.owner.tasks)
        self.assertFalse(self.owner.responses)

    async def test_http_status_survives_buffered_and_streamed_tts_without_reading_body(self):
        for streamed in (False, True):
            for status in (400, 401, 402, 403, 429, 500, 502, 503):
                self.response.status = status
                with self.subTest(streamed=streamed, status=status):
                    await self.assert_failure(
                        streamed, f"category=http phase=acquire http_status={status}"
                    )
                    self.assertEqual(self.response.read_sizes, [])
                    self.assertTrue(self.response.closed)

    async def test_acquisition_and_read_failures_have_redacted_categories(self):
        for streamed in (False, True):
            for phase in ("acquire", "read"):
                for category, failure in (
                    ("connection" if phase == "acquire" else "read", aiohttp.ClientError(PRIVATE)),
                    ("timeout", TimeoutError(PRIVATE)),
                ):
                    self.session.failure = failure if phase == "acquire" else None
                    self.response.failure = failure if phase == "read" else None
                    with self.subTest(streamed=streamed, phase=phase, category=category):
                        await self.assert_failure(streamed, f"category={category} phase={phase}")

    async def test_legacy_buffered_tts_logs_status_and_keeps_no_audio_contract(self):
        self.response.status = 402
        entity = self.module.UniversalTTS(self.entry, "ko")
        with self.assertLogs(self.module.__name__, "WARNING") as logs:
            self.assertEqual(await entity.async_get_tts_audio(PRIVATE, "ko", {}), (None, None))
        self.assertIn("http_status=402", " ".join(logs.output))
        self.assertNotIn("secret-key", " ".join(logs.output))
        self.assertEqual(self.response.read_sizes, [])

    async def test_unknown_exception_messages_and_replaced_metadata_are_redacted(self):
        for failure in (self.errors.STTError(PRIVATE), ValueError(PRIVATE)):
            if isinstance(failure, self.errors.STTError):
                failure.diagnostic = PRIVATE

            async def fail(*args, **kwargs):
                raise failure

            async def fail_stream(*args, **kwargs):
                raise failure
                yield  # Keep this a lazy async iterator.

            self.client.synthesize = fail
            self.client.synthesize_stream = fail_stream
            for streamed in (False, True):
                with self.subTest(failure=type(failure).__name__, streamed=streamed):
                    await self.assert_failure(streamed, "category=unclassified")

    def test_diagnostic_fields_reject_arbitrary_strings(self):
        for category, phase, status in (
            (PRIVATE, self.errors.FailurePhase.ACQUIRE, None),
            (self.errors.FailureCategory.HTTP, PRIVATE, 400),
            (self.errors.FailureCategory.HTTP, self.errors.FailurePhase.ACQUIRE, "400 secret"),
            (self.errors.FailureCategory.HTTP, self.errors.FailurePhase.ACQUIRE, True),
            (self.errors.FailureCategory.HTTP, self.errors.FailurePhase.ACQUIRE, 600),
        ):
            with self.subTest(category=category, phase=phase, status=status):
                with self.assertRaises(ValueError):
                    self.errors.FailureDiagnostic(category, phase, status)
