# Work Records

[GLOSSARY.md](GLOSSARY.md) contains existing product and domain terms.

When a task needs durable governance records, use `graphs/` for its plan and
dependencies, `issues/` for completion reports, and `questions/` for user decisions.
Create records when work requires them; no active Epic or ticket prefix is assumed.

## Design and results

- [STT/TTS redesign plan](plans/VOICE-REDESIGN-1.md): intended behavior, contracts, and acceptance criteria.
- [Execution graph](graphs/VOICE-REDESIGN-1.md): file ownership, dependencies, evidence, and execution prerequisites.
- [Generated board](BOARD.md): current graph status.
- [Implementation and verification reports](issues/VOICE-REDESIGN-1.md): delivered behavior, evidence, and validation limits.

## Historical evidence

Reports retain the commit IDs of the versions they describe. After the repository
history is rebuilt, those IDs are resolved from the retained Git bundles rather
than from the new main history. The local archive is
`.venv/archives/VOICE-REDESIGN-1/`: `pre-cleanup-all-refs.bundle` preserves the
pre-cleanup branches, `cleanup-ready.bundle` preserves the subsequent cleanup
snapshot, `verified-graph.bundle` preserves the detailed redesign
checkpoints, and `workspace-evidence/` holds verification and installation records.
These archives are local recovery material, not integration distribution files.
Keep them when clearing disposable virtual environments; the directory name does
not make their contents disposable. Old absolute test-environment paths in logs
are historical; use the current root README to recreate a runnable environment.
