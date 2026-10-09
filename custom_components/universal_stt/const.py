"""Constants for Universal STT."""

from types import MappingProxyType

DOMAIN = "universal_stt"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
MAX_AUDIO_BYTES = 16000 * 2 * 120

PROVIDER_URLS = MappingProxyType(
    {
        "gemini": "https://generativelanguage.googleapis.com/v1beta",
        "openrouter": OPENROUTER_URL,
        "openai": "https://api.openai.com/v1",
        "xai": "https://api.x.ai/v1",
    }
)
HTTP_TIMEOUT = 60
AUDIO_COLLECTION_TIMEOUT = 130
MAX_TTS_AUDIO_BYTES = 20 * 1024 * 1024
MAX_TTS_TEXT_BYTES = 64 * 1024
MAX_SSE_EVENT_BYTES = 1024 * 1024
MAX_SSE_WIRE_BYTES = 40 * 1024 * 1024
ENTRY_SHUTDOWN_TIMEOUT = 5
