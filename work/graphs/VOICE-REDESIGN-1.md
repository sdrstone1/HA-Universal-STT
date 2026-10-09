# VOICE-REDESIGN-1 — STT·TTS 통합 재설계 graph
> **목표**: 기존 설치와 음성 기능을 유지하면서 설정·인증·공급자·HA 실행 경계를 재설계하고 검증한다.
> **트랙**: HA Universal Voice 재설계 · **상태**: ✅ 개발·배포 준비 종결
> **식별자**: VOICE-REDESIGN-1 — 사용자 승인 작업 ID, Jira 미사용
> 🔒 base: main
> 🔒 device: none
> 이번 통합은 문서 정리만 포함한다. 제품의 기존 실기기 확인 범위는 아래 검증 근거와 통합 결과 보고에 보존한다.

## 1. 입력 스냅샷 (유효성 게이트)

| 입력 | 확인일 | 기준 |
|---|---|---|
| 제품 코드·README·테스트·프로젝트 규칙 | 2026-10-09 | main `2a5d51049ebc5179549eb42e0b605c13fd149e87` |
| 기존 출력 스트리밍 구현 | 2026-10-09 | `99f7f0330eb42c9663f3ca06f4444fcc8df7501e`; 기능 반영 대조 후 bundle로 보존 |
| 사용자 결정 | 2026-10-09 | 작업 ID·`feature/VOICE-REDESIGN-1` 승인; 설계부터 진행 |
| 실행 계약 | 2026-10-09 | [plan](../plans/VOICE-REDESIGN-1.md), 프로젝트 AI_RULES, GRAPH_OPS·WORKER_CONTEXT·WORKER_OPS·REPORTING |

확인일은 입력 관측일이다. 기준 제품 파일의 Git 변경일도 2026-10-09이며, 재진입 시 `git diff 2a5d51049ebc5179549eb42e0b605c13fd149e87..main -- README.md custom_components tests docs/rules`로 변경을 확인한다.
작업공간은 `/home/sdrstone1/Documents/Codex/HA STT/.worktrees/voice-redesign`, 브랜치는 `feature/VOICE-REDESIGN-1`이다. 현재 main은 `a23e7b10fe6a5bd1c4f6c3e8fef400969da40772`다. 기존 제품의 device 확인 범위는 유지하며 이번 저장소 정리는 음성 처리 동작을 변경하지 않는다. 종결 절차, 관심사별 커밋 구성과 공개 릴리스까지 사용자 요청 범위에 포함한다. 현재 main에는 관심사별 7개 커밋이 반영되어 있다. 종결 산출물을 먼저 확정하고 그 결과를 해당 관심사 커밋에 반영한 뒤 릴리스를 공개한다. 별도의 반복 종결 보고는 추가하지 않는다.

## 2. slices (노드)

`I/`는 `custom_components/universal_stt/`, `T/`는 `tests/`다. 중괄호는 명시된 파일들의 집합이며 wildcard가 아니다. 각 파일의 writer는 하나다.

| ID | 정의 / type | 상태 | 파일(scope, disjoint) | 검증·의존·device |
|---|---|---|---|---|
| S1 | 설정과 공용 계약 / foundation | ✅ | `I/{const,settings,contracts,errors}.py`; `T/test_settings.py` | snapshot·legacy·키 편집 정책; 없음; none |
| S2 | HTTP 인증과 응답 수명 / foundation | ✅ | `I/transport.py`; `T/test_transport.py` | origin·redirect·bounded read·close·cancel; S1; none |
| S3 | 공급자·설정 흐름·등록 / vertical | ✅ | `I/{client,gemini,config_flow,__init__,catalog,xai,gemini_stream,flow_forms,http_session,runtime,audio_formats,pcm_audio,openrouter_audio}.py`, `I/{strings,model_audio_formats}.json`, `I/translations/{en,ko}.json`; `T/{test_core,test_gemini,test_voice_flow,test_output_streaming,test_entry_lifecycle,test_audio_formats,test_openrouter_format_probe}.py` | 공급자 payload·모델별 형식·조회 fallback·setup/reload/unload·수명; S1,S2; required |
| S4 | STT 발화 처리 / vertical | ✅ | `I/{stt,audio,languages}.py`; `T/{test_languages,test_stt_entity}.py` | metadata·PCM 경계·timeout·언어·ID·취소; S3; required |
| S5 | TTS와 출력 스트리밍 / vertical | ✅ | `I/tts.py`; `T/{test_tts_entity,test_tts_streaming,test_tts_diagnostics}.py` | model/cache·입력 경계·stream consumer close·안전한 실패 진단; S3; required |
| J1 | 실제 HA와 제품 문서 / integration | ✅ | `README.md`, `hacs.json`, `.github/workflows/checks.yml`, `requirements-ha-test.txt`, `tests_ha/{conftest,test_runtime,test_audio,test_cache,test_config_flow,test_openrouter_audio}.py` | 실제 HA lifecycle·cache·stream·decoder; S3,S4,S5; required |
| R1 | 저장소와 이력 정리 / integration | ✅ | `.gitignore`, `docs/rules/CODE_RULES.md`, `work/README.md`; 리드 소유 graph·plan·issue 및 Git 이력 | 요구 대조·문서 정합·복구본·제품 tree 동일성; J1; 새 실기기 시험 불필요 |
| R2 | 릴리스 산출물 준비 / integration | ✅ | `I/manifest.json`, `README.md`, 릴리스 노트·배포 ZIP | HACS 필수 항목·버전·배포 파일·게시 대상 선택 절차; J1; 음성 로직 변경 시 재판정 |

