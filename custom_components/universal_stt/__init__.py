"""Universal Voice entry composition and Home Assistant lifecycle boundaries."""

from homeassistant.const import Platform

from .audio_formats import load_audio_formats
from .client import create_voice_client
from .errors import EntryUnavailableError, ShutdownError
from .http_session import async_get_voice_session
from .runtime import EntryRuntime
from .settings import VoiceSettings
from .transport import Transport

PLATFORMS = [Platform.STT, Platform.TTS]


async def async_setup_entry(hass, entry):
    """Build the provider without discovery or speech; rollback owned resources on failure."""
    previous = getattr(entry, "runtime_data", None)
    if isinstance(previous, EntryRuntime):
        if not previous.closed:
            raise EntryUnavailableError("Voice entry is already active")
        # Keep failed rollback resources reachable until cleanup has really succeeded.
        if not await async_unload_entry(hass, entry):
            raise ShutdownError("Unable to finish voice platform rollback")
    settings = VoiceSettings.from_entry(entry)
    runtime = EntryRuntime(settings)
    entry.runtime_data = runtime
    runtime.loaded_platforms = [
        platform for platform in PLATFORMS if settings.enabled(platform.value)
    ]
    try:
        runtime.client = create_voice_client(
            Transport(async_get_voice_session(hass), runtime), settings
        )
        if settings.provider == "openrouter" and settings.enabled("tts"):
            runtime.client.audio_formats = await hass.async_add_executor_job(load_audio_formats)
        await hass.config_entries.async_forward_entry_setups(entry, runtime.loaded_platforms)
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    except BaseException:
        try:
            runtime.platforms_unloaded = await hass.config_entries.async_unload_platforms(
                entry, runtime.loaded_platforms
            )
        finally:
            await runtime.shutdown()
        raise
    return True


async def async_unload_entry(hass, entry):
    """Pause admission before platform unload; failed unload leaves active requests intact."""
    runtime = entry.runtime_data
    async with runtime.lifecycle_lock:
        if not runtime.platforms_unloaded:
            runtime.pause()
            try:
                unloaded = await hass.config_entries.async_unload_platforms(
                    entry, runtime.loaded_platforms
                )
            except BaseException:
                runtime.resume()
                raise
            if not unloaded:
                runtime.resume()
                return False
            runtime.platforms_unloaded = True
        await runtime.shutdown()
    return True


async def async_reload_entry(hass, entry):
    """Apply a completed options snapshot through HA's existing reload lifecycle."""
    await hass.config_entries.async_reload(entry.entry_id)
