# VOICE-REDESIGN-1 — STT·TTS 통합 재설계 plan
> **트랙**: HA Universal Voice 재설계 · **상태**: ✅ 개발·배포 준비 종결
> **식별자**: VOICE-REDESIGN-1 — 사용자 승인 작업 ID
> **실행 순서**: [graph](../graphs/VOICE-REDESIGN-1.md)
> **결과**: [단계별 보고](../issues/VOICE-REDESIGN-1.md); 확인된 범위와 검증 한계 포함

## 1. 목표 (불변)

기존 설치와 음성 기능을 유지하면서 설정·인증·공급자·HA 실행 경계를 재설계하고 검증한다. 책임 분리뿐 아니라 저장 정책, 요청 수명, 실패 전달과 실제 HA 계약을 인수 기준으로 삼는다.

## 2. 배경 (왜)

공급자 선택·HTTP·인증 정책·catalog 상태를 분리하고, TTS cache model과 요청 model의 관계 및 스트리밍 종료를 명시적인 계약으로 관리한다. 출력 스트리밍은 현재 통합에 구현되어 있으며, 기존 별도 브랜치는 참조 이력으로 보존한다. 범용 플러그인 체계는 현재 다섯 공급자에 불필요한 등록·실패 경계를 더하므로 정적 조립을 채택한다. 아래 계약과 실제 HA 검증으로 책임 경계를 유지한다.

## 3. 범위 (in / out)

| 포함 | 제외 |
|---|---|
| 공급자 5종, STT/TTS/both, 여러 entry, discovery/manual, 기존 ID·설정 보존, 출력 streaming, 테스트·영한 문서, 관심사별 커밋 이력 정리, 종결 절차, GitHub 릴리스 | 부분 전사, 실시간 문장별 합성, per-call model switching, 임의 API 번역, 추가 유료 공급자 요청 |

공급자는 OpenRouter, OpenAI, xAI, Google Gemini, OpenAI-compatible이다. entry마다 한 공급자를 설정하고 서로 다른 STT/TTS 공급자는 별도 entry로 구성한다. domain과 설치 디렉터리는 `universal_stt`다. STT unique ID는 entry ID, TTS는 `<entry_id>_tts`다. 저장소 정리는 복구 가능한 기존 이력과 검증 증거를 보존한 뒤 재설계 결과를 관심사와 의존성에 맞는 여러 커밋으로 구성한다. 파일 종류만으로 제품 코드와 관련 시험을 기계적으로 분리하지 않으며, 하나의 루트 커밋에 전체 변경을 합치는 것을 정리 결과로 삼지 않는다. 기존 스트리밍 branch는 기능 반영 여부와 미커밋 변경을 확인한 뒤 회수한다. 설치된 로컬 거버넌스 자산과 작업공간은 제품 추적 대상에서 제외하되 파일을 임의 삭제하지 않는다.

### 사용자 요구와 인수 근거

| 요구 | 구현·실행 근거 | 남은 인수 조건 |
|---|---|---|
| 기존 코드의 의도 파악 후 설계부터 전면 재설계 | graph의 원본 비교·설계 근거, 설정·전송·공급자·runtime 책임 분리 | 최종 산출물과 아래 요구의 전체 대조 |
| 기존 HA에 설치 | 보존한 설치 영수증 및 사용자 OpenRouter 재생 확인 | 릴리스 설치 안내와 기존 설치의 구분 유지 |
| STT+TTS 전환 오류·커스텀 필드 노출 수정 | cookie-free 세션, 두 단계 flow, custom 전용 입력 | 현재 기능 유지 |
| OpenAI·Gemini·xAI·OpenRouter·compatible 순서 | flow_forms.py의 선택 목록 | 현재 순서 유지 |
| TTS 요청 형식 별도 관리, 기본 PCM·모델별 예외 | model_audio_formats.json과 audio_formats.py | 릴리스 패키지에 설정 파일 포함 |
| 실제 응답 형식으로 OpenRouter 재생·스트리밍 | openrouter_audio.py·pcm_audio.py, HA·FFmpeg 시험 및 세 모델 재생 | 요청 형식과 실제 응답 형식의 구분 유지 |
| Gemini에 불필요한 PCM 보완값을 넣지 않음 | JSON에 Gemini 보완값 없음, 응답 rate·channels 사용 | 임의 기본값 재도입 금지 |
| STT는 형식 분기 필요성 조사부터 | graph의 WAV 입력 조사, 모델별 분기 미추가 | 새 모델을 전수 검증했다는 주장 금지 |
| OpenAI·xAI 등 공급자 문서 계약 확인 | native 공급자별 payload와 관련 시험·README | 실계정 미확인을 자동 시험과 구분 |
| 테스트 개발 절차에 따른 검증 | 보존한 단위·두 HA 버전 시험과 독립 리뷰, 원격 CI | 최종 변경 범위에 맞는 검토·패키지 확인 |
| 종결 절차 | 통합 결과 보고와 검증 근거 | 종결 산출물 확정 → 커밋 → 관심사별 이력 정리 → 릴리스 순서로 반영 |
| 관심사에 맞는 커밋 정리 | 백업 bundle·검토한 최종 tree | 여러 의미 있는 커밋 구성, 파일 누락·중복·최종 tree 동일성 확인 후 반영 |
| 릴리스 | manifest 0.3.0, 현재 공개 태그·릴리스 없음 | HACS manifest 필수 항목, 출시 문서·릴리스 노트, 최종 커밋 태그 및 GitHub 릴리스 공개 확인 |

