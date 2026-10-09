"""Bounded HTTP requests and lazy response streams without owning the HA session."""

import asyncio
import json
import logging
from collections.abc import Coroutine
from typing import Any, Protocol, TypeVar

import aiohttp
from yarl import URL

from .const import HTTP_TIMEOUT, MAX_SSE_WIRE_BYTES, MAX_TTS_AUDIO_BYTES
from .contracts import Endpoint
from .errors import (
    AuthenticationError,
    FailureCategory,
    FailureDiagnostic,
    FailurePhase,
    ResponseError,
    STTError,
)

T = TypeVar("T")
_LOGGER = logging.getLogger(__name__)
PROBE_MEDIA_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/pcm",
        "audio/wav",
        "application/json",
        "application/octet-stream",
    }
)


class TransportOwner(Protocol):
    """Synchronous resource ownership seam implemented by an entry runtime.

    Register tasks before any HTTP await. Register responses immediately upon
    acquisition. Unregister methods must be idempotent and must not raise.
    Admission is separate: pausing new entry requests must not reject resource
    registration for an already admitted request.
    Shutdown closes registered responses, cancels and joins registered tasks,
    then closes provider iterators. It never owns the HA caller task.
    """

    def register_task(self, task: asyncio.Task) -> None: ...

    def unregister_task(self, task: asyncio.Task) -> None: ...

    def register_response(self, response: aiohttp.ClientResponse) -> None: ...

    def unregister_response(self, response: aiohttp.ClientResponse) -> None: ...


