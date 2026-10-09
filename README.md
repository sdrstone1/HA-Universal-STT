<p align="center"><img src="custom_components/universal_stt/brand/icon@2x.png" alt="HA Universal Voice icon" width="128"></p>

# HA Universal Voice · HA 유니버설 보이스

[English](#english) · [한국어](#한국어) · [Release notes / 변경 사항](CHANGELOG.md)

## English

Speech-to-text and text-to-speech for Home Assistant Assist, using OpenAI, Google Gemini, xAI (Grok), OpenRouter, or an OpenAI-compatible audio API server.

**Version: 0.3.0. Requires Home Assistant 2026.3.0 or newer. Automated integration tests target HA 2026.3.0 and 2026.10.0. OpenRouter TTS playback has been confirmed on the installed HA with Gemini, Mistral, and MiniMax Speech 2.8 HD. OpenAI and xAI live playback has not been tested because API keys are unavailable.**

### Features

- Enable STT, TTS, or both with a shared API connection.
- Discover OpenRouter transcription and speech models separately; select or enter model IDs.
- Choose TTS voices from the model catalog, or enter a custom voice ID.
- Edit the API connection, models, and voice through the integration's options.
- Use the STT and TTS entities separately in Assist. Multiple entries can use different services or keys.
- Keep existing STT entries and entity IDs when upgrading from Universal STT.
- Optionally stream TTS audio after collecting the complete input text; output streaming is off by default.
- English and Korean setup screens, plus a bundled integration icon for HA 2026.3 or newer.

### Install with HACS

HACS must already be installed. This is a **custom repository**, not a listing in the default HACS catalog.

1. Open **HACS → ⋮ → Custom repositories**.
2. Enter `https://github.com/sdrstone1/HA-Universal-STT`.
3. Select **Integration** as the type and click **Add**.
4. Find **HA Universal Voice**, open it, and choose **Download**. Select the published release version when available; the default branch contains development changes.
5. **Restart Home Assistant.** HACS's message about restarting before changes to `custom_components` apply is normal.
6. Go to **Settings → Devices & services → Add integration** and search for **HA Universal Voice**.

The repository URL and installation directory remain unchanged for existing users. The integration still installs into `/config/custom_components/universal_stt/`.

For a manual installation, copy `custom_components/universal_stt` into `/config/custom_components/`, restart HA, and add the integration as above.

### Providers

| Provider | STT / TTS | Discovery |
| --- | --- | --- |
| OpenAI | Audio Transcriptions / Speech endpoints | Live `/models`, filtered to known audio families; documented built-in voices |
| Google Gemini | Native Interactions API: audio transcription / WAV speech | Paginated live `/models` and `/voices`; separate model candidates |
| xAI (Grok) | Native `/stt` and `/tts` | Live `/models`, filtered to transcription IDs; live `/tts/voices`; no TTS model parameter |
| OpenRouter | Audio-compatible models | Live filtered model and voice catalog |
| OpenAI-compatible | Requires the selected audio endpoint, not just chat compatibility | Optional catalog URL; manual model and voice IDs |

Preset providers set their own API URL. When changing provider or URL, enter a new API key; the saved key is not copied to the new destination. Add separate STT and TTS entries to mix providers. xAI's `xai-tts` identifier is internal and is never sent as a model name.

OpenAI discovery does not infer capabilities for unknown models. Enter new compatible model IDs manually. Realtime-only models are not supported by this HTTP audio implementation. OpenAI has [announced retirement dates](https://developers.openai.com/api/docs/deprecations) for legacy STT models and TTS snapshots; check availability before choosing them.

For TTS testing, start with xAI's `eve` and Korean (`ko`), or OpenAI's `gpt-4o-mini-tts` with `marin` or `cedar`. These are documentation-based starting points, not a listening benchmark. OpenAI voices are optimized for English. Test Korean names, numbers, and short home-control replies with your own speaker.

### Set up STT and TTS

1. Choose **OpenAI**, **Google Gemini**, **xAI (Grok)**, **OpenRouter**, or **OpenAI-compatible**, then **STT + TTS**, **STT**, or **TTS**.
2. Continue to the connection screen and enter the API key. Preset services show no custom URL or dedicated key fields. Only **OpenAI-compatible** shows the API root, catalog and inference fields for the enabled features. TTS streaming appears only when TTS is enabled. OpenRouter uses `https://openrouter.ai/api/v1`; a custom server needs its API root, such as `http://server:8000/v1`. Do not append `/audio/speech` or `/audio/transcriptions`.
3. Select an STT model if STT is enabled.
4. Select a TTS model and a supported voice if TTS is enabled. xAI skips model selection and starts with its default voice, `eve`. Other providers require a voice ID.
5. In **Settings → Voice assistants**, edit your Assist pipeline. Select the integration's STT entity under speech-to-text and TTS entity under text-to-speech, then choose the language and voice as applicable.

**TTS output streaming** is disabled by default. Enable it in the connection form to forward audio as it arrives. The integration always collects and validates the full input text first, including when Assist supplies a text stream. It does not synthesize individual sentences as they arrive.

New entries start with OpenAI selected. Existing entries keep their saved service; older entries without a service field retain OpenRouter.

Automatic discovery runs during setup and when you submit the options connection form with discovery enabled. If it fails, retry or disable discovery and enter model and voice IDs manually. Custom servers fetch a catalog only when a catalog URL is entered; otherwise they use manual IDs. Saving configuration does not make a paid speech request: model, voice, and endpoint compatibility are verified when used.

For separate STT and TTS providers, add two entries: one STT-only and one TTS-only.

### Custom model catalog

For **OpenAI-compatible**, configure **STT model catalog URL** and **TTS model catalog URL** independently. Leave either blank to enter that model ID manually. Both may use the same URL; an identical URL/key pair is fetched only once per connection submission. Only enabled features are fetched. You can always enter a model ID not in the catalog. Disable discovery to continue manually after an error.

Each catalog accepts GET and must return a JSON object containing a `data` or `models` array. Entries may be ID strings or objects with `id`/`name`; `displayName` labels and `supported_voices` are optional. Custom pagination and arbitrary JSON mappings are not supported. Catalog membership does not guarantee audio capability. These fields configure **model listing**. Separate **STT inference URL** and **TTS inference URL** fields accept full POST URLs. When blank, the defaults are `<base URL>/audio/transcriptions` and `<base URL>/audio/speech`. Each inference endpoint has an optional Bearer key; without it, the shared key is used only on the same scheme, host and port. Changing a URL clears its saved key unless a replacement is entered. Payloads must still follow the OpenAI-compatible audio protocol; changing the URL does not translate arbitrary APIs.

Each catalog has an optional Bearer API key. A blank field preserves its saved key when editing the same connection and catalog URL. Without a catalog key, the speech key is reused only for the same scheme, host and port; other origins receive no key. Changing a catalog URL clears its key unless a replacement is entered. Redirects are not followed. Existing shared catalog settings populate both fields on edit, and are saved in the separate format only when you finish configuration.

### Google Gemini

Select **Google Gemini** and enter a Google AI Studio API key. The preset uses `https://generativelanguage.googleapis.com/v1beta` and the `x-goog-api-key` header. `/models` is fetched through all pages once during discovery, then split into STT and TTS candidates by model family. This is not a complete capability matrix; manual IDs remain available. Select models compatible with Google's Interactions API.

STT sends inline WAV audio to `/interactions` with instructions to return only a verbatim transcript in the original language. TTS sends text and a voice to the same endpoint and requests WAV, which is passed to Home Assistant as WAV rather than MP3. Both use `store: false`. TTS language follows the input text; selecting an Assist language does not translate it. `GET /voices` fetches the available built-in and stored custom voices through all pages. Voice IDs remain manually editable. A voice’s primary `language_code` is not treated as the model’s complete supported-language list. Gemini speech quality and real HA playback still require user testing.

### Catalog endpoints checked on 2026-10-09

| Service | GET endpoint | Limitations |
| --- | --- | --- |
| OpenRouter | `https://openrouter.ai/api/v1/models?output_modalities=transcription` or `speech` | Server-side modality filtering; voices when listed |
| OpenAI | `https://api.openai.com/v1/models` | Live IDs, no standard STT/TTS capability field; this integration filters known families |
| xAI | `https://api.x.ai/v1/models`; `https://api.x.ai/v1/tts/voices` | STT IDs filtered by known family; TTS selects a voice rather than a model |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/models` | `models[]` and `nextPageToken`; generation methods alone do not establish STT/TTS support |


Sources: [OpenRouter catalog](https://openrouter.ai/docs/api/api-reference/models/get-models), [OpenAI catalog](https://developers.openai.com/api/reference/resources/models/methods/list), [xAI catalog](https://docs.x.ai/developers/rest-api-reference/inference/models), [Gemini catalog](https://ai.google.dev/api/models), [Gemini audio](https://ai.google.dev/gemini-api/docs/audio), [Gemini TTS](https://ai.google.dev/gemini-api/docs/speech-generation).

### Upgrade an existing STT installation

1. Open the integration in HACS and choose **⋮ → Update information**, then update or redownload the development branch.
2. Restart Home Assistant.
3. Open the existing integration under **Settings → Devices & services** and select **Configure**.
4. Change the feature selection from **STT** to **STT + TTS**. Keep the STT model, then select the TTS model and voice.
5. Save and select the new TTS entity in your Assist pipeline.

Existing STT entries stay STT-only until TTS is configured. You do not need to delete them. Leave the API key field blank to keep the saved key; use **Clear saved API key** to remove it for an unauthenticated server. Saving options reloads the integration.

Completed options replace the previous settings snapshot; deleted fields are not merged back from the original entry. Legacy shared catalog fields are read into the separate STT/TTS fields only when those fields are absent. Finishing configuration removes legacy and disabled-feature fields; cancelling or failing a flow leaves saved settings intact. The domain `universal_stt`, installation directory, and existing entity IDs remain stable.

### Validate TTS on your installation

Try a short message from **Developer tools → Actions → `tts.speak`**. Replace both entity IDs with your actual entities:

```yaml
action: tts.speak
target:
  entity_id: tts.your_universal_voice_entity
data:
  media_player_entity_id: media_player.your_speaker
  message: "Hello. This is a speech test."
  language: en
  cache: false
```

Then test an Assist conversation and confirm that the existing STT still works. If playback fails, note the model ID, voice ID, HA version, and error message; do not share your API key. A successful API response does not by itself verify speaker playback.

### Languages and voices

OpenRouter, OpenAI, and compatible STT send the pipeline's language code to `/audio/transcriptions`; xAI uses `/stt`. Gemini sends WAV to `/interactions` and includes the expected language in its transcription instruction. The old single-language setup restriction no longer applies.

OpenRouter, OpenAI, and compatible TTS use `/audio/speech` with text, model, and voice. OpenAI and compatible servers receive explicit MP3 output. OpenRouter explicitly requests PCM by default, with exact model overrides in `custom_components/universal_stt/model_audio_formats.json` (`defaults.request_format` and each model’s `request_format`). MiniMax Speech 2.8 HD requests MP3 because its OpenRouter streaming path rejects PCM. Unlisted models use the default; this is a request policy, not a guarantee of support. Playback uses the actual response format: MP3 and WAV pass through with the matching extension; signed 16-bit little-endian PCM is wrapped as WAV. PCM rate and channels come from the response Content-Type. No model-specific PCM metadata defaults are currently configured. Missing rate or channels therefore produces an error rather than an assumed value. A metadata fallback must not be added solely because a model emits PCM; first establish that the OpenRouter response omits it and that the replacement value applies to that path. Unknown or octet-stream media types require a bounded MP3/WAV signature; unidentified raw bytes fail safely. Format probe logs contain HTTP status and an allowlisted media type. PCM response metadata logs contain only validated rate and channels from the response header, or fixed missing/invalid states; raw headers and speech content are not logged. **The shared speech API has no language parameter:** the model reads the input text, and some voices determine the language or accent. Choosing a language in Assist does not translate text or override a voice's language. Choose a compatible model and voice. xAI uses `/tts` and receives the Assist language explicitly.

STT and non-xAI TTS expose 184 ISO 639-1 language codes to Assist. xAI TTS uses its documented language list, including regional codes such as `pt-PT` and `es-MX`. These are selectable codes, **not a claim that every model or voice supports all 184 languages**. Model-specific language filtering is not implemented because the model catalog has no documented common language list. Voice lists are stored at setup; reopen Configure with discovery enabled to refresh them.

Gemini voices come from its Voices API. OpenAI built-in voices come from its documented list; no built-in GET voice catalog is used. Manual voice IDs remain available.

### Audio, privacy, and limits

STT collects at most 120 seconds of 16 kHz, 16-bit, mono PCM, converts it to WAV, and uploads one utterance. Unsupported metadata, empty or incomplete samples, and oversized input fail before the provider call. Input collection has a 130-second timeout; STT returns one final transcript, without partial transcription.

TTS accepts at most 64 KiB of UTF-8 text and rejects empty input. Text streams have a 130-second collection timeout even when output streaming is off. These collection limits do not bound total request time: an upstream input iterator's asynchronous cleanup and the later provider request can extend it. TTS audio is limited to 20 MiB and HTTP requests to 60 seconds. No automatic retries are performed; a failed or interrupted output stream is not replaced with a second complete-audio request.

With output streaming off, TTS returns complete audio with its detected extension. OpenRouter PCM receives an exact-length WAV header. With streaming on, OpenRouter PCM receives an unknown-length WAV header and complete channel frames progressively, so playback can begin before generation finishes. OpenRouter prepares a bounded response prefix before returning its extension to HA; an unconsumed prepared response is closed at the same 60-second deadline or entry unload. OpenAI, xAI, and compatible servers keep lazy MP3 output; Gemini PCM events remain streaming WAV. The model format JSON is loaded in the HA executor only for OpenRouter entries with TTS, and changes apply after reload or restart. Its supported-format lists document this integration’s OpenRouter speech path and validate the chosen request format; they do not restrict actual responses. Add exact model overrides only when needed, then reload the integration or restart HA. Actual OpenRouter playback is confirmed for Gemini, Mistral, and MiniMax Speech 2.8 HD; other provider/model combinations are not implied by those results. Gemini stream safeguards additionally limit each SSE event to 1 MiB and wire data to 40 MiB. These are integration memory limits, not provider quotas.

HA caches audio using the configured model, voice, and an instance-specific connection scope. Repeated text can hit the cache while an entity instance is active. Reloads and restarts deliberately miss the prior instance's cache, including when only the key or connection changes. Old connection options are rejected and per-call model changes are unsupported. Successful entry unload closes owned HTTP responses, tasks, and audio streams within a five-second cleanup attempt, while leaving HA's shared HTTP session open. Failed platform unload resumes the entry; cleanup failure is reported and retains resources for another cleanup attempt.

Audio for STT and text for TTS are sent to the configured service. Credentials are stored in HA's integration configuration/options. Integration logs and errors omit credentials, text, audio, and provider response bodies; HA 2026.3.0 itself can log a text prefix during TTS cache errors and debug cache lookups. Use `cache: false` in `tts.speak` to disable file caching for that call; HA can still hold audio in its memory cache.

TTS failure warnings include the HTTP status when available, or a connection, read, or timeout category and acquisition/read phase. Unclassified failures use a fixed generic label. Provider error bodies are not read for diagnostics.

### Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Run the actual HA suite in a separate Python 3.14.2 environment with FFmpeg installed:

```bash
python3.14 -m venv .venv/ha
.venv/ha/bin/python -m pip install -r requirements-ha-test.txt
.venv/ha/bin/python -B -m pytest -p no:cacheprovider tests_ha -v --basetemp=.venv/ha-test-tmp
```

Current verification: 176 unit tests and 88 actual-HA integration tests on each of HA 2026.3.0 and 2026.10.0 passed, including FFmpeg decoding. Ruff lint/format and Python compilation passed.

`tests/` checks production code using small HA interface substitutes. `tests_ha/` boots installed HA core and real STT/TTS platforms, config/options flow managers, entity registry, reload/unload, cache, input/output streams, and FFmpeg decoding. Only upstream provider HTTP responses are replaced by a local server; no HA interface stubs or paid provider calls are used. Keep the suites in separate processes because the unit suite installs substitutes in Python's module table. CI preserves the Python 3.13 unit job and adds the pinned HA/Python 3.14.2 job.

Automated HA tests validate integration contracts against local provider responses, separately from the reported OpenRouter playback on the installed HA. OpenAI and xAI live calls remain untested because API keys are unavailable. Comprehensive Assist conversations, language-quality evaluation, and every provider/model/device combination are outside the confirmed playback coverage; do not treat local HTTP fixtures as live provider certification.

### License

[MIT](LICENSE) · Copyright (c) 2026 sdrstone1. You may modify, redistribute, and use the code commercially while retaining copyright and license notices. Visible UI attribution and publication of modified source are not required.

## 한국어

OpenAI, Google Gemini, xAI(Grok), OpenRouter, OpenAI 호환 음성 API 서버로 Home Assistant Assist의 음성 인식(STT)과 음성 합성(TTS)을 연결하는 통합입니다.

**현재 버전은 0.3.0이며 Home Assistant 2026.3.0 이상이 필요합니다. HA 2026.3.0과 2026.10.0을 대상으로 자동 통합 테스트를 수행합니다. 설치된 HA에서 OpenRouter의 제미나이·미스트랄·MiniMax Speech 2.8 HD TTS 재생을 확인했습니다. OpenAI·xAI는 API 키가 없어 실제 재생을 확인하지 못했습니다.**

### 기능

- 하나의 API 연결로 STT, TTS 또는 둘 다 사용
- OpenRouter의 STT·TTS 모델을 따로 조회하고 모델 ID 직접 입력도 지원
- 모델 목록에서 TTS 목소리 선택 또는 음성 ID 직접 입력
- 통합의 구성 화면에서 API 연결, 모델, 목소리 변경
- Assist에서 STT·TTS 엔티티를 각각 선택하고, 여러 통합 항목으로 다른 서비스나 키 사용
- 기존 Universal STT 설정과 STT 엔티티 ID 유지
- 전체 문장을 모은 뒤 TTS 오디오를 스트리밍하는 옵션 제공, 기본값은 꺼짐
- 한국어·영어 설정 화면과 HA 2026.3 이상에서 사용할 통합 아이콘 제공

### HACS로 설치

HACS가 설치돼 있어야 합니다. 기본 HACS 목록에는 아직 등록돼 있지 않습니다. **사용자 지정 저장소로 추가하세요.**

1. **HACS → ⋮ → 사용자 지정 저장소(Custom repositories)**를 엽니다.
2. 저장소 주소에 `https://github.com/sdrstone1/HA-Universal-STT`를 입력합니다.
3. 유형은 **통합(Integration)**을 선택하고 **추가**를 누릅니다.
4. **HA Universal Voice**를 찾아 **다운로드**합니다. 공개된 릴리스가 있으면 해당 버전을 선택하세요. 기본 브랜치에는 개발 중 변경이 포함될 수 있습니다.
5. **Home Assistant를 재시작합니다.** 다운로드 창의 `custom_components` 변경 사항을 적용하려면 재시작하라는 문구는 정상 안내입니다.
6. **설정 → 기기 및 서비스 → 통합 추가**에서 **HA 유니버설 보이스** 또는 **HA Universal Voice**를 검색합니다.

기존 사용자를 위해 저장소 주소와 설치 폴더는 유지합니다. 설치 경로는 `/config/custom_components/universal_stt/`입니다.

수동 설치를 원하면 `custom_components/universal_stt` 폴더를 HA의 `/config/custom_components/`에 복사한 뒤 재시작하고 통합을 추가하세요.

### 서비스별 지원 범위

| 서비스 | STT / TTS | 목록 조회 |
| --- | --- | --- |
| OpenAI | Audio Transcriptions / Speech API | `/models`에서 알려진 음성 모델 계열만 표시, 목소리는 공식 목록 사용 |
| Google Gemini | 전용 Interactions API로 음성 전사·WAV 음성 합성 | `/models`·`/voices` 전체 페이지 조회, STT·TTS 모델 후보 분류 |
| xAI (Grok) | 전용 `/stt`, `/tts` API | STT는 `/models`에서 전사 모델만 표시, 목소리는 `/tts/voices`에서 조회 |
| OpenRouter | 음성 API에 대응하는 모델 | STT·TTS 모델과 목소리 목록 조회 |
| OpenAI-compatible | 채팅뿐 아니라 사용할 음성 API도 지원해야 함 | 목록 API URL 선택 입력, 모델·목소리 ID 직접 입력 |

OpenRouter·OpenAI·xAI의 API 주소는 자동으로 정합니다. 서비스나 주소를 바꿀 때는 API 키를 새로 입력하세요. 기존 키를 다른 서버로 넘기지 않습니다. STT와 TTS를 각각 추가하면 서로 다른 서비스를 조합할 수 있습니다. `xai-tts`는 통합 내부 식별자이며 xAI에 모델명으로 보내지 않습니다.

OpenAI 목록에서 새 모델의 기능을 자동으로 추측하지는 않습니다. 목록에 없는 호환 모델은 ID를 직접 입력하세요. 현재 구현은 HTTP 음성 API를 사용하며 Realtime 전용 모델은 지원하지 않습니다. OpenAI의 기존 STT 모델과 TTS 스냅샷에는 [종료 일정](https://developers.openai.com/api/docs/deprecations)이 있으므로 모델을 고를 때 확인하세요.

TTS 테스트는 xAI의 `eve`와 한국어(`ko`), 또는 OpenAI의 `gpt-4o-mini-tts`와 `marin`·`cedar` 조합으로 시작해 보세요. 직접 청취해 순위를 매긴 추천은 아닙니다. OpenAI 목소리는 영어에 최적화되어 있으므로 한국어 이름, 숫자, 짧은 기기 제어 응답을 실제 스피커로 비교해 보세요.

### STT와 TTS 설정

1. **OpenAI**, **Google Gemini**, **xAI (Grok)**, **OpenRouter**, **OpenAI-compatible** 중 서비스를 고른 뒤 **STT + TTS**, **STT**, **TTS** 중 사용할 기능을 선택합니다.
2. 다음 연결 화면에서 API 키를 입력합니다. 기본 제공 서비스에서는 사용자 지정 URL과 전용 키 항목이 나타나지 않습니다. **OpenAI-compatible**에서는 선택한 기능의 기본 URL·목록·음성 API 항목을 표시합니다. TTS 출력 스트리밍은 TTS를 사용할 때만 표시합니다. OpenRouter는 `https://openrouter.ai/api/v1`을 사용합니다. 사용자 지정 서버는 `http://server:8000/v1`처럼 API 기본 URL을 입력하세요. `/audio/speech`나 `/audio/transcriptions`는 붙이지 않습니다.
3. STT를 켰다면 음성 인식 모델을 고릅니다.
4. TTS를 켰다면 음성 합성 모델과 해당 모델이 지원하는 목소리를 고릅니다. xAI는 모델 선택 없이 기본 목소리 `eve`로 시작합니다. 다른 서비스는 목소리 ID를 입력해야 합니다.
5. **설정 → 음성 어시스턴트**에서 Assist 파이프라인을 엽니다. 음성 인식에는 STT 엔티티, 텍스트 음성 변환에는 TTS 엔티티를 선택하고 언어와 목소리를 설정합니다.

**TTS 출력 스트리밍**은 기본으로 꺼져 있습니다. 연결 설정에서 켜면 도착한 오디오부터 HA에 전달합니다. Assist가 문장을 나누어 보내도 전체 입력을 먼저 모으고 검증한 뒤 합성합니다. 문장 일부가 도착할 때마다 따로 합성하지는 않습니다.

새 항목은 OpenAI를 기본으로 선택합니다. 기존 항목은 저장된 서비스를 유지하며, 서비스 항목이 없는 예전 설정은 OpenRouter를 유지합니다.

자동 모델 조회는 초기 설정과 구성 화면에서 연결 설정을 제출할 때 실행합니다. 조회가 실패하면 다시 시도하거나 자동 조회를 끄고 모델·목소리 ID를 직접 입력하세요. 사용자 지정 서버는 목록 API URL을 입력했을 때만 목록을 조회하며, 비워두면 ID를 직접 입력합니다. 설정 저장만으로 유료 음성 요청을 보내지는 않으며, 모델·목소리·서버의 호환 여부는 실제 요청 시 확인합니다.

STT와 TTS에 다른 서비스를 쓰려면 STT 전용 항목과 TTS 전용 항목을 따로 추가하세요.

### 커스텀 모델 목록

**OpenAI-compatible**의 **STT 모델 목록 API URL**과 **TTS 모델 목록 API URL**을 따로 입력합니다. 어느 한쪽을 비워두면 해당 모델 ID는 직접 입력합니다. 두 칸에 같은 주소를 넣어도 되며 URL과 키가 같으면 연결 설정을 제출할 때 한 번만 조회합니다. 켜둔 기능의 목록만 가져오고, 목록에 없는 모델도 직접 입력할 수 있습니다. 조회 오류가 나면 자동 조회를 끄고 진행하세요.

각 목록 API는 GET 요청에 `data` 또는 `models` 배열을 담은 JSON 객체를 반환해야 합니다. 항목은 ID 문자열 또는 `id`·`name`이 있는 객체를 지원합니다. `displayName`은 표시 이름, `supported_voices`는 목소리 선택지로 사용합니다. 커스텀 페이지 넘김과 임의 JSON 구조 지정은 지원하지 않습니다. 이 두 칸은 **모델 목록 조회 주소**입니다. 별도로 **STT 실제 호출 URL**, **TTS 실제 호출 URL**에 POST 요청 주소를 지정할 수 있습니다. 비워두면 `<기본 URL>/audio/transcriptions`, `<기본 URL>/audio/speech`를 사용합니다. 호출별 Bearer 키도 지정할 수 있고, 별도 키가 없으면 같은 프로토콜·호스트·포트에만 공통 키를 사용합니다. 주소를 바꾸면 새로 입력한 키가 없는 한 기존 호출 키를 지웁니다. 주소를 바꿔도 요청·응답 형식은 OpenAI 호환이어야 합니다.

각 목록에 Bearer API 키를 따로 넣을 수 있습니다. 같은 연결·목록 주소를 수정할 때 키를 비워두면 저장한 키를 유지합니다. 별도 목록 키가 없으면 프로토콜·호스트·포트가 같을 때만 음성 API 키를 사용하고, 다른 서버에는 키 없이 요청합니다. 목록 주소를 바꾸면 새 키를 입력하지 않는 한 기존 목록 키를 지웁니다. 리다이렉트는 따라가지 않습니다. 기존 공통 목록 설정은 수정 화면에서 두 칸에 채워지며, 설정을 끝까지 저장할 때 분리된 형식으로 바뀝니다.

### Google Gemini

**Google Gemini**를 선택하고 Google AI Studio API 키를 입력합니다. 기본 주소는 `https://generativelanguage.googleapis.com/v1beta`이며 Google 전용 `x-goog-api-key` 헤더를 사용합니다. 자동 조회는 `/models`의 모든 페이지를 가져온 뒤 모델 계열에 따라 STT·TTS 후보를 나눕니다. 완전한 기능 판별은 아니므로 직접 입력도 허용합니다. Google Interactions API에서 사용할 수 있는 모델을 고르세요.

STT는 WAV를 `/interactions`에 보내고, 원문 그대로 전사한 텍스트만 반환하도록 지시합니다. TTS도 같은 경로에 문장과 목소리를 보내 WAV를 요청합니다. 받은 음성은 Home Assistant에 WAV로 전달하며, 두 요청 모두 `store: false`를 사용합니다. TTS 언어는 입력 문장을 따르며 Assist의 언어 선택으로 문장을 번역하지는 않습니다. `GET /voices`의 모든 페이지에서 기본 목소리와 저장된 사용자 목소리를 조회합니다. 목록에 없는 목소리 ID도 직접 입력할 수 있습니다. 목소리의 주 언어인 `language_code`를 모델의 전체 지원 언어로 취급하지 않습니다. 실제 음성 품질과 HA 재생은 사용자 테스트가 필요합니다.

### 확인한 목록 API (2026-10-09)

| 서비스 | GET 주소 | 구분 방식 |
| --- | --- | --- |
| OpenRouter | `https://openrouter.ai/api/v1/models?output_modalities=transcription` 또는 `speech` | 서버에서 STT·TTS를 걸러서 조회 |
| OpenAI | `https://api.openai.com/v1/models` | 실제 목록을 조회하되 알려진 음성 모델 계열만 표시 |
| xAI | `https://api.x.ai/v1/models`, `https://api.x.ai/v1/tts/voices` | STT 모델과 TTS 목소리 목록을 따로 조회 |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/models` | `models[]`와 `nextPageToken` 반환, 호출 메서드만으로 음성 지원 판별은 어려움 |


공식 문서: [OpenRouter 목록](https://openrouter.ai/docs/api/api-reference/models/get-models), [OpenAI 목록](https://developers.openai.com/api/reference/resources/models/methods/list), [xAI 목록](https://docs.x.ai/developers/rest-api-reference/inference/models), [Gemini 목록](https://ai.google.dev/api/models), [Gemini 음성 입력](https://ai.google.dev/gemini-api/docs/audio), [Gemini TTS](https://ai.google.dev/gemini-api/docs/speech-generation).

### 기존 STT에 TTS 추가

1. HACS에서 통합을 열고 **⋮ → 정보 업데이트(Update information)**를 누른 뒤 개발 브랜치를 업데이트하거나 다시 다운로드합니다.
2. Home Assistant를 재시작합니다.
3. **설정 → 기기 및 서비스**에서 기존 통합의 **구성(Configure)**을 엽니다.
4. 사용할 기능을 **STT**에서 **STT + TTS**로 바꿉니다. 기존 STT 모델을 유지하고 TTS 모델과 목소리를 선택하세요.
5. 저장한 뒤 Assist 파이프라인에서 새 TTS 엔티티를 선택합니다.

기존 항목은 TTS를 설정하기 전까지 STT 전용으로 동작하므로 삭제할 필요가 없습니다. API 키를 비워두면 저장된 키를 유지합니다. 인증 없는 서버로 바꾸려면 **기존 API 키 삭제**를 선택하세요. 구성 저장 후에는 통합을 다시 불러옵니다.

구성을 끝까지 저장하면 새 설정 전체가 이전 설정을 대체합니다. 지운 항목을 최초 설정에서 다시 가져오지 않습니다. 기존 공통 모델 목록 설정은 STT·TTS별 설정이 없을 때만 읽어오며, 저장을 마칠 때 이전 형식과 꺼둔 기능의 필드를 정리합니다. 취소하거나 실패하면 저장값은 유지합니다. 통합 도메인 `universal_stt`, 설치 폴더와 기존 엔티티 ID는 그대로 사용합니다.

### 실제 설치에서 TTS 확인

**개발자 도구 → 작업 → `tts.speak`**에서 짧은 문장을 재생하세요. 아래 두 엔티티 ID는 실제 엔티티로 바꿔야 합니다.

```yaml
action: tts.speak
target:
  entity_id: tts.your_universal_voice_entity
data:
  media_player_entity_id: media_player.your_speaker
  message: "안녕하세요. 음성 출력 테스트입니다."
  language: ko
  cache: false
```

이후 Assist 대화에서도 응답이 들리는지, 기존 STT가 계속 동작하는지 확인하세요. 재생이 실패하면 모델 ID, 목소리 ID, HA 버전과 오류 메시지를 알려주세요. API 키는 공유하지 마세요. API 응답이 성공해도 스피커 재생까지 확인한 것은 아닙니다.

### 언어와 목소리

OpenRouter·OpenAI·호환 서버의 STT는 파이프라인에서 선택한 언어 코드를 `/audio/transcriptions`에 전달하며, xAI는 `/stt`를 사용합니다. Gemini는 WAV를 `/interactions`에 보내고 전사 지시에 예상 언어를 넣습니다. 통합을 추가할 때 언어 하나로 제한하던 설정은 사용하지 않습니다.

OpenRouter, OpenAI, 호환 서버의 TTS는 `/audio/speech`에 문장, 모델, 목소리를 보냅니다. OpenAI와 호환 서버에는 MP3 출력 형식을 명시합니다. OpenRouter는 기본적으로 `response_format: pcm`을 명시합니다. `custom_components/universal_stt/model_audio_formats.json`의 `defaults.request_format`이 기본 요청 형식이며, 모델별 `request_format`으로 예외를 지정합니다. MiniMax Speech 2.8 HD는 OpenRouter 스트리밍 경로에서 PCM을 거절하므로 MP3를 요청합니다. 미등록 모델은 기본값을 사용하며, 이는 요청 정책이지 모든 모델의 지원 보장은 아닙니다. 재생에는 실제 응답 형식을 사용합니다. MP3·WAV는 해당 확장자로 전달하고, signed 16비트 little-endian PCM은 WAV로 감쌉니다. PCM의 샘플레이트와 채널 수는 응답 Content-Type에서 읽습니다. 현재 모델별 PCM 보완값은 등록되어 있지 않으므로 정보가 누락되면 추측하지 않고 오류를 반환합니다. 보완값은 해당 OpenRouter 응답의 정보 누락과 그 경로에 적용할 값의 근거를 확인한 경우에만 추가합니다. 형식이 없거나 octet-stream이면 제한된 접두부에서 MP3·WAV 서명을 확인하고, 식별되지 않은 raw 바이트는 안전한 오류로 반환합니다. 형식 관측 로그에는 HTTP 상태와 허용된 미디어 형식을 남깁니다. PCM 메타데이터 로그에는 응답 헤더에서 검증한 샘플레이트·채널 수 또는 missing/invalid 상태만 남기며 원문 헤더와 발화 내용은 기록하지 않습니다. **공통 TTS API에는 언어 지정 필드가 없습니다.** 모델은 입력 문장을 읽으며, 일부 목소리는 사용할 언어나 억양을 정합니다. Assist에서 언어를 골라도 문장을 번역하거나 목소리의 언어를 바꾸지는 않습니다. 문장과 맞는 모델·목소리를 선택하세요. xAI는 `/tts`를 사용하며 Assist에서 고른 언어를 함께 전달합니다.

STT와 xAI 이외의 TTS는 Assist에 ISO 639-1 언어 코드 184개를 제공합니다. xAI TTS는 공식 언어 목록을 사용하며 `pt-PT`, `es-MX` 같은 지역 코드도 선택할 수 있습니다. **모든 모델과 목소리가 184개 언어를 지원한다는 뜻은 아닙니다.** 모델 목록에 공통 언어 필드가 문서화돼 있지 않아 모델별 언어 필터는 아직 적용하지 않았습니다. 목소리 목록은 설정할 때 저장하며, 새로 조회하려면 구성 화면에서 자동 조회를 켜고 진행하세요.

Gemini 목소리는 Voices API로 조회합니다. OpenAI 기본 목소리는 공식 문서의 목록을 사용하며 기본 목소리 GET API로 조회하지 않습니다. 목소리 ID를 직접 입력하는 방식도 지원합니다.

### 오디오와 데이터

STT는 최대 120초의 16 kHz·16비트·모노 PCM을 모아 WAV로 변환한 뒤 한 번 업로드합니다. 지원하지 않는 메타데이터, 비어 있거나 불완전한 샘플, 크기 초과 입력은 공급자 호출 전에 거절합니다. 입력 수집 시간은 130초로 제한하며 부분 전사 없이 최종 결과 하나를 반환합니다.

TTS 입력은 UTF-8 기준 최대 64 KiB이며 빈 문장은 거절합니다. 출력 스트리밍이 꺼져 있어도 문장 스트림의 수집 시간은 130초로 제한합니다. 이 제한은 전체 호출 시간의 상한이 아닙니다. 입력 스트림의 비동기 정리와 이후 공급자 요청에 걸리는 시간은 추가될 수 있습니다. TTS 오디오는 20 MiB, HTTP 요청은 60초로 제한합니다. 자동 재시도는 하지 않으며 출력 스트림이 실패하거나 중단돼도 완성 오디오를 다시 요청하지 않습니다.

출력 스트리밍을 끄면 실제 형식의 완성 오디오를 반환하며, OpenRouter PCM에는 실제 길이의 WAV 헤더를 붙입니다. 켜면 OpenRouter PCM에 길이 미정 WAV 헤더를 붙이고 완전한 채널 프레임을 순차 전달해 생성이 끝나기 전부터 재생할 수 있습니다. HA에 확장자를 반환하기 위해 OpenRouter만 제한된 응답 접두부를 미리 읽습니다. 준비된 출력을 소비하지 않아도 준비 시작부터 같은 60초 제한 또는 엔트리 해제 시 응답을 닫습니다. OpenAI·xAI·호환 서버는 첫 소비 시 MP3 요청을 시작하고, Gemini의 PCM 이벤트는 기존 스트리밍 WAV를 사용합니다. 모델 형식 JSON은 OpenRouter의 TTS 사용 항목에서만 HA executor로 읽으며, 수정은 reload 또는 재시작 뒤 적용합니다. 지원 형식 목록은 이 통합의 OpenRouter 음성 경로를 기준으로 요청 형식을 검증하며 실제 응답을 제한하지 않습니다. 필요한 모델의 정확한 ID에 예외를 추가한 뒤 통합을 다시 로드하거나 HA를 재시작합니다. 실제 OpenRouter 재생은 제미나이·미스트랄·MiniMax Speech 2.8 HD에서 확인했습니다. 이 결과가 다른 공급자·모델 조합의 재생을 보장하지는 않습니다. Gemini 스트림에는 서버 전송 이벤트(SSE) 하나당 1 MiB, 전송 데이터 전체 40 MiB의 추가 제한을 둡니다. 이 값은 통합의 메모리 보호 한도이며 공급자의 이용 한도가 아닙니다.

HA의 오디오 캐시는 설정한 모델·목소리와 현재 연결 인스턴스를 구분합니다. 같은 엔티티 인스턴스에서는 같은 문장의 캐시를 재사용할 수 있지만 다시 불러오거나 재시작하면 이전 캐시를 사용하지 않습니다. 키나 연결만 바꿔도 같습니다. 이전 연결 옵션은 거절하며 호출별 모델 변경은 지원하지 않습니다. 통합 항목을 성공적으로 해제하면 소유한 HTTP 응답·작업·오디오 스트림을 5초의 정리 시도 안에 닫고 HA의 공용 HTTP 세션은 유지합니다. 플랫폼 해제가 실패하면 항목을 다시 사용할 수 있게 하며, 자원 정리가 실패하면 오류를 알리고 다음 정리 시도를 위해 자원을 추적합니다.

STT 오디오와 TTS 문장은 설정한 서버로 전송합니다. 인증 정보는 HA의 통합 설정에 보관합니다. 통합의 로그와 오류에는 인증 정보·문장·오디오·공급자 응답 본문을 넣지 않지만, HA 2026.3.0 자체는 TTS 캐시 오류와 디버그 캐시 조회 때 문장 일부를 기록할 수 있습니다. `tts.speak`에서 `cache: false`를 지정하면 해당 호출의 파일 캐시를 끕니다. HA 메모리에는 오디오가 남을 수 있습니다.

TTS 실패 경고에는 확인 가능한 HTTP 상태 코드 또는 연결·읽기·시간 초과 구분과 응답 획득/읽기 단계를 표시합니다. 분류하지 못한 실패는 고정된 일반 표시를 사용합니다. 진단을 위해 공급자 오류 본문을 읽지 않습니다.

### 개발과 검증

의존성 설치와 검사 명령은 위 영어 안내의 [Development](#development)를 참고하세요. 실제 HA 테스트에는 Python 3.14.2와 FFmpeg가 필요합니다. `requirements-ha-test.txt`로 설치 버전을 고정합니다.

현재 검증 결과는 단위 테스트 176개, HA 2026.3.0·2026.10.0 통합 테스트 각각 88개 통과입니다. FFmpeg 디코딩을 포함하며 Ruff 정적·서식 검사와 Python 컴파일 검사도 통과했습니다.

`tests/`는 HA 인터페이스 일부를 대체해 제품 코드를 검사합니다. `tests_ha/`는 설치된 HA core와 실제 STT·TTS 플랫폼을 실행하여 설정·구성 흐름, 엔티티 등록, 다시 불러오기·해제, 캐시, 입력·출력 스트림과 FFmpeg 디코딩을 검사합니다. 공급자 HTTP 응답만 로컬 서버로 대체하며 HA 인터페이스를 대체하거나 유료 공급자를 호출하지 않습니다. 단위 테스트가 Python 모듈에 HA 대체물을 등록하므로 두 묶음은 별도 프로세스에서 실행합니다. CI는 기존 Python 3.13 단위 테스트를 유지하고 고정한 HA·Python 3.14.2 검사를 별도로 실행합니다.

자동 HA 테스트는 로컬 공급자 응답으로 통합 계약을 확인하며, 설치된 HA의 OpenRouter 재생 확인과 구분합니다. OpenAI·xAI는 API 키가 없어 실제 호출을 검증하지 못했습니다. 종합적인 Assist 대화·언어별 음질 평가 및 모든 공급자·모델·기기 조합은 확인된 재생 범위에 포함되지 않으며, 로컬 HTTP 응답 시험을 실제 공급자 검증으로 간주하지 않습니다.

### 라이선스

[MIT](LICENSE) · Copyright (c) 2026 sdrstone1. 저작권 표시와 라이선스 문구를 유지하면 수정·재배포·상업적 이용이 가능합니다. 앱 화면에 저작자 이름을 표시하거나 수정한 소스 코드를 공개할 의무는 없습니다.

## References / 참고 문서

- [OpenRouter STT](https://openrouter.ai/docs/guides/overview/multimodal/stt)
- [OpenRouter TTS](https://openrouter.ai/docs/guides/overview/multimodal/tts)
- [Home Assistant TTS entities](https://developers.home-assistant.io/docs/core/entity/tts/)
- [HACS custom repositories](https://www.hacs.dev/docs/faq/custom_repositories/)
- [Local integration icons](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)

Provider API references: [OpenAI TTS](https://developers.openai.com/api/docs/guides/text-to-speech), [xAI TTS](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech), [xAI STT](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text).
