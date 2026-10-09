"""xAI native audio payloads and live transcription/voice choices."""

import aiohttp

from .catalog import snapshot, voice_ids
from .client import STTClient
from .contracts import Endpoint, normalize_base_url
from .errors import ResponseError, STTError


class XAIClient(STTClient):
    """Native TTS takes a voice and locale; its internal model ID is not transmitted."""

    def speech_body(self, text, model, voice, language):
        return {
            "text": text,
            "voice_id": voice,
            "language": language,
            "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000},
        }

    async def transcribe(self, wav, model, language):
        form = aiohttp.FormData()
        form.add_field("model", model)
        form.add_field("language", language)
        # Native xAI requires file after all text fields.
        form.add_field("file", wav, filename="speech.wav", content_type="audio/wav")
        payload = await self.transport.request_json(
            "POST", self.settings.inference_endpoint("stt"), data=form
        )
        text = payload.get("text")
        if not isinstance(text, str):
            raise STTError("Service response has no transcript")
        return text.strip()

    async def discover_models(self, modality="transcription"):
        if modality not in {"transcription", "speech"}:
            raise ValueError("Invalid audio modality")
        path = "models" if modality == "transcription" else "tts/voices"
        endpoint = Endpoint(
            f"{normalize_base_url(self.settings.base_url)}/{path}", self.settings.api_key
        )
        payload = await self.transport.request_json("GET", endpoint)
        if modality == "transcription":
            items = payload.get("data")
            if not isinstance(items, list):
                raise ResponseError("Invalid model catalog")
            models = {
                item["id"]: item["id"]
                for item in items
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"].startswith("grok-voice-transcribe-")
            }
            return snapshot(models)
        items = payload.get("voices")
        if not isinstance(items, list):
            raise ResponseError("Invalid voice catalog")
        voices = voice_ids([item.get("voice_id") for item in items if isinstance(item, dict)])
        return snapshot({"xai-tts": "xAI Text to Speech"}, provider_voices=voices)
