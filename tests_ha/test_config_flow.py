"""Actual HA selectors, connection drafts, and STT-to-TTS options regression."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector
from yarl import URL

from custom_components.universal_stt.const import PROVIDER_URLS
from custom_components.universal_stt.contracts import Endpoint
from custom_components.universal_stt.errors import AuthenticationError, STTError
from custom_components.universal_stt.http_session import async_get_voice_session
from custom_components.universal_stt.transport import Transport

pytestmark = pytest.mark.asyncio


def fields(form):
    return {key.schema: value for key, value in form["data_schema"].schema.items()}


@pytest_asyncio.fixture
async def catalogs():
    """Only loopback catalogs; first response sets a cookie that must never be replayed."""
    server = SimpleNamespace(requests=[], status=200)

    async def respond(request):
        server.requests.append((request.query.get("output_modalities"), dict(request.headers)))
        if server.status != 200:
            return web.Response(status=server.status, text="private-provider-body")
        feature = request.query.get("output_modalities")
        response = web.json_response(
            {
                "data": [
                    {
                        "id": "known-stt" if feature == "transcription" else "known-tts",
                        "name": "STT" if feature == "transcription" else "TTS",
                        "supported_voices": ["alloy"],
                    }
                ]
            }
        )
        response.set_cookie("catalog_cookie", "unrelated-cookie-value")
        return response

    app = web.Application()
    app.router.add_get("/models", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server.base = f"http://localhost:{runner.addresses[0][1]}"
    try:
        yield server
    finally:
        await runner.cleanup()


async def finish_both(hass, result, manager):
    result = await manager.async_configure(result["flow_id"], {"model": "known-stt"})
    assert result["step_id"] == "tts"
    result = await manager.async_configure(result["flow_id"], {"tts_model": "known-tts"})
    assert result["step_id"] == "voice"
    result = await manager.async_configure(result["flow_id"], {"voice": "alloy"})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    return result


async def test_initial_form_selects_only_provider_and_mode(hass):
    result = await hass.config_entries.flow.async_init("universal_stt", context={"source": "user"})
    assert set(fields(result)) == {"provider", "mode"}
    provider = fields(result)["provider"]
    assert isinstance(provider, SelectSelector)
    assert [item["value"] for item in provider.config["options"]] == [
        "openai",
        "gemini",
        "xai",
        "openrouter",
        "custom",
    ]
    assert result["data_schema"]({}) == {"provider": "openai", "mode": "both"}


@pytest.mark.parametrize("service", ("openai", "gemini", "xai", "openrouter", "custom"))
@pytest.mark.parametrize("mode", ("stt", "tts", "both"))
async def test_connection_form_contains_only_selected_service_and_feature_fields(
    hass, service, mode
):
    result = await hass.config_entries.flow.async_init("universal_stt", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": service, "mode": mode}
    )
    assert result["step_id"] == "connection"
    expected = {"api_key", "discover"}
    if mode != "stt":
        expected.add("tts_streaming")
    if service == "custom":
        expected.add("base_url")
        for feature in ("stt", "tts"):
            if mode in {feature, "both"}:
                expected.update(
                    {
                        f"{feature}_url",
                        f"{feature}_api_key",
                        f"{feature}_models_url",
                        f"{feature}_models_api_key",
                    }
                )
    assert set(fields(result)) == expected


async def test_existing_legacy_provider_default_and_blank_key_are_preserved(hass, add_entry):
    entry = await add_entry("openrouter", "stt", base_url=PROVIDER_URLS["openrouter"])
    legacy = dict(entry.data)
    legacy.pop("provider")
    legacy.pop("mode")
    hass.config_entries.async_update_entry(entry, data=legacy)
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {"provider": "openrouter", "mode": "stt"}
    result = await manager.async_configure(
        result["flow_id"], {"provider": "openrouter", "mode": "stt"}
    )
    assert "clear_api_key" in fields(result)
    result = await manager.async_configure(result["flow_id"], {"discover": False})
    result = await manager.async_configure(result["flow_id"], {"model": "known-stt"})
    await hass.async_block_till_done()
    assert entry.options["api_key"] == legacy["api_key"]


async def test_existing_stt_to_both_with_cookie_setting_catalog(
    hass, add_entry, catalogs, provider
):
    with patch(
        "custom_components.universal_stt.settings.PROVIDER_URLS",
        {**PROVIDER_URLS, "openrouter": catalogs.base},
    ):
        entry = await add_entry("openrouter", "stt", base_url=catalogs.base, model="known-stt")
        saved = deepcopy(dict(entry.data))
        runtime = entry.runtime_data
        shared = async_get_clientsession(hass)
        shared.cookie_jar.update_cookies(
            {"other_integration": "retain"}, URL("https://other.example")
        )
        cookies_before = list(shared.cookie_jar)
        manager = hass.config_entries.options
        result = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(
            result["flow_id"], {"provider": "openrouter", "mode": "both"}
        )
        assert result["step_id"] == "connection"
        assert set(fields(result)) == {"api_key", "clear_api_key", "discover", "tts_streaming"}
        result = await manager.async_configure(result["flow_id"], {})
        assert result["step_id"] == "model" and not result["errors"]
        assert dict(entry.data) == saved and not entry.options and entry.runtime_data is runtime
        assert [feature for feature, _ in catalogs.requests] == ["transcription", "speech"]
        assert all("Cookie" not in headers for _, headers in catalogs.requests)
        assert list(shared.cookie_jar) == cookies_before
        session = async_get_voice_session(hass)
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
        assert not list(session.cookie_jar)
        assert runtime.client.transport._session is session
        result = await manager.async_configure(result["flow_id"], {"model": "known-stt"})
        assert result["step_id"] == "tts"
        result = await manager.async_configure(result["flow_id"], {"tts_model": "known-tts"})
        assert result["step_id"] == "voice"
        assert entry.runtime_data is runtime and not entry.options
        await manager.async_configure(result["flow_id"], {"voice": "alloy"})
        await hass.async_block_till_done()
        assert entry.options["mode"] == "both" and entry.options["api_key"] == saved["api_key"]
        assert entry.runtime_data is not runtime and runtime.closed
        assert entry.runtime_data.client.transport._session is session and not session.closed
        assert not provider.requests


@pytest.mark.parametrize("recover", ("retry", "manual"))
async def test_stt_upgrade_catalog_failure_can_retry_or_finish_manually(
    hass, add_entry, catalogs, recover
):
    with patch(
        "custom_components.universal_stt.settings.PROVIDER_URLS",
        {**PROVIDER_URLS, "openrouter": catalogs.base},
    ):
        entry = await add_entry("openrouter", "stt", base_url=catalogs.base)
        runtime = entry.runtime_data
        saved = deepcopy(dict(entry.data))
        manager = hass.config_entries.options
        result = await manager.async_init(entry.entry_id)
        result = await manager.async_configure(
            result["flow_id"], {"provider": "openrouter", "mode": "both"}
        )
        catalogs.status = 503
        result = await manager.async_configure(
            result["flow_id"], {"api_key": "replacement-local-key"}
        )
        assert result["step_id"] == "connection" and result["errors"] == {"base": "cannot_connect"}
        assert "private-provider-body" not in str(result["errors"])
        assert dict(entry.data) == saved and not entry.options and entry.runtime_data is runtime
        catalogs.status = 200
        result = await manager.async_configure(result["flow_id"], {"discover": recover == "retry"})
        assert result["step_id"] == "model" and not result["errors"]
        await finish_both(hass, result, manager)
        assert entry.options["api_key"] == "replacement-local-key"
        assert len(catalogs.requests) == (3 if recover == "retry" else 1)


async def test_provider_switch_does_not_offer_or_forward_saved_key(hass, add_entry):
    entry = await add_entry("openrouter", "stt", base_url=PROVIDER_URLS["openrouter"])
    runtime = entry.runtime_data
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    result = await manager.async_configure(result["flow_id"], {"provider": "openai", "mode": "stt"})
    assert set(fields(result)) == {"api_key", "discover"}
    result = await manager.async_configure(result["flow_id"], {"discover": False})
    assert entry.runtime_data is runtime and not entry.options
    result = await manager.async_configure(result["flow_id"], {"model": "whisper-1"})
    await hass.async_block_till_done()
    assert entry.options["provider"] == "openai" and entry.options["api_key"] == ""


@pytest.mark.parametrize(
    "error, expected",
    (
        (ValueError("session-error"), "cannot_connect"),
        (STTError("private-body"), "cannot_connect"),
        (AuthenticationError("private-key"), "invalid_auth"),
    ),
)
async def test_discovery_errors_are_not_labeled_invalid_url(hass, error, expected):
    manager = hass.config_entries.flow
    result = await manager.async_init("universal_stt", context={"source": "user"})
    result = await manager.async_configure(
        result["flow_id"], {"provider": "openai", "mode": "both"}
    )
    with patch(
        "custom_components.universal_stt.config_flow.discover_for_settings",
        AsyncMock(side_effect=error),
    ):
        result = await manager.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": expected}


async def test_voice_session_survives_first_entry_unload_and_closes_only_at_ha_stop(
    hass, add_entry, provider
):
    # First construction occurs inside HA's config-entry context, not a flow.
    first = await add_entry("custom", "tts")
    session = async_get_voice_session(hass)
    second = await add_entry("custom", "tts")
    assert first.runtime_data.client.transport._session is session
    assert second.runtime_data.client.transport._session is session
    assert await hass.config_entries.async_unload(first.entry_id)
    assert not session.closed and async_get_voice_session(hass) is session
    assert (
        await second.runtime_data.synthesize("session lifecycle", "speech-model", "Kore")
        == provider.audio["mp3"]
    )
    assert "Cookie" not in provider.requests[-1][2]
    await hass.async_stop(force=True)
    assert session.closed


async def test_shared_session_cookie_guard_remains_and_voice_session_ignores_set_cookie(
    hass, catalogs
):
    shared = async_get_clientsession(hass)
    endpoint = Endpoint(f"{catalogs.base}/models", "local-test-key")
    transport = Transport(shared)
    await transport.request_json("GET", endpoint)
    assert shared.cookie_jar.filter_cookies(URL(endpoint.url))
    cookies = list(shared.cookie_jar)
    with pytest.raises(ValueError, match="session cookies"):
        await transport.request_json("GET", endpoint)
    assert len(catalogs.requests) == 1
    voice = Transport(async_get_voice_session(hass))
    await voice.request_json("GET", endpoint)
    await voice.request_json("GET", endpoint)
    assert len(catalogs.requests) == 3
    assert all("Cookie" not in headers for _, headers in catalogs.requests)
    assert list(shared.cookie_jar) == cookies


@pytest.mark.parametrize(
    "service, mode", (("custom", "stt"), ("custom", "tts"), ("openai", "both"))
)
async def test_options_clear_controls_are_visible_only_for_relevant_keys(
    hass, add_entry, service, mode
):
    entry = await add_entry(
        service,
        "both",
        stt_api_key="stt-key",
        tts_api_key="tts-key",
        stt_models_api_key="catalog-stt",
        tts_models_api_key="catalog-tts",
    )
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    result = await manager.async_configure(result["flow_id"], {"provider": service, "mode": mode})
    clear = {name for name in fields(result) if name.startswith("clear_")}
    expected = {"clear_api_key"}
    if service == "custom":
        expected.update({f"clear_{mode}_api_key", f"clear_{mode}_models_api_key"})
    assert clear == expected
    connection = {"discover": False, "clear_api_key": True}
    if service == "custom":
        connection[f"clear_{mode}_api_key"] = True
    result = await manager.async_configure(result["flow_id"], connection)
    if mode == "both":
        await finish_both(hass, result, manager)
    elif mode == "stt":
        await manager.async_configure(result["flow_id"], {"model": "known-stt"})
    else:
        result = await manager.async_configure(result["flow_id"], {"tts_model": "known-tts"})
        await manager.async_configure(result["flow_id"], {"voice": "alloy"})
    await hass.async_block_till_done()
    assert entry.options["api_key"] == ""
    if service == "custom":
        assert entry.options[f"{mode}_api_key"] == ""


@pytest.mark.parametrize(
    "service, connection, expected",
    (
        ("custom", {"base_url": "file:///private"}, "invalid_url"),
        ("custom", {"base_url": "https://voice.example/v1", "tts_url": "not-a-url"}, "invalid_url"),
        ("openai", {"api_key": "key\r\ninjection"}, "invalid_config"),
    ),
)
async def test_relevant_url_and_key_validation_have_distinct_errors(
    hass, service, connection, expected
):
    manager = hass.config_entries.flow
    result = await manager.async_init("universal_stt", context={"source": "user"})
    result = await manager.async_configure(result["flow_id"], {"provider": service, "mode": "both"})
    result = await manager.async_configure(result["flow_id"], {**connection, "discover": False})
    assert result["step_id"] == "connection" and result["errors"] == {"base": expected}
