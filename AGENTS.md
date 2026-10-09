# HA Universal Voice

This is a single Python Home Assistant integration project. Its integration domain
and source directory remain `universal_stt` and `custom_components/universal_stt/`.
The product supports speech-to-text (STT) and text-to-speech (TTS).

Before changing files, read `docs/rules/AI_RULES.md`. Use `README.md` for current
product behavior and release status, `docs/rules/README.md` for code conventions,
and `work/GLOSSARY.md` for existing domain terms.

Project policy lives in `.kollhong/governance.jsonc`, with the repository root as
the single project anchor. Codex runtime settings live in `.codex/config.toml`.
Global governance is installed under the user's `.kollhong/governance/` directory.

Check Git root and status in the active runtime before Git operations. Preserve
existing files and Git metadata; do not initialize or publish a repository as
part of an unrelated coding task. Read local rules explicitly if hook discovery
cannot resolve this project's root in the current execution environment.

<!-- KOLLHONG-GOVERNANCE:BEGIN -->
<!-- source-digest: sha256:cc8f798f2d60e970da3974dcb548d2d3aeeb21930d150afe58bc3eb5f2dcb095 -->
## Kollhong governance — project:kollhong-architecture

- **[KH-DEFINE-001] 공통 정의 경계** (`block`, `native/partial`)
  - 규칙: 프로젝트가 지정한 공통 정의 폴더 안의 기존 값을 직접 변경·삭제하지 않고, 폴더 밖 파일에서 그 정의를 재발명하지 않는다.
  - 대체: 먼저 공통 정의 폴더에서 필요한 정의를 검색한다. 기존 정의가 있으면 그것을 참조하고, 없으면 공통 폴더에 순수 추가한 뒤 참조한다. 기존 값의 변경·삭제가 반드시 필요하면 worker는 근거와 필요한 결정을 parent에게 반환한다. parent 또는 리드는 해당 편집에 유효한 사용자 [KH-DEFINE-SKIP] 승인이 있으면 재사용하고, 없으면 요청한다. lead 위임은 승인을 대신하지 않으며 기존 값 변경을 피하려고 중복 정의를 추가하지 않는다. 선언을 적을 자리는 셋 중 하나다. 공유물이 폴더나 모듈로 실체가 있으면 그것을 anchor_dir로 하는 프로젝트를 선언해 소유자를 준다. 소유자를 두기 어려운 저장소 전체 규약은 저장소 공통 shared_definitions에 적는다. 프로젝트 블록에 자기 anchor 밖 폴더를 적는 배치는 쓰지 않는다. 심볼릭 링크로 폴더를 공유하지 않는다. 판정이 링크를 따라간 실제 경로로 소유를 정하므로 링크 위치의 소유가 사라진다.
  - 적용: 프로젝트 설정의 shared_definitions.roots가 선언된 경우에만 적용한다.; roots 안 파일 편집에서 기존 내용을 제거(변경·삭제)할 때 적용한다.; roots 밖 파일 편집에서 outside_signals에 등록된 식별자를 새로 추가할 때 적용한다.; 두 판정의 roots는 저장소 공통 선언과 그 경로를 소유한 프로젝트 선언에서만 읽으며 형제 프로젝트의 선언은 합치지 않는다. outside_signals도 같은 선언에서 읽는다.; 프로젝트 설정 파일을 편집할 때 그 편집의 결과 내용으로 선언 배치를 검사한다.
  - 예외: roots 안에 새 정의를 추가(removed_content가 비어 있는 순수 추가)하는 편집은 허용한다.; 테스트 코드 파일(test/·tests/·Tests/ 디렉터리, test_*.*·*_test.* 파일, iOS XCTest 관례인 *Tests.swift 파일과 *Tests/ 디렉터리)은 outside_signals warn 대상에서 제외한다. 면제는 철자 그대로 일치할 때만 적용되어 대소문자를 구분하며, 철자만 겹치는 이름(Contests/·attests.swift)은 면제하지 않는다.; outside_signals가 미선언이면 warn이 발동하지 않는다. roots가 미선언이거나 배열이 아니면 그 선언은 폴더 목록으로 읽지 않으며, 읽을 목록이 하나도 없으면 양 강제 모두 무동작이다.; 선언한 폴더가 아직 저장소에 없으면 알리기만 하고 막지 않는다. 폴더를 만들기 전에 선언을 먼저 적는 순서가 정상이다.; 사용자가 [KH-DEFINE-SKIP]을 포함해 재요청하면 block을 우회한다.
- **[KH-PROJECT-001] 독립 프로젝트 소스 경계 유지** (`block`, `instruction-only/full`)
  - 규칙: 독립 프로젝트가 형제 프로젝트의 내부 소스 심볼을 직접 import하지 않는다.
  - 대체: 공유가 필요하면 팀 결정으로 공용 모듈이나 명시적인 인터페이스 경계를 설계한다.
  - 적용: project registry에서 서로 독립된 anchor로 선언된 프로젝트 사이의 source dependency에 적용한다.
  - 예외: registry와 시스템 설계 문서에 공용 모듈로 명시된 경계는 허용한다.
  - 이전 별칭: `repo-wide 절대금지 #1`
- **[KH-PROJECT-002] 서로 무관한 프로젝트 변경의 commit 분리** (`block`, `instruction-only/full`)
  - 규칙: 한 commit에 서로 무관한 여러 프로젝트의 변경을 함께 묶지 않는다.
  - 대체: 변경 목적과 프로젝트 경계에 따라 stage 범위를 나누고 프로젝트별 독립 commit으로 기록한다.
  - 적용: 하나의 repository 안에서 둘 이상의 독립 project anchor가 변경된 commit을 만들 때 적용한다.
  - 예외: 원자적 API migration이나 repository-wide tooling 변경처럼 모든 project가 함께 바뀌어야 하는 근거가 있으면 허용한다.
  - 이전 별칭: `repo-wide 절대금지 #2`
