"""Exercise response ownership with deterministic fakes and a loopback server."""

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web
from yarl import URL

package = types.ModuleType("transport_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/universal_stt")]
sys.modules[package.__name__] = package
transport_module = importlib.import_module("transport_test_package.transport")
contracts = importlib.import_module("transport_test_package.contracts")
errors = importlib.import_module("transport_test_package.errors")
Endpoint = contracts.Endpoint
Transport = transport_module.Transport


class Owner:
    def __init__(self):
        self.tasks = set()
        self.responses = set()
        self.reject_task = False
        self.reject_response = False

    def register_task(self, task):
        self.tasks.add(task)
        if self.reject_task:
            raise errors.EntryUnavailableError("Entry is closed")

    def unregister_task(self, task):
        self.tasks.discard(task)

    def register_response(self, response):
        self.responses.add(response)
        if self.reject_response:
            raise errors.EntryUnavailableError("Entry is closed")

    def unregister_response(self, response):
        self.responses.discard(response)


class FakeResponse:
    def __init__(self, body=b"audio", *, status=200, content_type="audio/mpeg", length=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = {"Content-Type": content_type}
        self.content_length = length
        self.content = self
        self.closed = False
        self.close_count = 0
        self.read_sizes = []
        self.read_started = asyncio.Event()
        self.block_read = False
        self.cancelled = False
        self.failure = None

    async def read(self, size):
        self.read_sizes.append(size)
        self.read_started.set()
        if self.failure is not None:
            raise self.failure
        if self.block_read:
            try:
                await asyncio.Future()
            finally:
                self.cancelled = True
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def close(self):
        self.closed = True
        self.close_count += 1


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False
        self.headers = {}
        self.request_started = asyncio.Event()
        self.block_headers = False
        self.cancelled = False
        self.failure = None

    async def request(self, method, url, **options):
        self.calls.append((method, url, options))
        self.request_started.set()
        if self.block_headers:
            try:
                await asyncio.Future()
            finally:
                self.cancelled = True
        if self.failure:
            raise self.failure
        return self.response


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = Owner()
        self.response = FakeResponse()
        self.session = FakeSession(self.response)
        self.transport = Transport(self.session, self.owner)
        self.endpoint = Endpoint("https://voice.example/speech?secret=query", "secret-key")

    def assert_released(self):
        self.assertTrue(self.response.closed)
        self.assertEqual(self.owner.responses, set())
        self.assertEqual(self.owner.tasks, set())
        self.assertFalse(self.session.closed)

    async def test_success_headers_are_fresh_and_timeout_fixed(self):
        self.assertEqual(await self.transport.request_bytes("POST", self.endpoint), b"audio")
        options = self.session.calls[0][2]
        self.assertEqual(options["headers"], {"Authorization": "Bearer secret-key"})
        self.assertFalse(options["allow_redirects"])
        self.assertEqual(options["timeout"].total, 60)
        self.assert_released()
        options["headers"].clear()
        self.response.body = b"audio"
        await self.transport.request_bytes("GET", Endpoint("https://other.example", "", "google"))
        self.assertEqual(self.session.calls[-1][2]["headers"], {})
        self.response.body = b"audio"
        await self.transport.request_bytes(
            "POST", Endpoint("https://google.example", "g", "google")
        )
        self.assertEqual(self.session.calls[-1][2]["headers"], {"x-goog-api-key": "g"})

    async def test_request_policy_cannot_be_overridden(self):
        for options in (
            {"headers": {"Authorization": "unexpected"}},
            {"auth": object()},
            {"cookies": {"token": "ambient"}},
            {"allow_redirects": True},
            {"timeout": aiohttp.ClientTimeout(total=1)},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                await self.transport.request_json("GET", self.endpoint, **options)
        self.assertEqual(self.session.calls, [])

    async def test_session_default_credentials_are_rejected(self):
        for attribute, value in (
            ("headers", {"Authorization": "ambient"}),
            ("headers", {"X-Goog-Api-Key": "ambient"}),
            ("headers", {"Cookie": "token=ambient"}),
            ("_default_auth", object()),
            ("trust_env", True),
        ):
            setattr(self.session, attribute, value)
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                self.transport.stream("GET", self.endpoint)
            setattr(self.session, attribute, {} if attribute == "headers" else None)
        self.assertEqual(self.session.calls, [])

    async def test_session_credentials_mutated_after_stream_creation_are_rejected(self):
        for header in ("Authorization", "x-goog-api-key", "Cookie"):
            stream = self.transport.stream("GET", self.endpoint)
            self.session.headers[header] = "ambient-key"
            with self.subTest(header=header), self.assertRaises(errors.STTError):
                await anext(stream)
            await stream.aclose()
            self.session.headers.clear()
        stream = self.transport.stream("GET", self.endpoint)
        self.session.cookie_jar = aiohttp.CookieJar()
        self.session.cookie_jar.update_cookies(
            {"token": "ambient-key"}, response_url=URL(self.endpoint.url)
        )
        with self.assertRaises(errors.STTError):
            await anext(stream)
        await stream.aclose()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.owner.tasks, set())

    async def test_status_mapping_never_reads_error_body(self):
        for status in (301, 302, 307, 400, 401, 402, 403, 429, 500, 502, 503):
            self.response.status = status
            self.response.body = b"secret service body"
            expected = errors.AuthenticationError if status in (401, 403) else errors.STTError
            with self.subTest(status=status), self.assertRaises(expected) as raised:
                await self.transport.request_bytes("POST", self.endpoint)
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(
                errors.safe_failure_detail(raised.exception),
                f"category=http phase=acquire http_status={status}",
            )
            self.assertEqual(self.response.read_sizes, [])
            self.assert_released()

    async def test_bad_content_empty_and_declared_oversize_close_response(self):
        for body, content_type, length in (
            (b"{}", "application/json", None),
            (b"", "audio/mpeg", None),
            (b"audio", "audio/mpeg", 11),
        ):
            self.response.body = body
            self.response.content_type = content_type
            self.response.content_length = length
            with self.subTest(body=body), self.assertRaises(errors.ResponseError):
                await self.transport.request_bytes("POST", self.endpoint, max_bytes=10)
            self.assert_released()

    async def test_unknown_length_read_stops_at_limit_plus_one(self):
        self.response.body = b"a" * 50
        with self.assertRaises(errors.ResponseError):
            await self.transport.request_bytes("POST", self.endpoint, max_bytes=10)
        self.assertEqual(self.response.read_sizes, [11])
        self.assertEqual(len(self.response.body), 39)
        self.assert_released()

    async def test_json_object_boundary_and_malformed_body(self):
        for body in (b"[]", b"null", b"{invalid", b"\xff", b"{}extra"):
            self.response.body = body
            with self.subTest(body=body), self.assertRaises(errors.ResponseError):
                await self.transport.request_json("GET", self.endpoint)
            self.assert_released()
        self.response.body = b'{"text":"ok"}'
        self.assertEqual(
            await self.transport.request_json("GET", self.endpoint, max_bytes=13), {"text": "ok"}
        )
        self.response.body = b'{"text":"ok"}'
        with self.assertRaises(errors.ResponseError):
            await self.transport.request_json("GET", self.endpoint, max_bytes=12)
        self.assert_released()

    async def test_network_error_is_safe_and_without_sensitive_cause(self):
        for failure in (aiohttp.ClientError("secret-key"), TimeoutError("secret body")):
            self.session.failure = failure
            with self.subTest(failure=failure), self.assertRaises(errors.STTError) as raised:
                await self.transport.request_json("GET", self.endpoint)
            self.assertNotIn("secret", str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertEqual(self.owner.tasks, set())

    async def test_never_consumed_stream_has_no_request_or_owned_task(self):
        stream = self.transport.stream("POST", self.endpoint)
        await asyncio.gather(stream.aclose(), stream.aclose())
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.owner.tasks, set())
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

    async def test_pending_headers_close_cancels_and_joins_child(self):
        self.session.block_headers = True
        stream = self.transport.stream("POST", self.endpoint)
        caller = asyncio.create_task(anext(stream))
        await self.session.request_started.wait()
        self.assertEqual(len(self.owner.tasks), 1)
        self.assertNotIn(caller, self.owner.tasks)
        await asyncio.gather(stream.aclose(), stream.aclose())
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(self.session.cancelled)
        self.assertEqual(self.owner.tasks, set())

    async def test_blocked_read_concurrent_close_and_runtime_join(self):
        self.response.block_read = True
        stream = self.transport.stream("POST", self.endpoint)
        caller = asyncio.create_task(anext(stream))
        await self.response.read_started.wait()
        self.assertEqual(self.owner.responses, {self.response})
        tasks = list(self.owner.tasks)
        self.response.close()
        for task in tasks:
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(
                stream.aclose(), stream.aclose(), asyncio.gather(*tasks, return_exceptions=True)
            ),
            1,
        )
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(self.response.cancelled)
        self.assert_released()

    async def test_consumer_cancellation_closes_and_preserves_cancel(self):
        self.response.block_read = True
        caller = asyncio.create_task(self.transport.request_bytes("POST", self.endpoint))
        await self.response.read_started.wait()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assert_released()

    async def test_owner_rejection_cleans_partial_registration(self):
        self.owner.reject_task = True
        with self.assertRaises(errors.EntryUnavailableError):
            await self.transport.request_json("GET", self.endpoint)
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.owner.tasks, set())
        self.owner.reject_task = False
        self.owner.reject_response = True
        with self.assertRaises(errors.EntryUnavailableError):
            await self.transport.request_bytes("POST", self.endpoint)
        self.assert_released()

    async def test_full_timeout_covers_headers_body_and_consumer_pause(self):
        with patch.object(transport_module, "HTTP_TIMEOUT", 0.02):
            self.session.block_headers = True
            with self.assertRaises(errors.STTError):
                await self.transport.request_json("GET", self.endpoint)
            self.assertTrue(self.session.cancelled)
            self.session.block_headers = False
            self.response.block_read = True
            with self.assertRaises(errors.STTError):
                await self.transport.request_bytes("GET", self.endpoint)
            self.assert_released()
            self.response.block_read = False
            self.response.body = b"audio"
            stream = self.transport.stream("GET", self.endpoint)
            self.assertEqual(await anext(stream), b"audio")
            stream._deadline = asyncio.get_running_loop().time() - 1
            with self.assertRaises(errors.STTError):
                await anext(stream)
            await stream.aclose()
            self.assert_released()

    async def test_break_then_explicit_close_releases_response(self):
        stream = self.transport.stream("GET", self.endpoint)
        async for _ in stream:
            break
        self.assertFalse(self.response.closed)
        await stream.aclose()
        await stream.aclose()
        self.assertEqual(self.response.close_count, 1)
        self.assert_released()


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_session_redirect_auth_size_and_reuse(self):
        target_hits = []
        observed_headers = []

        async def service(request):
            observed_headers.append(dict(request.headers))
            if request.path == "/redirect":
                raise web.HTTPFound("/target")
            if request.path == "/target":
                target_hits.append(True)
            if request.path == "/auth":
                return web.Response(status=401, text="secret body")
            if request.path == "/large":
                response = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
                await response.prepare(request)
                await response.write(b"a" * 32)
                await response.write_eof()
                return response
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_get("/{path}", service)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        origin = f"http://127.0.0.1:{runner.addresses[0][1]}"
        owner = Owner()
        try:
            async with aiohttp.ClientSession() as session:
                transport = Transport(session, owner)
                with self.assertRaises(errors.STTError):
                    await transport.request_json("GET", Endpoint(origin + "/redirect", "test-key"))
                self.assertEqual(target_hits, [])
                with self.assertRaises(errors.AuthenticationError):
                    await transport.request_json("GET", Endpoint(origin + "/auth"))
                with self.assertRaises(errors.ResponseError):
                    await transport.request_bytes("GET", Endpoint(origin + "/large"), max_bytes=10)
                self.assertEqual(
                    await transport.request_json("GET", Endpoint(origin + "/ok", "g", "google")),
                    {"ok": True},
                )
                self.assertEqual(observed_headers[0]["Authorization"], "Bearer test-key")
                self.assertEqual(observed_headers[-1]["x-goog-api-key"], "g")
                self.assertNotIn("Authorization", observed_headers[-1])
                self.assertFalse(session.closed)
                self.assertEqual(owner.tasks, set())
                self.assertEqual(owner.responses, set())
        finally:
            await runner.cleanup()