## 4. 마일스톤 (큰 단위)

1. 순수 설정·인증 정책과 수명 계약을 확정한다.
2. 공급자·설정·runtime을 연결하고 기존 엔티티 동작을 유지한다.
3. STT와 TTS의 경계·취소·stream/cache를 검증한다.
4. 실제 HA 자동 검증 후 실제 공급자·Assist·스피커 증거를 확보하여 종결한다.

## 5. 주요 설계 결정

### 설정과 저장

immutable `VoiceSettings.from_entry()`는 `options or data`를 선택하며 병합하지 않는다. 기존 `settings_for()`는 독립 dict를 반환하며 `mode_for()`의 dict 계약도 유지한다.

기존 키를 보존한다: `provider`, `base_url`, `api_key`, `mode`, `model`, `tts_model`, `voice`, `voices`, `stt_models_url`, `tts_models_url`, `stt_models_api_key`, `tts_models_api_key`, `stt_url`, `tts_url`, `stt_api_key`, `tts_api_key`. `tts_streaming`은 기본 false다.

legacy `models_url/models_api_key`는 feature별 키가 없을 때만 투영한다. 명시된 빈 값은 fallback하지 않는다. VERSION 1을 유지한다. 완료된 저장에서만 legacy·비활성 기능·비custom endpoint 필드와 기존 `language`를 정리한다. 취소·실패는 저장값을 바꾸지 않는다. 기존 누락 mode는 STT, 새 설정 기본은 both다.

순수 `apply_connection_edit()`가 blank-preserve, clear flag, provider/base/endpoint 변경 시 키 제거를 결정한다. flow와 runtime은 같은 정책·factory를 사용한다. 저장은 유료 음성 요청을 하지 않으며 자격증명은 설정 객체의 repr에 포함하지 않는다.

### 설정 화면

서비스·기능 선택 뒤 연결 설정으로 진행하는 두 단계 폼을 사용한다. 서비스 순서는 OpenAI, Google Gemini, xAI (Grok), OpenRouter, OpenAI-compatible이다. 새 설정은 OpenAI를 기본 선택하고 기존 항목의 서비스는 유지한다. 공급자 필드가 없는 기존 항목은 OpenRouter로 해석한다.

기본 공급자는 API 키·목록 조회 등 공통 항목만 표시하고 API root·개별 endpoint·목록 URL·전용 키는 OpenAI-compatible에서만 표시한다. STT/TTS 중 활성화한 기능의 입력만 노출하며 서비스 변경 시 이전 키가 새 공급자로 전송되지 않게 한다. 전환 중 저장소와 기존 실행 상태는 최종 저장 전까지 유지한다. URL 입력 검증과 조회·폼 처리 오류를 구분하여 모든 실패를 API root 오류로 표시하지 않는다.

### 공급자·전송

`Endpoint`는 URL과 인증 정책을 묶는다. 공통 키는 scheme/host/effective-port가 같을 때만 사용하며 전용 키가 우선한다. HTTP 로컬 서버는 허용한다. userinfo/fragment와 base query는 거절하고 full endpoint query는 허용한다. redirect는 금지한다.

`Transport`가 status·인증·timeout·JSON·bounded read·response close를 담당한다. HTTP 60초, TTS 20 MiB를 유지한다. 설정 조회와 실행은 통합 전용 HTTP 세션 하나를 공유하며 `DummyCookieJar`로 공급자 쿠키를 저장하거나 재전송하지 않는다. HA의 기본 공유 세션·쿠키 저장소는 변경하지 않는다. HA helper의 공용 connector를 사용하되 entry별 자동 정리 대신 HA close 이벤트에서 세션을 detach한다. 여러 entry 중 하나를 해제해도 다른 entry와 설정 조회의 세션이 유지되어야 한다.