- **[KH-QUESTION-001] 결정 질문 전 자체 복구·외부 의존 근거** (`block`, `native/partial`)
  - 규칙: work/questions에 새 결정 문서를 만들 때 첫 근거 섹션에 안전하게 시도한 자체 복구와 그 결과, 또는 외부 의존·결정권자·자체 해결 불가 사유를 기록한다. 자체 해결 불가 사유가 규칙의 예외 조항이면 그 조항의 성립 조건을 확인한 결과를 함께 적고, 결정을 항목으로 누적하는 양식에서는 이 근거를 항목마다 적는다. 질문이 기대는 환경 사실(도구 설치·인증 상태·파일 존재·설정 값·기존 기록의 현재 유효성)은 읽기 전용 명령으로 확인해, 신규 문서 §0과 새로 추가하는 결정 항목마다 「전제 확인:」 줄에 명령과 출력 요지를 적는다. 확인할 환경 사실이 없으면 그 이유를, 확인이 다른 규칙에 막히면 막는 규칙과 대신 확인한 것을 같은 줄에 적는다.
  - 대체: 사용자에게 즉시 질문하기 전에 안전한 자체 확인과 복구를 수행하고, 제품 방향·권한·외부 계약처럼 사용자의 결정이 필요한 사안만 근거를 갖춘 questions 문서로 routing한다. 규칙에 막혀 질문이 생기면 그 규칙이 이미 정한 대체 행동이 있는지 먼저 보고, 예외 조항으로 가려면 그 조항의 성립 조건을 명령으로 확인한다. 조건이 성립하지 않으면 대체 행동이 유일한 길이므로 묻지 않고 그 행동을 수행한다. 질문 문서를 쓰기 전에 그 질문이 기대는 환경 사실을 `command -v`·`--version`·`<도구> login status`·`gh auth status`·`test -e`·`git config --get` 같은 읽기 전용 명령으로 실측하고 그 명령과 출력 요지를 「전제 확인:」 줄에 붙인다. 자격증명 파일의 내용은 읽지 않으며 상태 조회 명령만 쓴다. 과거 관측 기록은 현재 상태의 근거가 아니므로 지금 다시 확인한다. 확인 명령이 다른 규칙에 막히면 막는 규칙 ID 또는 권한 사유와 대신 확인한 것을 적는 것으로 갈음하고 그 확인 불가를 근거로 달성안을 빼지 않는다.
  - 적용: governed project의 work/questions에 새 결정 문서를 생성하거나, 기존 결정 문서에 새 대기 항목을 추가·편집할 때 적용한다.
  - 예외: 안전·권한·제품 방향처럼 시도 자체가 사용자 결정을 침범하는 사안은 복구 실행 없이 질문할 수 있다.; 범위를 넘길지와 발견을 후속으로 미룰지를 묻는 결정은 자체 복구로 해소되는 실행 세부가 아니므로 복구 시도 기록 없이 제시할 수 있다.
- **[KH-SWIFT-003] 프로젝트별 Swift 네이밍 규칙** (`block`, `native/partial`)
  - 규칙: Swift 코드의 신규·변경 라인은 프로젝트별 naming_guard 규칙을 따르며 block 규칙 위반은 쓰기 전에 고친다.
  - 대체: 해당 프로젝트의 NAMING_CONVENTION과 hook settings를 확인해 금지된 함수·타입 이름을 권장 이름으로 바꾸고, 정당한 권고 예외는 canonical 설정에서 warn으로 관리한다.
  - 적용: project registry가 소유하는 Swift 파일의 신규·변경 identifier에 적용한다.
  - 예외: canonical project policy에서 warn으로 분류된 패턴은 근거를 확인하고 진행할 수 있다.
- **[KH-SWIFT-004] 실기기·외부 시스템 의존의 교체 가능한 DI 경계** (`warn`, `native/partial`)
  - 규칙: 새로 만들거나 수정하는 Swift production code가 Keychain·APNS·공유 네트워크 세션·권한 API처럼 비결정적이거나 부작용이 있는 외부 시스템에 의존하면 protocol 또는 동등한 표준 주입 경계로 의존성을 교체 가능하게 설계한다.
  - 대체: 구체 API 참조를 protocol이나 프로젝트의 표준 test seam 뒤로 옮기고 생성자·factory·주입 프로퍼티로 운영 구현과 CI용 fake/mock을 교체할 수 있게 한다.
  - 적용: 신규·기존 Swift production code가 비결정적이거나 부작용이 있고 CI에서 직접 재현하기 어려운 외부 시스템 의존을 추가·변경할 때 적용한다.
  - 예외: 앱 composition root의 운영 구현 조립 코드와 플랫폼이 이미 제공하는 표준 test seam을 사용하는 경계는 대체 가능성을 검증한 근거가 있으면 허용한다.

각 룰의 강제 한계(어떤 경로를 못 잡는지)는 이 목록에 싣지 않고 `$KOLLHONG_HOME/governance/ENFORCEMENT_MAP_FULL.md`에 둡니다 (`KOLLHONG_HOME` 기본값 `$HOME/.kollhong`, installer의 `--shared-root`로 바꾼 경우 그 경로).
<!-- KOLLHONG-GOVERNANCE:END -->