foundation은 후속 기능의 기반, vertical은 사용자 흐름까지 연결한 변경, integration은 합류 검증을 뜻한다. graph·plan은 리드 소유 기획 자산이다. 수정 재검증은 원래 파일 소유 slice를 다시 열어 수행한다. 검증한 단계는 issues에 누적 기록하며 전체 제품 종결과 구분한다.

## 3. edges (의존 흐름 = 시간축)

모든 edge는 `impl_dep`다.

| 선행 | 후행 |
|---|---|
| S1 | S2 |
| S1 | S3 |
| S2 | S3 |
| S3 | S4 |
| S3 | S5 |
| S3 | J1 |
| S4 | J1 |
| S5 | J1 |
| J1 | R1 |
| J1 | R2 |

## 4. frontier (현재 착수 가능 작업)

- 개발 frontier는 없다. 종결 산출물을 포함한 파일을 기존 관심사별 커밋에 반영한 뒤 최종 커밋으로 v0.3.0을 공개한다. 이는 개발·배포 준비의 종결이며 아직 공개 성공을 뜻하지 않는다. 게시 결과는 GitHub 태그·릴리스와 CI를 정본으로 확인하고 별도 종결 보고를 추가하지 않는다. OpenAI·xAI 실계정 미확인 한계는 유지한다.
- 순차 작업은 graph workspace를 공유한다. S4/S5 동시 실행에만 scratch를 배정한다.
- 검증된 scratch는 다른 slice를 기다리지 않고 graph로 fold한다.
- S1/S2는 기존 실행 경로를 유지하고, S3는 기존 엔티티 facade 계약을 보존한 새 backend를 연결한다. 각 checkpoint는 전체 unit suite와 import 검사를 통과해야 한다. worker는 관련 테스트를 수행하고 리드는 checkpoint의 전체 회귀를 확인한다.

## 5. design_rationale (설계·판정 근거)