`VoiceClient`는 `transcribe(wav, model, language) -> str`, `synthesize(text, model, voice, language) -> bytes`, 고정 `audio_format` facade를 유지한다. S3에서 생성자와 소비자를 함께 교체한다. 기존 error import는 새 공용 모듈의 같은 class 객체를 re-export한다.

immutable `CatalogSnapshot`은 모델별/공급자 전체 voice scope와 live/documented/manual 출처를 구분한다. mutable `client.voices` 부작용을 제거한다. custom 동일 URL/실효 인증은 제출당 한 번 조회하며 Gemini 반복 page token은 실패한다. 조회 실패 후 조회 해제·수동 입력으로 완료할 수 있다. 목록이나 언어 전달 선택지가 모델의 실제 지원 능력을 입증하지 않는다.

OpenAI 호환 MP3, xAI native endpoints와 TTS model 미전송, Gemini Interactions `store:false`·WAV를 보존한다. 자동 retry는 추가하지 않는다.

### entry와 stream 수명

S3 `EntryRuntime`은 admission과 entry 소유 child task·응답·스트림 registry를 관리한다. 작업은 HTTP await 전에 등록하고 finally에서 해제한다. HA 호출자 task를 소유하거나 직접 취소하지 않는다.

`AudioStream`은 extension·byte iterator·idempotent `aclose()`를 제공한다. OpenRouter 외 공급자는 첫 iteration에서 HTTP를 시작하므로 미소비 stream은 network 자원을 소유하지 않는다. OpenRouter는 HA에 확장자를 반환하기 전에 응답 형식을 확인해야 하므로 준비 단계에서 HTTP를 시작하며, 첫 소비 전에도 응답을 소유하고 deadline·명시 close·unload에서 회수한다. 획득 response는 즉시 등록한다. 반복·동시 close는 하나의 cleanup task를 공유한다. response를 동기 close하고 pending request/pull을 취소·join한 뒤 generator를 close하여 already-running 충돌을 피한다.

S5 HA wrapper는 finally에서 provider stream을 닫는다. break 자체의 자동 close를 약속하지 않는다. consumer 명시 close와 entry unload가 회수 경계다.

unload는 admission pause → platform unload 순서다. false/exception이면 admission을 다시 열고 기존 runtime·요청을 유지하며 실패를 전달한다. 성공하면 admission을 영구 폐쇄하고 response close·작업 취소·iterator cleanup을 전체 5초 안에 수행한다. cleanup 실패는 성공으로 반환하지 않고 shutdown 기록을 유지하여 재시도한다. 재시도는 platform unload를 반복하지 않으며 영구 폐쇄된 runtime을 재개하지 않는다. setup 부분 실패도 같은 소유 자원 cleanup으로 rollback한다.

### STT·TTS·cache

STT는 16 kHz/16-bit/mono PCM, 2분 상한·130초 수집 timeout을 유지한다. metadata·empty·홀수 PCM·overflow·timeout은 호출 전에 실패한다.

TTS는 전체 입력을 모은 뒤 출력 streaming을 시작한다. 완성/stream 호출 모두 empty·64 KiB UTF-8 상한을 검증하며 입력 수집은 130초로 제한한다. 이 입력 제한은 새 자원 보호 결정이다. HA 입력 stream 지원은 출력 streaming 설정과 분리한다. 입력 stream은 항상 통합의 제한된 수집 경로로 받고, 출력 streaming이 꺼져 있으면 완성 오디오 응답을 반환하여 HA 자체의 무제한 입력 결합 경로로 우회하지 않는다. SSE 1 MiB/event, 40 MiB wire, 20 MiB PCM은 참조 구현에서 계승한 내부 메모리 상한이며 공급자 공식 허용치로 설명하지 않는다.

configured model을 cache와 실제 요청에 사용하고 다른 model 옵션은 거절한다. xAI 내부 model sentinel은 서버로 보내지 않는다. S5는 entity instance마다 opaque random `connection_revision`과 그 UUID를 포함한 `connection_scope_<uuid>` 옵션 키를 supported/default options에 넣는다. HA가 엔티티보다 먼저 cache를 조회하므로 옵션 값만 바꿔 이전 cache key를 재현할 수 없게 이름도 instance에 결속한다. 이전 전체 options는 지원하지 않는 scope 키로 HA가 먼저 거절하며, 이전 revision만 넘겨도 새 scope 기본 키 때문에 이전 cache를 읽지 못하고 엔티티가 요청 전에 거절한다. 저장 schema·secret/URL hash를 사용하지 않는다. 같은 instance는 cache hit, reload/restart는 의도적 cache miss다.