class Transport:
    """Use Endpoint authentication and retain the caller's shared session."""

    def __init__(self, session: aiohttp.ClientSession, owner: TransportOwner | None = None):
        self._session = session
        self._owner = owner

    async def _start(self, operation: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        task = asyncio.create_task(operation)
        try:
            if self._owner is not None:
                self._owner.register_task(task)
                task.add_done_callback(self._owner.unregister_task)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._owner is not None:
                self._owner.unregister_task(task)
            raise
        return task

    async def _acquire(self, method: str, endpoint: Endpoint, options: dict):
        # The shared session may have changed since a lazy stream was created.
        self._validate_options(options, endpoint)
        try:
            response = await self._session.request(
                method,
                endpoint.url,
                headers=endpoint.headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
                allow_redirects=False,
                **options,
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            category = (
                FailureCategory.TIMEOUT
                if isinstance(err, TimeoutError)
                else FailureCategory.CONNECTION
            )
            raise STTError(
                "Unable to contact voice service",
                diagnostic=FailureDiagnostic(category, FailurePhase.ACQUIRE),
            ) from None
        try:
            if self._owner is not None:
                self._owner.register_response(response)
        except BaseException:
            response.close()
            if self._owner is not None:
                self._owner.unregister_response(response)
            raise
        return response

    def _release(self, response: aiohttp.ClientResponse) -> None:
        response.close()
        if self._owner is not None:
            self._owner.unregister_response(response)

    def _validate_options(self, options: dict, endpoint: Endpoint) -> None:
        if {"headers", "auth", "cookies", "timeout", "allow_redirects"} & options.keys():
            raise ValueError("Transport owns authentication, redirects, and timeout")
        # aiohttp otherwise silently merges session credentials into a request.
        if (
            getattr(self._session, "_default_auth", None) is not None
            or getattr(self._session, "trust_env", False)
            or any(
                header.lower() in {"authorization", "x-goog-api-key", "cookie"}
                for header in getattr(self._session, "headers", {})
            )
        ):
            raise ValueError("Voice transport requires a session without default credentials")
        cookie_jar = getattr(self._session, "cookie_jar", None)
        if cookie_jar is not None and cookie_jar.filter_cookies(URL(endpoint.url)):
            raise ValueError("Voice transport requires requests without session cookies")

    def stream(
        self,
        method: str,
        endpoint: Endpoint,
        *,
        max_bytes: int = MAX_TTS_AUDIO_BYTES,
        content_types: frozenset[str] | None = None,
        log_audio_format: bool = False,
        **options,
    ) -> "ResponseStream":
        """Return lazy bytes, suitable for an audio or provider SSE transformer.

        Consumers close in finally. On unload the owner cancels/joins child
        tasks before provider generator aclose; ResponseStream itself is not
        an async generator and can close safely during a pending pull.
        """
        self._validate_options(options, endpoint)
        if max_bytes <= 0:
            raise ValueError("Response byte limit must be positive")
        if type(log_audio_format) is not bool:
            raise ValueError("Audio format probe flag must be boolean")
        return ResponseStream(
            self, method, endpoint, options, max_bytes, content_types, log_audio_format
        )

    async def request_bytes(
        self,
        method: str,
        endpoint: Endpoint,
        *,
        max_bytes: int = MAX_TTS_AUDIO_BYTES,
        content_types: frozenset[str] | None = frozenset(
            {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "application/octet-stream"}
        ),
        **options,
    ) -> bytes:
        stream = self.stream(
            method, endpoint, max_bytes=max_bytes, content_types=content_types, **options
        )
        try:
            result = bytearray()
            async for chunk in stream:
                result.extend(chunk)
            return bytes(result)
        finally:
            await stream.aclose()

    async def request_json(
        self,
        method: str,
        endpoint: Endpoint,
        *,
        max_bytes: int = MAX_SSE_WIRE_BYTES,
        **options,
    ) -> dict:
        data = await self.request_bytes(
            method, endpoint, max_bytes=max_bytes, content_types=None, **options
        )
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError, RecursionError):
            raise ResponseError("Invalid JSON service response") from None
        if not isinstance(payload, dict):
            raise ResponseError("Invalid JSON response structure")
        return payload


class ResponseStream:
    """A single-consumer lazy HTTP iterator with shared, shielded cleanup."""

    def __init__(
        self,
        transport: Transport,
        method: str,
        endpoint: Endpoint,
        options: dict,
        max_bytes: int,
        content_types: frozenset[str] | None,
        log_audio_format: bool = False,
    ):
        self._transport = transport
        self._method = method
        self._endpoint = endpoint
        self._options = options
        self._max_bytes = max_bytes
        self._content_types = content_types
        self._log_audio_format = log_audio_format
        self._response: aiohttp.ClientResponse | None = None
        self._pending: asyncio.Task | None = None
        self._cleanup: asyncio.Task | None = None
        self._closed = False
        self._received = 0
        self._deadline: float | None = None
        self.content_type_header = ""

    def __aiter__(self) -> "ResponseStream":
        return self

    def _close_response(self) -> None:
        response, self._response = self._response, None
        if response is not None:
            self._transport._release(response)

    async def __anext__(self) -> bytes:
        return await self.read_chunk()

    @property
    def deadline(self):
        return self._deadline

    async def read_chunk(self, size=65536) -> bytes:
        """Bound a preparation prefix without discarding the remaining response."""
        if not 1 <= size <= 65536:
            raise ValueError("Invalid response chunk size")
        if self._closed:
            raise StopAsyncIteration
        if self._pending is not None:
            raise RuntimeError("Response stream already has a pending consumer")
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + HTTP_TIMEOUT
        try:
            self._pending = await self._transport._start(self._pull(size))
            return await self._pending
        finally:
            self._pending = None

    async def _pull(self, size) -> bytes:
        phase = FailurePhase.READ if self._response is not None else FailurePhase.ACQUIRE
        try:
            if asyncio.get_running_loop().time() >= self._deadline:
                raise TimeoutError
            async with asyncio.timeout_at(self._deadline):
                if self._response is None:
                    self._response = await self._transport._acquire(
                        self._method, self._endpoint, self._options
                    )
                    self._check_response()
                phase = FailurePhase.READ
                chunk = await self._response.content.read(
                    min(size, self._max_bytes - self._received + 1)
                )
                self._received += len(chunk)
                if self._received > self._max_bytes:
                    raise ResponseError("Service response exceeds byte limit")
                if not chunk:
                    if not self._received:
                        raise ResponseError("Service returned an empty response")
                    raise StopAsyncIteration
                return chunk
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._closed = True
            self._close_response()
            category = (
                FailureCategory.TIMEOUT if isinstance(err, TimeoutError) else FailureCategory.READ
            )
            raise STTError(
                "Unable to read voice service response",
                diagnostic=FailureDiagnostic(category, phase),
            ) from None
        except BaseException:
            self._closed = True
            self._close_response()
            raise

    def _check_response(self) -> None:
        response = self._response
        # Keep a copied value after response close; never retain or log raw headers.
        self.content_type_header = str(response.headers.get("Content-Type", ""))
        if self._log_audio_format:
            status = response.status
            safe_status = status if type(status) is int and 100 <= status <= 599 else 0
            media_type = response.content_type
            safe_type = media_type if media_type in PROBE_MEDIA_TYPES else "other"
            _LOGGER.warning(
                "OpenRouter TTS format probe (http_status=%s media_type=%s)", safe_status, safe_type
            )
        if response.status in {401, 403}:
            raise AuthenticationError(
                "Voice service rejected authentication",
                diagnostic=FailureDiagnostic(
                    FailureCategory.HTTP, FailurePhase.ACQUIRE, response.status
                ),
            )
        if not 200 <= response.status < 300:
            diagnostic = FailureDiagnostic(
                FailureCategory.HTTP, FailurePhase.ACQUIRE, response.status
            )
            raise STTError(
                f"Voice service returned HTTP {diagnostic.http_status}", diagnostic=diagnostic
            )
        if self._content_types is not None and response.content_type not in self._content_types:
            raise ResponseError("Unsupported service response content type")
        if response.content_length is not None and response.content_length > self._max_bytes:
            raise ResponseError("Service response exceeds byte limit")

    async def aclose(self) -> None:
        """Close the response now, then cancel/join a pending request or read.

        Cleanup is independent of the owned child task, so runtime task joins
        and concurrent consumer closes cannot wait on each other.
        """
        self._closed = True
        self._close_response()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._cleanup)

    async def _finish_close(self) -> None:
        pending = self._pending
        if pending is not None and pending is not asyncio.current_task():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        self._close_response()