설정 정책 → 전송 → 공급자/설정/등록 → 엔티티 순서로 책임을 교체한다. S3는 조회부터 저장·실행까지 연결하여 임시 이중 factory를 피한다. S4/S5는 writer가 겹치지 않는다. 상세 계약·인수 기준은 [plan §5](../plans/VOICE-REDESIGN-1.md#5-주요-설계-결정)에 둔다. 파일 권장 400줄·상한 1000줄은 각 책임 모듈에 적용한다.

### 설정 snapshot — 병합하지 않는다

- 근거: 기준 `settings.py:6`의 결과는 `dict(entry.options or entry.data)`다.
- 배제: 일반적인 data/options 병합 — 삭제한 키가 다시 살아나므로 기존 계약과 다르다.
- 재확인: `git show 2a5d510:custom_components/universal_stt/settings.py`.
- 처리: S1에서 고정하고 기존 dict helper 계약을 유지한다.

### TTS model — configured model과 cache 식별자를 유지한다

- 근거: 기준 `tts.py:77,90`에 default model의 cache 목적이 명시되어 있고 configured model을 요청한다.
- 배제: 옵션 누락을 근거로 per-call switching 추가 — 새로운 기능 의도를 입증하지 못한다.
- 재확인: `git show 2a5d510:custom_components/universal_stt/tts.py`.
- 처리: S5에서 다른 model 옵션을 요청 전에 거절한다.

### stream 종료 — 소비자와 entry 수명까지 소유한다

- 근거: 참조 브랜치의 `tts.py`, `gemini_stream.py`는 출력 iterator를 제공하지만 HA 조기 종료·entry unload 증거는 없다.
- 배제: generator 내부 context만으로 모든 break가 자동 close됨 — 외부 consumer close가 필요하다.
- 재확인: `git show 99f7f0330eb42c9663f3ca06f4444fcc8df7501e:custom_components/universal_stt/tts.py`.
- 처리: S2/S3/S5의 lazy acquisition·registry·명시 close 계약과 J1 검증으로 해결한다.

### unit green — 실제 HA·공급자 검증과 구분한다

- 근거: 현재 CI는 Python 3.13이며 entity/flow 테스트는 HA 대체 인터페이스를 사용한다.
- 배제: unit 통과가 실제 HA 등록·스피커 재생을 입증함 — 실행 대상이 다르다.
- 재확인: `git show 2a5d510:.github/workflows/checks.yml`.
- 처리: J1 실제 HA job과 required device gate를 둔다.

### HA 입력 수집과 로그 — 통합이 제어하는 경계를 구분한다

- 근거: 실제 HA 2026.3.0 `components/tts/__init__.py`의 1046–1053행은 입력 stream 미지원 엔티티의 입력을 제한 없이 결합하며, 952–958행은 cache 오류에 문장 일부를 기록한다.
- 배제: 출력 streaming 설정을 그대로 입력 지원 여부로 사용해도 통합의 입력 제한이 유지됨 — 꺼진 경우 HA가 먼저 입력을 수집하므로 성립하지 않는다. 통합 예외의 텍스트 제거만으로 HA 전체 로그가 보호된다는 해석도 core의 별도 message 인자로 인해 성립하지 않는다.
- 재확인: `sed -n '940,965p;1040,1067p' .venv/ha/lib/python3.14/site-packages/homeassistant/components/tts/__init__.py`.
- 처리: S5는 입력 stream을 항상 제한된 수집 경로로 받고 출력 설정에 따라 완성/stream 응답을 선택한다. J1은 HA core 로그의 외부 제약을 문서화한다. 제품 통합의 로그·예외 보호는 유지하며 외부 HA 소스를 이 저장소에서 변경하지 않는다.

### HA cache 이전 옵션 검증 — 옵션 이름도 instance에 결속한다

- 근거: HA 2026.3.0 `tts/__init__.py:782–790,903–909`는 호출 options로 기본값을 덮은 뒤 엔티티 호출보다 먼저 cache hit를 반환한다. 실제 SpeechManager 메모리 재현에서 이전 revision으로 이전 cache를 읽었다.
- 배제: 엔티티의 revision 검사만으로 모든 오래된 요청을 거절함 — cache hit는 엔티티에 도달하지 않는다. defaults에만 내부 키를 넣는 대안은 supported/default의 일치 계약에 기대지 못하므로 채택하지 않는다.
- 재확인: graph 환경에서 `sed -n '761,800p;886,947p' .venv/ha/lib/python3.14/site-packages/homeassistant/components/tts/__init__.py`; J1 actual HA에서 이전 전체 options 및 revision만 재전달하는 회귀를 실행한다.
- 처리: 고정 revision 값과 함께 instance UUID를 포함한 scope 옵션 이름을 사용한다. 실제 HA의 options hash는 키 이름을 포함하며, 이전 scope 키는 지원하지 않는 옵션으로 cache 전에 거절된다. 저장 형식과 엔티티 ID는 유지한다.

### 공급자 cookie와 모델 조회 — 인증 검사는 유지하고 세션을 격리한다

- 근거: 실제 HA 2026.10.0의 기본 공유 세션은 cookie jar를 사용한다. 로컬 목록 서버가 STT 목록 응답에 Set-Cookie를 반환하면 TTS 목록의 다음 요청은 Transport의 ambient cookie 차단으로 ValueError를 내고, 기존 flow는 이를 invalid_url로 표시했다. 동일 조건 STT 단독은 모델 폼까지 진행했다.
- 배제: 정상 HA 기본 세션의 trust_env 설정 자체가 원인 — 실측 false다. HTTP(S) URL 형식만 고치면 해결됨 — 검증한 로컬 URL에서도 첫 응답 cookie 후 두 번째 요청 전에 실패했다. 공용 쿠키 삭제나 보안 guard 제거 — 다른 통합의 세션 상태를 바꾸거나 인증 정책을 약화하므로 배제한다.
- 재확인: `.venv/ha-live/bin/python -B -m pytest -p no:cacheprovider tests_ha/test_config_flow.py -k cookie --basetemp=.venv/voice-flow-recheck`로 cookie 응답 후 STT/TTS 연속 목록 조회를 재확인한다. 운영 공급자의 실제 응답·자격증명은 읽거나 호출하지 않았으므로 운영 실패의 세부 응답까지 확정한 것은 아니다.
- 처리: 통합 전용 cookie-free 세션을 flow/runtime이 공유하고 entry unload와 HA 종료의 소유권을 구분한다. URL 검증과 조회 실패 메시지도 분리한다. 사용자 설정 전환을 막는 경로라 이번 수정에서 처리한다.

### STT 형식 분기 필요성 — 조사 범위의 현행 WAV 호환

- 판정·근거: 현재 `audio.py`는 16 kHz·16-bit·모노 PCM WAV를 만들며 최대 120초(약 3.84 MB, base64 약 5.12 MB)다. 조사한 [OpenRouter](https://openrouter.ai/blog/tutorials/transcription-on-openrouter/), [OpenAI](https://developers.openai.com/api/docs/guides/speech-to-text), [Gemini](https://ai.google.dev/gemini-api/docs/audio), [xAI](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text) 문서는 WAV 입력을 지원하고 현행 크기는 각 inline/upload 상한보다 작다. multipart와 base64 요청 포장도 각 구현 경로와 맞는다. 유료 공급자 호출 없이 공식 문서와 코드만 조사했다.
- 배제: TTS처럼 STT에도 모델별 PCM/MP3 선택을 즉시 구현해야 함 — 현재 입력과 충돌하는 형식 조건은 발견하지 못했다. multipart/base64 차이를 코덱 차이로 보는 해석도 동일 WAV를 포장하는 방식이라는 점에서 배제한다.
- 재확인: `grep -nE 'setnchannels|setsampwidth|setframerate|MAX_AUDIO_BYTES|add_field|mime_type|base64' custom_components/universal_stt/{audio.py,const.py,client.py,gemini.py,xai.py}`.
- 처리: 사용자가 요구한 필요성 조사까지만 수행하고 STT 코드를 변경하지 않는다. 새 모델·커스텀 서버를 추가할 때 WAV, endpoint, 모델별 옵션·입력 제한을 확인한다. 모든 현재·향후 카탈로그 모델의 호환성을 전수 보증하는 판정은 아니다.

## 6. 검증·실행 근거

최종 문서 검증: kh-verify light의 critic·document 두 독립 렌즈 findings=[], review_green=true, raw_major_plus=0, confirmed_majorplus=0, needs_user_decision=0, missing_lenses=[], execution_failures=[], device_recommended=false, test_adequacy_warn=false. 요구 대조 결과 반복 종결 보고 제거·기존 관심사 커밋 반영 순서와 일치한다. diff check와 main 대비 제품·시험·CI 동일성 검사 exit 0. 기존 unit176·HA 버전별88 및 실기기 확인 범위를 보존한다. QA: 문서 링크·범위 정합 확인, 공용 API·docx·정책 변경 없음. chain-termination=graph-finalize-ready; 추가 제품 시험이나 실계정 호출은 필요하지 않다. 개발 종결 산출물을 확정해 기존 문서 관심사 커밋에 반영하며, 공개 실행 결과는 태그·릴리스·CI에서 확인한다.

- 2026-10-09 최종 배포 준비 검토 — kh-verify panel의 critic·architect·security·document 4렌즈가 findings=[]를 반환했다. review_green=true, raw_major_plus=0, confirmed_majorplus=0, needs_user_decision=0, missing_lenses=[], execution_failures=[], adversarial_ran=false다. security의 test_adequacy_warn=true는 실제 이력 재구성·push 경로 미실행에 대한 한계이며 해소된 것으로 바꾸지 않는다. 새 device 검증 권장은 없고, 기존 음성 Python·시험·CI·의존성은 1a5d949와 동일하다. 실제 원격 CI core·home-assistant job success를 확인했다. 현재 metadata JSON·diff check는 exit 0, ZIP은 추적 통합 파일 30개를 소스 blob과 바이트 대조했고 SHA256은 `f1a753ce1b0c68fb82c31845ca460eb5cab5f8251d3107183f80e904052a2181`이다. 관심사 7개에 최종 75파일을 한 번씩 배정했다. QA5: 설치·버전·링크·실행 범위 문서 정합 확인, docx/API_SPEC/공용 API cascade/접근제어 변경 해당없음. 종결 산출물과 배포 준비에 대한 검토는 마쳤으며, 전체 요청은 이력·태그·공개 결과 확인 전까지 진행 중이다.

- 2026-10-09 이력 재구성 실행 경계 — 별도 인덱스의 `git read-tree --empty`가 KH-WORKER-001에 의해 main 내용 반입으로 분류되어 실행 전 차단됐다. 배정 worktree의 `.venv/release-handoff/rebuild_history.py`를 사용자 실행용으로 준비하고 독립 검토했다. 에이전트는 읽기 전용 `--check`와 구문 검사만 실행했다. 스크립트는 exact source·로컬/원격 기준·미추적 파일까지 clean 상태 확인, bundle 생성·verify, 커밋별 경계·최종 tree·개수 대조 후 main 교체와 lease push를 수행하며 실행 영수증을 저장한다. mutation 경로는 에이전트가 실행하거나 다른 도구로 우회하지 않았다. 게시 결과 확인과 남은 작업공간 회수는 실행 이후에만 보고한다.

- 2026-10-09 사용자 요구 전수 대조 — 이전의 assistant 작성 plan 범위 제외를 사용자 승인처럼 소비한 오류를 교정했다. 원격 main은 `1a5d949` 단일 root이고 공개 tag·release는 없다(`git rev-list --count main`, `git ls-remote --tags origin`, `gh release list --repo sdrstone1/HA-Universal-STT`). 사용자가 요구한 관심사별 커밋 정리·릴리스는 미수행으로 판정하며, 기능·설정·형식 처리·STT 조사·기존 설치 요구는 코드와 보존 기록에 반영되어 있음을 독립 대조했다. 모든 공급자의 새 실계정 시험을 추가 요구로 만드는 해석은 키 부재 수용과 실제 확인 범위 때문에 배제한다. HACS 공식 integration 문서의 manifest 필수 항목과 현재 JSON 대조로 issue_tracker 누락을 추가 발견했으며 릴리스 준비에 포함한다. 최신 원격 CI `https://github.com/sdrstone1/HA-Universal-STT/actions/runs/37894291227`는 `1a5d949`에서 success지만 이는 미발행 릴리스나 관심사별 이력의 완료 증거가 아니다. 전체 종결은 아직 진행 중이다.

- 2026-10-09 이력 전환 준비 검토 — kh-verify light의 fresh critic·document 두 렌즈에서 CRITICAL/MAJOR/MINOR 0건, missing_lenses=[], execution_failures=[], confirmed_majorplus=0, needs_user_decision=0, review_green=true, test_adequacy_warn=false, device_recommended=false다. 요구 대조에서도 사용자 요청과 충돌하는 지적은 없으며 이 등급의 적대검증은 미실행이다. diff check와 제품·시험·CI·의존성·HACS 동일성 검사는 exit 0이다. QA5는 기존 문서 참조와 실제 CI 안내 정합을 확인했고 API_SPEC/docx/공용 계약 변경/접근제어는 해당없다. 이번 문서 변경은 양 runtime instruction이 같은 CODE_RULES를 참조하는 프로젝트 문서 보완이며 전역 hook·정책의 의미나 강제를 변경하지 않는다. chain-termination 분류는 이력 전환·원격 반영 대기이며 전체 요청 완료를 선언하지 않는다.

- 2026-10-09 복구본 확인과 이전 작업공간 회수 — 사용자가 bundle 생성·verify 명령의 성공을 확인했다. 리드는 `.venv/archives/VOICE-REDESIGN-1/pre-cleanup-all-refs.bundle` 실재 및 SHA-256 `865674667bbb20e1f5af466ed6dd5f5d2bd747464ff4e11fb80c48899090dc26`을 확인했다. streaming worktree의 status가 빈 결과이고 기존 9개 출력 시험 시나리오와 기능이 현재 main에 반영된 독립 대조 근거에 따라 해당 worktree 및 branch를 회수했다. 사용자 실행을 리드가 bundle verify한 것으로 기록하지 않는다. 제품·시험·CI·의존성·HACS 파일의 `git diff 39eb9f7 --exit-code -- custom_components tests tests_ha .github requirements-dev.txt requirements-ha-test.txt pyproject.toml hacs.json`은 exit 0이다. 새 기준 이력 구성과 원격 반영은 아직 수행하지 않았다.

- 2026-10-09 저장소 정리 checkpoint — `.gitignore`의 루트 로컬 자산·HA 시험 출력 제외, CODE_RULES의 실제 HA job 안내, plan의 OpenRouter 준비 예외, 결과 보고 링크를 수정했다. 독립 읽기 전용 검토에서 blocking finding 없음; `git diff --check` exit 0이며 `git diff --exit-code -- custom_components tests tests_ha .github` exit 0으로 제품·시험·CI 변경 없음을 확인했다. 기존 streaming branch의 9개 출력 시험 시나리오와 추가 취소·제한 계약이 현재 코드에 반영되어 있음을 대조했고 해당 worktree는 clean이다. 다만 `git bundle create .venv/archives/VOICE-REDESIGN-1/pre-cleanup-all-refs.bundle --all`은 PreToolUse의 KH-WORKER-001이 미등록 하위명령을 통합으로 분류하여 실행 전 차단했다. 새 복구본은 생성되지 않았고 이력·branch·worktree 삭제 및 강제 push는 수행하지 않았다. 다른 명령으로 같은 백업 동작을 우회하지 않는다. 남은 작업은 정상 경로의 복구본 생성, 새 기준 이력 구성, 원격·로컬 동기 및 보존 확인 후 이전 작업공간 회수다.

- 2026-10-09 최종 검증 checkpoint — unit 176개 OK(.venv/final-response-unit.log), HA 2026.3.0·2026.10.0 각각 88개 passed(.venv/final-response-ha3.log, .venv/final-response-ha10.log), 각 93 warnings는 HA/aiohttp·backoff 외부 라이브러리 경고다. 명령: `.venv/bin/python -B -m unittest discover -s tests -v`; `.venv/ha/bin/python -B -m pytest -p no:cacheprovider tests_ha -q --basetemp=.venv/final-response-ha3`; `.venv/ha-live/bin/python -B -m pytest -p no:cacheprovider tests_ha -q --basetemp=.venv/final-response-ha10`. 전체 Ruff check·format 58파일·compileall·diff check exit 0. kh-verify full: critic/architect/security/document 4렌즈 findings=[], raw_major_plus=0, confirmed_majorplus=0, needs_user_decision=0, missing_lenses=[], execution_failures=[], review_green=true, adversarial_ran=false, test_adequacy_warn=false, device_recommended=true. MAJOR+ 없어 적대검증 미발동. 문서의 오래된 책임 설명 1건은 현재 설계에 맞춰 정정 후 재확인했다. QA5: docx/API_SPEC/Swift 접근제어 해당없음; SynthesizedAudio·AudioStream·factory·runtime·HA facade 및 fixtures 소비자 cascade 확인, PATTERNS 정합. build_green=true, scope_ok=true, integration_conflict=false(main=origin/main=2a5d510으로 기준 유지). 실제 Gemini/Mistral/MiniMax HD 재생 성공은 사용자 관측이며 자동 시험과 구분한다. OpenAI·xAI는 키 부재로 실계정 미검증; 모든 모델·기기 검증으로 확대하지 않는다. device: verified는 이 확인 범위에 한한다. 검증 기준 commit은 `4e797566107b830791998f50f5df4d6969f729b2`이며 이전 이력의 bundle에서 확인한다. 검증본 설치 30파일 SHA-256 일치와 재시작 후 HTTP 200을 확인했고, 설치 영수증은 보존한 `.venv/deployments/20261009-143557/receipt.json`이다. 사용자의 device·통합 승인은 이 검증 범위를 대상으로 한다.

- 2026-10-09 PCM 응답 관측 보완 — 실제 응답 헤더의 검증된 rate·channels 또는 고정 missing/invalid 상태만 PCM 처리 전에 기록하도록 변경했다. 원문 헤더·키·발화는 기록하지 않는다. 모델 보완값과 섞기 전 응답 자체의 정보를 관측한다. 테스트·추가 리뷰·공급자 호출은 수행하지 않는다. 다음 실제 재생의 응답 관측을 기다리며 전체 종결은 대기한다.

- 2026-10-09 PCM 보완 설정 정정 — OpenRouter Gemini 응답에서 rate·channels 누락을 확인하지 않고 등록했던 24 kHz·모노 보완값과 모델 항목을 제거했다. 기존 로그는 매개변수를 제외한 audio/pcm만 남기므로 누락 여부를 판정할 수 없다. native Google의 PCM 규격은 OpenRouter 응답 헤더 누락의 근거가 아니라는 점을 문서에 반영했다. 기본 요청 pcm과 실제 거절 응답으로 확인한 MiniMax HD의 mp3 예외는 유지한다. 테스트·추가 검증·공급자 호출은 실행하지 않는다.

- 2026-10-09 요청 형식 설정 변경 — 사용자가 Mistral·Gemini 실제 재생 성공을 확인했다. 승인된 MiniMax Speech 2.8 HD 진단 1회는 HTTP 400과 streaming response_format mp3 only / got pcm 오류를 반환했다. 응답 수신 전 요청 거절이므로 응답 감지만으로 해결할 수 없다. 별도 JSON defaults.request_format=pcm 및 정확한 모델 ID minimax/speech-2.8-hd의 request_format=mp3를 적용한다. 모델 자체의 모든 경로에서 PCM 미지원이라는 해석은 배제한다. 테스트·추가 리뷰·공급자 재호출은 사용자 지시에 따라 실행하지 않는다. 이번 변경의 실제 재생과 전체 종결은 대기한다.

- 2026-10-09 HA 스트림 타입 수정본 설치 — 제품 `52e9ee65b4e0abf4f71bc0adefdad4e7b7a31aa8`의 tts.py를 기존 파일 백업 후 반영했다. 영수증 `.venv/deployments/20261009-134013/receipt.json`. Docker restart 명령 exit 0. 테스트·추가 리뷰·설치 후 smoke는 실행하지 않았고 실제 재생 성공은 확인되지 않았다. device pending과 미검증 상태 유지.

- 2026-10-09 HA 스트림 타입 오류 진단 — 13:37:21·13:38:00 사용자 요청은 HTTP 200/audio/pcm 이후 HA tts의 메시지 없는 오류로 실패했다. HA 2026.10.0 소스 `_async_convert_audio`는 입력을 collections.abc.AsyncGenerator로 assert하지만 설치 코드의 TTSAudioIterator는 해당 타입을 구현하지 않는다. 이 불일치를 수정한다. 공급자 HTTP 실패 해석은 상태 200과 통합 요청 실패 경고 부재로 배제한다. 재확인 위치: `.venv/ha-live/lib/python3.14/site-packages/homeassistant/components/tts/__init__.py:374`, `custom_components/universal_stt/tts.py`의 TTSAudioIterator. 사용자 지시대로 테스트·추가 리뷰는 하지 않으며 실제 오류 진단과 수정만 수행한다.

- 2026-10-09 응답 형식 수정본 설치 — 제품 `31e4967247bb7c4aa8cdabe4cb04c11190c40416` 30파일을 기존 설치본 백업 후 반영했다. 영수증 `.venv/deployments/20261009-133622/receipt.json`, 복구본 `/config/.voice-install-20261009-133622/previous`. Docker restart 명령 exit 0. 사용자 지시에 따라 재생 시험·HTTP smoke·모듈 import·로그 추가 검사·해시 대조는 실행하지 않았다. 정상 로드·재생 성공을 주장하지 않으며 device pending 유지.

- 2026-10-09 응답 형식 재생 구현 기록 — 요청별 SynthesizedAudio와 준비된 스트림에 확장자를 담고 OpenRouter의 MP3/WAV/PCM 응답을 처리하도록 연결했다. PCM 헤더 metadata 우선, JSON의 정확한 모델 fallback, 완성/스트리밍 WAV framing, entry 소유·deadline 정리 코드를 작성했다. 사용자 지시로 테스트·lint·compile·독립 리뷰를 수행하지 않았으며 이번 변경에 review_green/build_green 판정을 부여하지 않는다. 이전 테스트 결과는 이번 코드에 적용되지 않는다. chain-termination=repair-needed/device-wait, 전체 graph 종결은 하지 않는다. 설치는 기존 사용자 승인 범위의 미검증 수정본 반영이다.

- 2026-10-09 테스트·추가 리뷰 중단 — 사용자가 이번 수정의 테스트와 추가 검증을 명시적으로 중단시켰다. 구현·설치는 계속하되 자동 테스트·lint·compile·독립 리뷰를 새로 실행하지 않고 검증되지 않은 변경으로 보고한다. 이전 checkpoint의 통과 결과를 이번 변경의 증거로 재사용하지 않는다. 전체 graph 종결과 device verified 주장은 하지 않는다.

- 2026-10-09 응답 기반 재생 요구 교정 — 사용자 시험 두 건(13:24:58, 13:25:48)에서 HTTP 200/audio/pcm을 관측했고 사용자는 Mistral을 통합 구성에서 변경·저장했음을 확인했다. 요청 생략만 반영하고 PCM 재생을 누락한 구현 범위를 교정한다. 실제 응답 형식을 처리하고 요청별 확장자를 HA에 전달한다. 명시적 요청 포맷 선택 중심의 이전 registry 설계는 응답 metadata 우선·누락값만 설정 보완하는 설계로 대체한다. 예전 미검증 WIP는 그대로 복원하지 않는다. 실제 오디오 body는 수집하지 않았으며 device pending 유지.

- 2026-10-09 형식 생략 시험 설치 — 제품 `c0deac70e8b3fca6ee3745936db0638b0e3432c7`의 26파일을 백업 후 설치하고 SHA-256을 대조했다. 영수증 `.venv/deployments/20261009-132312/receipt.json`, 복구본 `/config/.voice-install-20261009-132312/previous`. HA 2026.10.0 재시작 2026-10-09T04:23:30Z 후 웹 HTTP 200, 기존 STT/TTS entity ID 유지, 형식 생략/probe import 및 초기 통합 오류 0건 확인. 설치 성공은 Mistral 응답·재생 성공을 뜻하지 않는다. 사용자의 수동 시험과 안전한 HTTP/MIME 로그 확인을 기다리며 device pending 유지.

- 2026-10-09 OpenRouter 형식 생략 시험 checkpoint — OpenRouter TTS만 response_format 키를 생략하며 상태/허용 목록 MIME만 관측한다. 전체 unit 163개 OK(`.venv/omit-unit.log`), HA 2026.3.0·2026.10.0 각각 78개 passed/83 warnings(`.venv/omit-ha3.log`, `.venv/omit-ha10.log`); Ruff check·format 53파일·compileall·diff check 통과. 재확인 명령: `.venv/bin/python -B -m unittest discover -s tests -v`; `.venv/ha/bin/python -B -m pytest -p no:cacheprovider tests_ha -q --basetemp=.venv/omit-ha3-tmp`; `.venv/ha-live/bin/python -B -m pytest -p no:cacheprovider tests_ha -q --basetemp=.venv/omit-ha10-tmp`. kh-verify full 4렌즈 완료: raw_major_plus=0, confirmed_majorplus=0, needs_user_decision=0, missing_lenses=[], execution_failures=[], review_green=true, adversarial_ran=false, device_recommended=true. MINOR는 PCM 거절 보장 범위를 명시적인 MIME으로 한정하고 octet-stream의 코덱 미검증을 영한 README/plan에 적으며 새 테스트의 graph scope를 보완했다. architecture test_adequacy_warn=true는 octet-stream의 실제 코덱·재생 확인 필요성으로 보존한다. QA5: public protocol/schema·STT·native 공급자 변경 없음; Transport.stream의 기본 인자 호환과 소비자·정리 계약 확인, API_SPEC/docx/언어 접근제어 해당없음. 실제 Mistral은 미호출·미검증이며 chain-termination=device-wait, 전체 제품 종결과 base 통합은 하지 않는다.

- 2026-10-09 포맷 생략 시험 우선 — 사용자가 Mistral을 직접 시험하기 위해 요청 포맷을 비우도록 지시했다. 필드를 아예 생략하는 의미로 구현한다. 미검증 registry/PCM 작업 파일 12개와 tracked diff를 `.venv/format-registry-wip/`에 SHA-256 검증해 보관한 뒤 제품 파일만 검증된 `e11f8dd`로 복원했다. 그 위에 OpenRouter TTS 요청 필드 생략과 제한된 상태/MIME 관측을 구현한다. 모델별 자동 형식 선택이 실제로 존재한다고 미리 단정하지 않는다. 시험 후 형식 설정 분리 작업을 이어가며 미검증 보관본을 그대로 배포하지 않는다.

- 2026-10-09 TTS 설정 분리 계획 게이트 — 기존 graph에 T1 계획을 보완했다. 정확한 모델 ID의 JSON 규칙·executor 읽기·미등록 TTS의 HTTP 전 실패·PCM 프레임 변환을 채택하고 STT 및 native 공급자 계약을 보존한다. 독립 critic의 slices_assemblable/scope_disjoint/spec_no_drift/open_questions_zero/ready 모두 true, blocking findings=[]이다. 구현 writer는 기존 graph worktree를 계속 사용하며 제품 형식 loader·JSON·client·setup·TTS 모델 선택·번역·PCM 변환·관련 테스트·README를 순차 소유한다. graph/plan/issues는 리드가 소유한다. 코드 검증과 실제 재생은 아직 남아 있다.

- 2026-10-09 모델별 형식 설정 요구 — 사용자는 TTS 모델별 지원 형식 규칙을 독립 설정 파일로 분리하고 향후 그 파일만 수정할 수 있도록 요청했다. STT는 필요 여부 조사만 허용했으므로 설정·요청·실행 코드를 변경하지 않는다. 승인된 단일 진단 호출에서 HTTP 400 및 Gemini TTS가 pcm만 지원하지만 mp3를 받았다는 오류를 확인했다. 키는 프로세스 메모리에서만 사용했고 오류 문구의 키·URL은 마스킹했으며 원본 응답은 저장하지 않았다. 1회 호출 승인은 소진됐다. Gemini 음성 ID 대소문자 문제라는 해석은 목록 선택 확인과 명시적 형식 오류로 배제한다. 재확인 근거: 설치 제품 775acbd의 client.py speech_body가 MP3를 일괄 요청하고 공개 OpenRouter TTS 문서의 Gemini 예제는 PCM을 요청한다. 유료 재호출 없이 로컬 공급자 재현과 실제 HA 디코더 시험으로 교정한다.

- 2026-10-09 진단 설치·실제 실패 확인 — 제품 `775acbd4a74c9f04392557d33dab0148e70a69ce` 26파일을 백업 후 설치했다. 영수증 `.venv/deployments/20261009-125548/receipt.json`, 서버 복구본 `/config/.voice-install-20261009-125548/previous`. HA 2026.10.0 재시작 후 웹 HTTP 200, 26파일 SHA-256 일치, 새 진단 import, 기존 STT/TTS ID 유지 및 초기 통합 오류 0건 확인. 사용자 재생 직후 12:56:44 로그는 `category=http phase=acquire http_status=400`으로 OpenRouter의 요청 거절을 확인했다. 이전의 generic STTError만으로 연결 장애·음성 ID 문제를 확정할 수 없다는 판단을 대체하는 실제 근거다. 재확인: `docker logs --since 10m homeassistant 2>&1 | grep 'custom_components.universal_stt'`. 응답 본문·인증 정보는 읽지 않았다. HTTP 400만으로 거절된 필드를 특정할 수 없어 사용자 입력 방식·공급자 오류 문구 확인 중이며 device pending 유지.

- 2026-10-09 TTS 진단 보완 checkpoint — HTTP 상태와 고정 실패 종류·단계를 TTS 경고에 전달한다. payload·음성 ID·재시도·취소·응답 정리 계약은 유지한다. 신규 fixture의 임시 모듈 identity 오류를 교정한 뒤 전체 unit 159개 OK(`.venv/tts-diagnostics-unit-recheck.log`), HA 2026.3.0·2026.10.0 각각 78개 passed(`.venv/tts-diag-ha3.log`, `.venv/tts-diag-ha10.log`), 전체 Ruff check·format 52파일·compileall·diff check exit 0. 명령은 앞 checkpoint의 unit/HA 명령과 동일하고 basetemp는 tts-diag-ha3/ha10으로 격리했다. kh-verify full 4렌즈(critic/architect/security/document) findings=[], raw_major_plus=0, confirmed_majorplus=0, needs_user_decision=0, missing_lenses=[], execution_failures=[], review_green=true, adversarial_ran=false, test_adequacy_warn=false, device_recommended=true. MAJOR+ 없어 적대검증 미발동. QA5: API_SPEC/docx/언어 접근제어 해당없음, STTError 소비자·인증 하위 타입·PATTERNS·영한 문서 계약 확인. chain-termination=repair-needed/device-wait: 안전한 진단 설치 후 실제 공급자 실패를 다시 확인해야 하며 root cause 해결이나 전체 제품 종결로 판정하지 않는다.

- 2026-10-09 실제 TTS 실패 조사 — HA 로그에 TTS stream failed (STTError)가 기록됐고 사용자는 OpenRouter의 google/gemini-3.8-flash-tts 및 Kore 음성을 사용한다고 확인했다. 오디오 생성 stream에서 실패했으므로 스피커 자체 문제로 단정하지 않는다. 기존 로그가 HTTP 상태·전송 단계를 없애므로 원인 확정에 필요한 안전한 진단을 S2/S5 범위에서 보완한다. 입력·키·URL·응답 본문은 기록하지 않는다. 공개 모델 목록에는 Kore가 있으며 실제 저장 값의 대소문자는 확인하지 않았다. 공급자 유료 호출은 수행하지 않으며 device pending을 유지한다.

실행 준비 기록: worktree 생성 후 훅이 branch/base/owner를 대장에 적립한 것을 확인했다. 보호 대장 변경에 대한 사용자 승인 후 공식 `kollhong-worktree-ledger.py set`으로 `device_requirement=required` 등록을 완료했다. 이 문서의 pending은 실기기 검증 미완료를 뜻한다. Git의 `core.hooksPath`는 미설정이고 `.git/hooks`에는 샘플만 있으므로 전체 Git 게이트 작동을 확인했다고 주장하지 않는다.
