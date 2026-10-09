# Existing Patterns

Inspect the relevant implementation in `custom_components/universal_stt/` and its
matching test in `tests/` before choosing an implementation pattern. The current
test modules cover core behavior, Gemini, languages, TTS entities, and voice flow.

Reuse existing configuration, provider, and mocking patterns where they fit.
Check callers before changing shared APIs. Do not introduce a parallel provider
abstraction or duplicate constants merely to avoid examining existing code.
