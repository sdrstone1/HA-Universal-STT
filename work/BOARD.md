<!-- GENERATED FILE — DO NOT EDIT. work/graphs/<Epic>.md 머리말에서 재생성된다. -->
<!-- 갱신: graph 문서를 만든 직후와 그래프 종결 finalize에서 재생성한다 — Claude는 python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/bin/kollhong-board-render.py" <work 경로>, Codex는 python3 "${CODEX_HOME:-$HOME/.codex}/bin/kollhong-board-render.py" <work 경로>. -->
# work/BOARD.md — 전역 보드 (활성 Epic + 불변 목표)

> **용도**: 활성 Epic의 [불변 목표 + 상태] cross-Epic 단일 인덱스. **세션 진입점**.
> **진입**: 본 BOARD → 활성 Epic 식별 → 그 Epic의 `graphs/`·`plans/` 진입.
> 목표·트랙·상태의 정본은 각 `graphs/<Epic>.md` 머리말이다. 이 파일을 고치지 말고 그쪽을 고친 뒤 재생성한다.
> 완료한 Epic은 여기서 빠진다 — 완료 보고는 `issues/<Epic>.md`, 이력은 `git log --grep <Epic>`.
> 다른 worktree에서 진행 중인 Epic도 오른다. 그 행은 이 checkout에 문서가 없으므로 링크 대신 **어느 브랜치에 있는지**를 싣는다.

| Epic | 목표 (불변) | 트랙 | 상태 | plan · graph · issues |
|---|---|---|---|---|
| — | 활성 Epic이 없다 | — | — | — |