오류는 flow 오류·STT ERROR·TTS 실패/HA 오류로 전달하고 취소는 전파한다. 이 통합의 로그·예외에는 secret·텍스트·음성·응답 본문을 넣지 않는다. TTS 실패 진단은 검증된 HTTP 상태 숫자와 고정된 전송 실패 종류·단계만 표시하며 원본 예외 문자열을 출력하지 않는다. HA 2026.3.0 자체의 TTS cache 오류 로그는 입력 문장 일부를 기록하므로, HA 전체 로그의 무텍스트를 보장한다고 설명하지 않는다. J1에서 이 외부 동작과 통합의 보호 범위를 README에 구분한다.

### OpenRouter TTS 응답 형식에 따른 재생

OpenRouter TTS 요청의 response_format은 별도 JSON의 defaults.request_format(pcm)을 기본으로 하고 정확한 모델 ID의 request_format 예외(MiniMax Speech 2.8 HD: mp3)를 우선하며 실제 응답의 Content-Type에 따라 MP3·WAV·PCM을 처리한다. 모델 이름이나 설정의 지원 형식 목록으로 실제 응답을 덮어쓰지 않는다. MP3와 WAV는 해당 확장자로 전달하며 PCM은 signed 16-bit little-endian 프레임에 WAV 헤더를 붙인다. application/octet-stream 또는 누락 MIME은 제한된 접두 바이트에서 MP3/WAV 서명을 확인하고, 식별하지 못한 바이트를 MP3나 raw PCM으로 추정하지 않는다.

PCM의 rate·channels는 유효한 응답 매개변수를 우선한다. 현재 등록된 모델별 PCM 보완값은 없다. 보완값 추가는 실제 OpenRouter 응답에서의 누락 및 해당 경로에 적용할 값의 근거가 확인된 경우에 한한다. 알 수 없거나 잘못된 값은 명확한 안전한 오류로 반환하며 전역 24 kHz·모노를 임의 적용하지 않는다. 형식 규칙과 지원 형식 정보는 설정 파일에 분리하되 새로운 모델의 유효한 응답을 목록 부재만으로 거절하지 않는다. JSON은 HA executor에서 읽고 검증한 불변 snapshot을 주입하며, reload 또는 재시작으로 수정 내용을 적용한다. STT-only·모델 조회는 TTS 형식 설정을 요구하지 않는다.

반환 형식은 요청별 결과·스트림에 담고 공유 client.audio_format을 변경하지 않는다. 완성 PCM은 실제 길이의 RIFF/WAV로 반환한다. 스트리밍은 길이 미정 WAV 헤더를 먼저 보내며 채널 프레임 경계에서 분할된 바이트를 이어 붙인다. 최대 응답 크기·빈 응답·미완 프레임·취소·동시 close·unload 계약을 유지한다.

HA는 응답 객체를 반환할 때 확장자를 요구하므로 OpenRouter 스트리밍에서만 제한된 응답 접두부를 미리 읽어 형식을 결정한다. 준비 시작 전에 entry가 스트림을 소유하고, 준비 취소·실패·첫 소비 전 close·unload에서 정리한다. 다른 공급자는 기존 첫 소비 시 HTTP 시작 계약을 유지한다. 준비한 스트림을 소비하지 않아도 timeout 및 entry 수명 안에서 자원을 회수해야 한다. 자동 재호출은 하지 않는다.

인수 기준은 설정 기반 기본 요청 형식과 모델별 예외 적용, PCM·MP3·WAV의 올바른 반환 확장자, 동시 요청의 형식 격리, 헤더 우선/누락 fallback/잘못된 metadata 실패, bounded sniff와 미지원 형식 거절, PCM 분할 프레임 처리, 전체 생성 전 첫 출력 수신, 실제 HA와 FFmpeg의 디코딩·취소·미소비 정리 검증이다. STT와 native 공급자의 요청 형식은 변경하지 않는다.

### 검증과 종결

STT·TTS의 130초 제한은 입력 수집 구간의 시간이다. HA가 제공한 입력 iterator의 비동기 정리와 이후 공급자 요청까지 합친 전체 호출 시간의 상한은 아니다. 입력 정리는 소유 호출 경로에서 기다리고 취소를 전파하며, 추적되지 않는 background cleanup으로 넘기지 않는다. 지연된 upstream 정리 중 공급자 미호출과 취소 전파도 검증한다.

