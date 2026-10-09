"""Exercise entry ownership and HA lifecycle interfaces without paid providers."""

import asyncio
import importlib
import importlib.util
import sys
import time
import types
import unittest
from enum import Enum
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

package = types.ModuleType("lifecycle_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
runtime_module = importlib.import_module("lifecycle_test_package.runtime")
client_module = importlib.import_module("lifecycle_test_package.client")
settings_module = importlib.import_module("lifecycle_test_package.settings")
transport_module = importlib.import_module("lifecycle_test_package.transport")
errors = importlib.import_module("lifecycle_test_package.errors")


class Platform(str, Enum):
    STT = "stt"
    TTS = "tts"


class Response:
    status = 200
    content_type = "audio/mpeg"
    headers = {"Content-Type": "audio/mpeg"}
    content_length = None

    def __init__(self):
        self.closed = False
        self.first = True
        self.read_started = asyncio.Event()
        self.release = asyncio.Event()
        self.content = types.SimpleNamespace(read=self.read)

    async def read(self, size):
        if self.first:
            self.first = False
            return b"ID3audio"
        self.read_started.set()
        await self.release.wait()
        return b""

    def close(self):
        self.closed = True


class Session:
    headers = {}
    trust_env = False
    closed = False

    def __init__(self, *, pending_headers=False):
        self.response = Response()
        self.requested = asyncio.Event()
        self.headers_ready = asyncio.Event()
        if not pending_headers:
            self.headers_ready.set()
        self.calls = []

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.requested.set()
        await self.headers_ready.wait()
        return self.response


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = Session()
        const = types.ModuleType("homeassistant.const")
        const.Platform = Platform
        aio = types.ModuleType("homeassistant.helpers.aiohttp_client")
        aio.async_get_clientsession = lambda hass: self.session
        session_helper = types.ModuleType("lifecycle_test_package.http_session")
        session_helper.async_get_voice_session = lambda hass: self.session
        with patch.dict(
            sys.modules,
            {
                "homeassistant": types.ModuleType("homeassistant"),
                "homeassistant.const": const,
                "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
                "homeassistant.helpers.aiohttp_client": aio,
                "lifecycle_test_package.http_session": session_helper,
            },
        ):
            spec = importlib.util.spec_from_file_location(
                "lifecycle_test_package.entrypoint", Path(package.__path__[0]) / "__init__.py"
            )
            spec.submodule_search_locations = None
            self.entrypoint = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.entrypoint)
        self.hass = types.SimpleNamespace(
            async_add_executor_job=AsyncMock(side_effect=lambda job: job()),
            config_entries=types.SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
                async_reload=AsyncMock(),
            ),
        )
        self.entry = types.SimpleNamespace(
            data={
                "provider": "custom",
                "base_url": "http://localhost/v1",
                "mode": "both",
                "api_key": "key",
            },
            options={},
            entry_id="stable-id",
            async_on_unload=Mock(),
            add_update_listener=Mock(),
        )

    async def setup(self):
        await self.entrypoint.async_setup_entry(self.hass, self.entry)
        return self.entry.runtime_data

    def assert_empty(self, runtime):
        self.assertEqual((runtime.tasks, runtime.responses, runtime.streams), (set(), set(), set()))
        self.assertFalse(self.session.closed)

    async def test_all_providers_and_modes_boot_without_discovery_or_speech(self):
        self.assertIs(self.entrypoint.create_voice_client, client_module.create_voice_client)
        for provider in ("openrouter", "openai", "xai", "gemini", "custom"):
            for mode in ("stt", "tts", "both"):
                with self.subTest(provider=provider, mode=mode):
                    self.hass.async_add_executor_job.reset_mock()
                    self.entry.data.update(provider=provider, mode=mode)
                    runtime = await self.setup()
                    expected = [
                        platform for platform in Platform if mode in {platform.value, "both"}
                    ]
                    self.assertEqual(runtime.loaded_platforms, expected)
                    self.assertEqual(
                        self.hass.async_add_executor_job.await_count,
                        int(provider == "openrouter" and mode in {"tts", "both"}),
                    )
                    self.assertEqual(runtime.audio_format, "wav" if provider == "gemini" else "mp3")
                    self.assertTrue(await self.entrypoint.async_unload_entry(self.hass, self.entry))
                    self.assert_empty(runtime)
        self.assertEqual(self.session.calls, [])

    async def test_invalid_audio_policy_rolls_back_before_forwarding_platforms(self):
        self.entry.data.update(provider="openrouter", mode="tts")
        self.hass.async_add_executor_job.side_effect = errors.ResponseError(
            "Invalid model audio format configuration"
        )
        with self.assertRaises(errors.ResponseError):
            await self.setup()
        self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()
        self.hass.config_entries.async_unload_platforms.assert_awaited_once()
        self.assertTrue(self.entry.runtime_data.closed)
        self.assert_empty(self.entry.runtime_data)
        self.assertFalse(self.session.calls)

    async def test_legacy_mode_options_snapshot_listener_and_reload(self):
        self.entry.data.update(mode="both", api_key="data-secret")
        self.entry.options = {
            "provider": "openai",
            "base_url": "http://localhost/v1",
            "model": "new",
        }
        runtime = await self.setup()
        self.assertEqual(runtime.loaded_platforms, [Platform.STT])
        self.assertEqual(runtime.settings.api_key, "")
        self.entry.add_update_listener.assert_called_once_with(self.entrypoint.async_reload_entry)
        await self.entrypoint.async_reload_entry(self.hass, self.entry)
        self.hass.config_entries.async_reload.assert_awaited_once_with("stable-id")
        await runtime.shutdown()

    async def test_unload_cancels_owned_pending_headers_without_cancelling_caller_task(self):
        self.session = Session(pending_headers=True)
        runtime = await self.setup()
        caller = asyncio.create_task(runtime.synthesize("hello", "model", "voice"))
        await self.session.requested.wait()
        self.assertNotIn(caller, runtime.tasks)
        self.assertTrue(await self.entrypoint.async_unload_entry(self.hass, self.entry))
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(caller.cancelling(), 0)
        self.assert_empty(runtime)

    async def test_unload_closes_blocked_read_and_lazy_unconsumed_stream_has_no_resources(self):
        runtime = await self.setup()
        unused = runtime.synthesize_stream("unused", "model", "voice")
        self.assert_empty(runtime)
        self.assertEqual(self.session.calls, [])
        active = runtime.synthesize_stream("hello", "model", "voice")
        self.assertEqual(await anext(active), b"ID3audio")
        caller = asyncio.create_task(anext(active))
        await self.session.response.read_started.wait()
        self.assertTrue(await self.entrypoint.async_unload_entry(self.hass, self.entry))
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(self.session.response.closed)
        self.assert_empty(runtime)
        with self.assertRaises(errors.EntryUnavailableError):
            await anext(unused)
        await unused.aclose()

    async def test_unload_false_or_exception_resumes_admission_and_preserves_inflight_read(self):
        for failure in (False, RuntimeError("platform failed")):
            with self.subTest(failure=type(failure).__name__):
                self.session = Session()
                runtime = await self.setup()
                caller = asyncio.create_task(runtime.synthesize("hello", "model", "voice"))
                await self.session.response.read_started.wait()

                async def unload(entry, platforms):
                    self.assertTrue(runtime.paused)
                    with self.assertRaises(errors.EntryUnavailableError):
                        await runtime.transcribe(b"wav", "model", "en")
                    if isinstance(failure, Exception):
                        raise failure
                    return failure

                self.hass.config_entries.async_unload_platforms.side_effect = unload
                if isinstance(failure, Exception):
                    with self.assertRaises(RuntimeError):
                        await self.entrypoint.async_unload_entry(self.hass, self.entry)
                else:
                    self.assertFalse(
                        await self.entrypoint.async_unload_entry(self.hass, self.entry)
                    )
                self.assertFalse(runtime.closed)
                self.assertFalse(runtime.paused)
                self.assertFalse(caller.done())
                self.assertFalse(self.session.response.closed)
                self.session.response.release.set()
                self.assertEqual(await caller, b"ID3audio")
                runtime.client.synthesize = AsyncMock(return_value=b"new")
                self.assertEqual(await runtime.synthesize("new", "model", "voice"), b"new")
                await runtime.shutdown()
                self.assert_empty(runtime)
                self.hass.config_entries.async_unload_platforms.side_effect = None

    async def test_setup_partial_failure_rolls_back_platforms_and_owned_resources(self):
        calls = []

        async def forward(entry, platforms):
            calls.append(
                asyncio.create_task(entry.runtime_data.synthesize("hello", "model", "voice"))
            )
            await self.session.response.read_started.wait()
            raise RuntimeError("setup failed")

        self.hass.config_entries.async_forward_entry_setups.side_effect = forward
        with self.assertRaises(RuntimeError):
            await self.setup()
        runtime = self.entry.runtime_data
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.platforms_unloaded)
        with self.assertRaises(asyncio.CancelledError):
            await calls[0]
        self.assert_empty(runtime)
        self.entry.add_update_listener.assert_not_called()

    async def test_cleanup_failure_is_observable_and_retry_does_not_unload_platforms_again(self):
        runtime = await self.setup()
        source = types.SimpleNamespace(__anext__=AsyncMock(return_value=b"audio"))

        class FlakyStream:
            extension = "mp3"

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await source.__anext__()

            aclose = AsyncMock(side_effect=[RuntimeError("cleanup failed"), None])

        runtime.client.synthesize_stream = Mock(return_value=FlakyStream())
        stream = runtime.synthesize_stream("hello", "model", "voice")
        await anext(stream)
        self.hass.config_entries.async_unload_platforms.reset_mock()
        with self.assertRaises(errors.ShutdownError):
            await self.entrypoint.async_unload_entry(self.hass, self.entry)
        self.assertIsNotNone(runtime.shutdown_error)
        self.assertTrue(runtime.closed)
        runtime.resume()
        self.assertTrue(runtime.paused)
        self.assertTrue(await self.entrypoint.async_unload_entry(self.hass, self.entry))
        self.hass.config_entries.async_unload_platforms.assert_awaited_once()
        self.assertIsNone(runtime.shutdown_error)
        self.assert_empty(runtime)

    async def test_cancellation_resistant_task_times_out_boundedly_and_can_finish_on_retry(self):
        runtime = await self.setup()
        started, released = asyncio.Event(), asyncio.Event()

        async def resist(*args):
            started.set()
            while not released.is_set():
                try:
                    await released.wait()
                except asyncio.CancelledError:
                    continue
            return b"audio"

        runtime.client.synthesize = resist
        caller = asyncio.create_task(runtime.synthesize("hello", "model", "voice"))
        await started.wait()
        self.hass.config_entries.async_unload_platforms.reset_mock()
        try:
            with patch.object(runtime_module, "ENTRY_SHUTDOWN_TIMEOUT", 0.02):
                before = time.monotonic()
                with self.assertRaises(errors.ShutdownError):
                    await self.entrypoint.async_unload_entry(self.hass, self.entry)
                self.assertLess(time.monotonic() - before, 0.2)
            self.assertTrue(runtime.closed)
            self.assertIsNotNone(runtime.shutdown_error)
        finally:
            released.set()
        self.assertEqual(await caller, b"audio")
        self.assertTrue(await self.entrypoint.async_unload_entry(self.hass, self.entry))
        self.hass.config_entries.async_unload_platforms.assert_awaited_once()
        self.assert_empty(runtime)

    async def test_break_explicit_close_concurrent_close_and_caller_cancellation_release_stream(
        self,
    ):
        runtime = await self.setup()
        stream = runtime.synthesize_stream("hello", "model", "voice")
        async for chunk in stream:
            self.assertEqual(chunk, b"ID3audio")
            break
        self.assertTrue(runtime.responses)
        await asyncio.gather(stream.aclose(), stream.aclose())
        self.assert_empty(runtime)
        self.session.response = Response()
        stream = runtime.synthesize_stream("hello", "model", "voice")
        await anext(stream)
        caller = asyncio.create_task(anext(stream))
        await self.session.response.read_started.wait()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assert_empty(runtime)
        await runtime.shutdown()

    async def test_setup_retry_preserves_failed_runtime_until_remaining_cleanup_succeeds(self):
        released, started = asyncio.Event(), asyncio.Event()
        callers = []

        async def resist(*args):
            started.set()
            while not released.is_set():
                try:
                    await released.wait()
                except asyncio.CancelledError:
                    continue
            return b"audio"

        async def forward(entry, platforms):
            entry.runtime_data.client.synthesize = resist
            callers.append(
                asyncio.create_task(entry.runtime_data.synthesize("hello", "model", "voice"))
            )
            await started.wait()
            raise RuntimeError("setup failed")

        self.hass.config_entries.async_forward_entry_setups.side_effect = forward
        try:
            with patch.object(runtime_module, "ENTRY_SHUTDOWN_TIMEOUT", 0.01):
                with self.assertRaises(errors.ShutdownError):
                    await self.setup()
                previous = self.entry.runtime_data
                self.hass.config_entries.async_forward_entry_setups.side_effect = None
                with self.assertRaises(errors.ShutdownError):
                    await self.setup()
                self.assertIs(self.entry.runtime_data, previous)
                self.assertEqual(self.hass.config_entries.async_forward_entry_setups.await_count, 1)
        finally:
            released.set()
        await callers[0]
        replacement = await self.setup()
        self.assertIsNot(replacement, previous)
        self.assert_empty(previous)
        await replacement.shutdown()

    async def test_setup_retry_retries_failed_platform_rollback_before_replacing_runtime(self):
        self.hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError(
            "setup failed"
        )
        self.hass.config_entries.async_unload_platforms.return_value = False
        with self.assertRaises(RuntimeError):
            await self.setup()
        previous = self.entry.runtime_data
        self.hass.config_entries.async_forward_entry_setups.side_effect = None
        with self.assertRaises(errors.ShutdownError):
            await self.setup()
        self.assertIs(self.entry.runtime_data, previous)
        self.hass.config_entries.async_unload_platforms.return_value = True
        replacement = await self.setup()
        self.assertIsNot(replacement, previous)
        await replacement.shutdown()
