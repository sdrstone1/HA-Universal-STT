"""Entry-owned voice operations, lazy streams, and bounded shutdown retries."""

import asyncio

from .const import ENTRY_SHUTDOWN_TIMEOUT
from .contracts import SynthesizedAudio
from .errors import (
    EntryUnavailableError,
    FailureCategory,
    FailureDiagnostic,
    FailurePhase,
    ShutdownError,
    STTError,
)


class EntryRuntime:
    """Own child tasks and responses, never the HA caller or shared HTTP session."""

    def __init__(self, settings):
        self.settings = settings
        self.client = None
        self.loaded_platforms = []
        self.platforms_unloaded = False
        self.lifecycle_lock = asyncio.Lock()
        self.paused = False
        self.closed = False
        self.tasks = set()
        self.responses = set()
        self.streams = set()
        self.shutdown_error = None
        self._shutdown_task = None

    @property
    def audio_format(self):
        return self.client.audio_format

    @property
    def requires_audio_prepare(self):
        return self.settings.provider == "openrouter"

    def admit(self):
        if self.paused or self.closed:
            raise EntryUnavailableError("Voice entry is unavailable")

    def pause(self):
        self.paused = True

    def resume(self):
        if not self.closed:
            self.paused = False

    def register_task(self, task):
        if self.closed:
            task.cancel()
            raise EntryUnavailableError("Voice entry is closed")
        # Pausing admission must not stop an already admitted response's next read.
        self.tasks.add(task)

    def unregister_task(self, task):
        self.tasks.discard(task)

    def register_response(self, response):
        if self.closed:
            response.close()
            raise EntryUnavailableError("Voice entry is closed")
        self.responses.add(response)

    def unregister_response(self, response):
        self.responses.discard(response)

    async def _run(self, operation, *, admit=True):
        if admit:
            self.admit()
        task = asyncio.create_task(operation())
        try:
            self.register_task(task)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        task.add_done_callback(self.unregister_task)
        try:
            return await task
        finally:
            if task.done():
                self.unregister_task(task)

    async def transcribe(self, wav, model, language):
        return await self._run(lambda: self.client.transcribe(wav, model, language))

    async def synthesize(self, text, model, voice, language="auto"):
        return await self._run(lambda: self.client.synthesize(text, model, voice, language))

    async def synthesize_audio(self, text, model, voice, language="auto"):
        async def synthesize():
            method = getattr(self.client, "synthesize_audio", None)
            if method is not None:
                return await method(text, model, voice, language)
            return SynthesizedAudio(
                self.audio_format, await self.client.synthesize(text, model, voice, language)
            )

        return await self._run(synthesize)

    async def prepare_synthesize_stream(self, text, model, voice, language="auto"):
        stream = self.synthesize_stream(text, model, voice, language)
        await stream.prepare()
        return stream

    def synthesize_stream(self, text, model, voice, language="auto"):
        return ManagedAudioStream(
            self, lambda: self.client.synthesize_stream(text, model, voice, language)
        )

    def _close_responses(self):
        failures = []
        for response in tuple(self.responses):
            try:
                response.close()
            except Exception:
                failures.append(response)
            else:
                self.unregister_response(response)
        return failures

    async def shutdown(self):
        """Persist permanent closure; each attempt waits at most five seconds.

        A timed-out cleanup keeps running and remains observable for retry. Using
        asyncio.wait avoids waiting indefinitely for cancellation-resistant tasks.
        Platform unload is tracked separately and must not repeat after success.
        """
        self.closed = True
        self.paused = True
        self._close_responses()
        for task in tuple(self.tasks):
            task.cancel()
        if self._shutdown_task is None or self._shutdown_task.done():
            self._shutdown_task = asyncio.create_task(self._finish_shutdown())
        try:
            done, _ = await asyncio.wait({self._shutdown_task}, timeout=ENTRY_SHUTDOWN_TIMEOUT)
            if not done:
                raise ShutdownError("Voice entry cleanup timed out")
            try:
                self._shutdown_task.result()
            except Exception:
                raise ShutdownError("Voice entry cleanup failed") from None
        except asyncio.CancelledError:
            self.shutdown_error = ShutdownError("Voice entry cleanup was interrupted")
            raise
        except ShutdownError as err:
            self.shutdown_error = err
            raise
        self.shutdown_error = None

    async def _finish_shutdown(self):
        tasks = tuple(self.tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if task.done():
                self.unregister_task(task)
        failures = []
        for stream in tuple(self.streams):
            try:
                await stream.aclose()
            except Exception:
                failures.append(stream)
        failures.extend(self._close_responses())
        if failures or self.tasks or self.responses or self.streams:
            raise ShutdownError("Voice entry has unfinished resource cleanup")


class ManagedAudioStream:
    """Admit/register on first consumption; explicit close or unload releases ownership."""

    def __init__(self, runtime, create_stream):
        self._runtime = runtime
        self._create_stream = create_stream
        self.extension = runtime.audio_format
        self._stream = None
        self._pending = None
        self._cleanup = None
        self._closed = False
        self._expiry = None
        self._expired = False

    def __aiter__(self):
        return self

    def _start(self):
        if self._stream is None:
            self._runtime.admit()
            self._stream = self._create_stream()
            self._runtime.streams.add(self)

    async def prepare(self):
        """Register ownership before dynamic-format HTTP preparation begins."""
        if self._closed:
            raise EntryUnavailableError("Voice stream is closed")
        if self._pending is not None:
            raise RuntimeError("Audio stream already has a pending consumer")
        self._start()
        try:
            self._pending = asyncio.create_task(
                self._runtime._run(self._stream.prepare, admit=False)
            )
            await self._pending
            self.extension = self._stream.extension
            self._expiry = asyncio.get_running_loop().call_at(self._stream.deadline, self._expire)
            return self
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pending = None

    def _expire(self):
        self._expired = True
        self._closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish_close())

    async def __anext__(self):
        if self._expired:
            raise STTError(
                "Audio response deadline exceeded",
                diagnostic=FailureDiagnostic(FailureCategory.TIMEOUT, FailurePhase.READ),
            )
        if self._closed:
            raise StopAsyncIteration
        if self._pending is not None:
            raise RuntimeError("Audio stream already has a pending consumer")
        self._start()
        try:
            self._pending = asyncio.create_task(
                self._runtime._run(lambda: anext(self._stream), admit=False)
            )
            chunk = await self._pending
            self.extension = self._stream.extension
            return chunk
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pending = None

    async def aclose(self):
        self._closed = True
        if self._expiry is not None:
            self._expiry.cancel()
        if self._cleanup is None or (
            self._cleanup.done() and self._cleanup.exception() is not None
        ):
            self._cleanup = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._cleanup)

    async def _finish_close(self):
        if self._stream is not None:
            await self._stream.aclose()
        pending = self._pending
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        self._runtime.streams.discard(self)