각 slice의 관련 테스트는 `python -m unittest discover -s tests -p '<소유 테스트 파일명>' -v`로 실행한다. 리드는 각 checkpoint의 import와 전체 회귀를 확인한다. 검증 의존성은 작업공간의 `.venv`에 설치한다. 아래 명령은 재확인 절차이며, 실행 결과는 graph checkpoint와 단계별 보고에 기록한다.

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m compileall -q custom_components
.venv/bin/python -m unittest discover -s tests -v
```

수명 테스트는 pending headers, blocked read, never-consumed, cancellation, explicit-close break, concurrent close, unload false/exception 후 신규 요청, setup rollback, cleanup timeout/retry를 포함한다. 정상 종료의 registry 비움과 shared session 생존을 확인한다. S3는 모든 공급자·mode의 import/boot, flow/runtime의 동일 factory, 기존 엔티티와 facade의 호환도 검증한다.

J1은 기존 Python 3.13·Ruff py311을 유지하고 별도 pinned HA 2026.3.0/Python ≥3.14.2 job에서 `python -m pytest tests_ha -q`를 실행한다. HA·pytest·pytest-asyncio의 실제 설치 가능한 버전을 고정한다. 실제 HA 객체·등록·options·reload·unload·IDs·cache·stream 소비를 검사하고 network/provider 응답만 대체한다. unit stub과 별도 프로세스를 사용한다. ffmpeg로 streaming WAV decoder 수용·duration·truncation을 검사한다. 같은 model/voice로 연결 또는 키 변경 후 stale audio 재사용이 없어야 한다. 실제 HA 검사를 skip/stub으로 대체하면 완료가 아니다. 최소 HA 버전은 baseline 시험 성공 뒤 `hacs.json`에 선언한다.

실제 HA에 설치한 OpenRouter Gemini·Mistral·MiniMax Speech 2.8 HD의 사용자 재생 확인을 실행 근거로 기록한다. OpenAI·xAI는 키 부재로 실제 공급자 호출을 확인하지 못했으며 자동 HTTP 계약 테스트와 구분한다. 종합적인 Assist 대화·언어별 음질 평가·모든 모델과 기기 조합을 검증했다고 주장하지 않는다. 사용자가 확인한 실행 범위와 잔여 한계를 기록한 verified graph commit 및 device 승인 경계를 따른다. 추가 유료 공급자 호출은 수행하지 않는다.

## 6. 열린 질문 · 외부 의존

열린 제품 설계 질문은 0개다. Python 3.14.2·HA 2026.3.0 환경을 작업공간에 준비했다. CI와 실제 HA·공급자·스피커 증거는 실행 의존이다. 사용자 승인 범위의 기존 HA 설치 갱신은 포함한다. 유료 공급자 호출은 별도 승인 후 수행한다. `device_requirement=required` 등록과 승인 근거는 graph의 실행 준비 기록을 따른다.

README 영한 본문은 streaming 기본 false, 전체 입력 상한, 취소·retry 정책과 실제 확인된 공급자 범위를 설명한다. 종결 검증은 실제 재생 확인과 자동 회귀를 별도로 기록한다. GitHub 릴리스는 요청 범위에 포함하며, 버전·설치 안내·HACS manifest·배포 파일 및 릴리스 노트를 준비하고 최종 검토된 관심사별 이력의 커밋에 태그한다. 출시 사실은 실제 공개 결과로 확인하고 미발행 상태에서 발행했다고 기록하지 않는다.

## 7. cross-ref

- 실행·scope·발견 근거: [graph](../graphs/VOICE-REDESIGN-1.md).
- 제품 기준: [README](../../README.md).
- 규칙: [AI_RULES](../../docs/rules/AI_RULES.md), [CODE_RULES](../../docs/rules/CODE_RULES.md).
- 공식 계약: [HA STT](https://developers.home-assistant.io/docs/core/entity/stt/), [HA TTS](https://developers.home-assistant.io/docs/core/entity/tts/), [HA 2026.3.0 Python 요구](https://raw.githubusercontent.com/home-assistant/core/2026.3.0/pyproject.toml), [Gemini Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview), [Gemini Voices](https://ai.google.dev/api/voices), [OpenRouter STT](https://openrouter.ai/docs/guides/overview/multimodal/stt), [OpenRouter TTS](https://openrouter.ai/docs/guides/overview/multimodal/tts), [xAI STT](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text), [xAI TTS](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech).
- [완료 보고](../issues/VOICE-REDESIGN-1.md)는 구현·검증 결과와 실제 공급자 확인 범위를 기록한다.
