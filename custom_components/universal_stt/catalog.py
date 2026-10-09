"""Translate provider catalogs into immutable choices with explicit provenance."""

from .contracts import CatalogSnapshot
from .errors import ResponseError

OPENAI_VOICES = (
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "ballad",
    "verse",
    "marin",
    "cedar",
)


def voice_ids(values):
    """Keep distinct nonempty IDs without treating a list as a capability guarantee."""
    if not isinstance(values, list):
        return ()
    return tuple(
        dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip())
    )


def snapshot(models, voices=None, *, provider_voices=(), voices_source="live"):
    return CatalogSnapshot(
        dict(sorted(models.items(), key=lambda item: item[1].casefold())),
        voices or {},
        provider_voices,
        "live",
        voices_source,
    )


def custom_catalog(payload):
    items = payload.get("data", payload.get("models"))
    if not isinstance(items, list):
        raise ResponseError("Expected a data or models array")
    models, voices = {}, {}
    for item in items:
        if isinstance(item, str):
            model_id, label = item.strip(), item.strip()
        elif isinstance(item, dict):
            model_id = item.get("id", item.get("name"))
            if not isinstance(model_id, str):
                continue
            model_id = model_id.strip()
            label = str(item.get("displayName") or item.get("name") or model_id)
            if isinstance(item.get("supported_voices"), list):
                voices[model_id] = voice_ids(item["supported_voices"])
        else:
            continue
        if model_id:
            models[model_id] = label
    if items and not models:
        raise ResponseError("Catalog has no recognizable model IDs")
    return snapshot(models, voices)


def compatible_catalog(payload, provider, modality):
    items = payload.get("data")
    if not isinstance(items, list):
        raise ResponseError("Invalid model catalog")
    models, voices = {}, {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        architecture = item.get("architecture") or {}
        if not isinstance(model_id, str) or not model_id or not isinstance(architecture, dict):
            continue
        modalities = architecture.get("output_modalities")
        if modalities is not None and (
            not isinstance(modalities, list) or modality not in modalities
        ):
            continue
        if provider == "openai":
            stt = model_id == "whisper-1" or model_id.startswith(
                ("gpt-4o-transcribe", "gpt-4o-mini-transcribe")
            )
            speech = model_id.startswith(("tts-1", "gpt-4o-mini-tts"))
            if not (stt if modality == "transcription" else speech) or "diarize" in model_id:
                continue
            if speech:
                voices[model_id] = (
                    OPENAI_VOICES if model_id.startswith("gpt-4o-mini-tts") else OPENAI_VOICES[:9]
                )
        models[model_id] = str(item.get("name") or model_id)
        if provider != "openai" and isinstance(item.get("supported_voices"), list):
            voices[model_id] = voice_ids(item["supported_voices"])
    return snapshot(models, voices, voices_source="documented" if provider == "openai" else "live")


def gemini_models(items, modality, voices=()):
    models = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        model_id = item["name"].removeprefix("models/")
        if not model_id.startswith("gemini-"):
            continue
        is_tts = "tts" in model_id.split("-")
        accepted = (
            is_tts
            if modality == "speech"
            else (
                not is_tts
                and any(part in model_id for part in ("flash", "pro"))
                and not any(part in model_id for part in ("image", "live", "audio"))
            )
        )
        if accepted:
            models[model_id] = str(item.get("displayName") or model_id)
    return snapshot(models, provider_voices=voices)


async def discover_for_settings(client, settings):
    """Fetch only enabled features; one custom URL/effective-auth pair per submission."""
    catalogs, fetched = {}, {}
    for feature, modality in (("stt", "transcription"), ("tts", "speech")):
        if not settings.enabled(feature):
            continue
        if settings.provider == "custom":
            endpoint = settings.catalog_endpoint(feature)
            if endpoint is None:
                catalogs[feature] = CatalogSnapshot()
                continue
            identity = (endpoint.url, endpoint.api_key, endpoint.authentication)
            if identity not in fetched:
                fetched[identity] = await client.discover_custom_models(endpoint)
            catalogs[feature] = fetched[identity]
        else:
            catalogs[feature] = await client.discover_models(modality)
    return catalogs
