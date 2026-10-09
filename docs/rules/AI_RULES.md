# Agent Work Rules

Read the requested behavior and current release constraints in `README.md`, the
affected source and tests, and [CODE_RULES.md](CODE_RULES.md) before editing.
Keep work scoped to the request and preserve concurrent changes.

Use the existing `custom_components/universal_stt/` integration and `tests/` layout.
Do not rename the integration domain, installed directory, or existing entity IDs
as a consequence of the HA Universal Voice product name.

Do not make live provider requests, publish releases, or deploy to Home Assistant
unless the task authorizes those actions. Report local test results separately
from real Home Assistant and audio-provider validation. Mock tests do not establish
that a provider or speaker works in the user's installation.

Document current behavior in the existing root README when behavior changes.
Use work/graphs, work/issues, and work/questions for their governance purposes
when those artifacts are needed; do not invent a ticket prefix or issue ID.
Verify Git-based governance gates and hook discovery in the active runtime before
reporting them as operational.
