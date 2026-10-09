# Code and Verification

Follow the existing Python Home Assistant integration patterns. Preserve async
behavior, existing configuration migration behavior, and provider-specific API
contracts. Keep API keys and user audio out of logs, fixtures, and commits.

`pyproject.toml` owns the Ruff configuration: Python 3.11 syntax target, line length
100, and E/F/I lint checks. CI uses Python 3.13; do not silently change either.

Use the relevant tests during development. The project CI checks, from
`.github/workflows/checks.yml`, are:

```bash
ruff check .
ruff format --check .
python -m compileall -q custom_components
python -m unittest discover -s tests -v
```

Use the project's existing virtual environment where available. A passing local
suite is not evidence of real Home Assistant installation or paid provider testing.

CI also runs `tests_ha/` in a separate Python 3.14.2 job with FFmpeg and the
Home Assistant dependencies pinned in `requirements-ha-test.txt`:

```bash
python -B -m pytest -p no:cacheprovider tests_ha -v --basetemp=.ha-test-tmp
```

Keep this job separate from unit tests, which install HA interface substitutes.
The HA suite uses real Home Assistant interfaces with local provider responses;
it does not establish live provider or speaker behavior. See the root README
for environment setup and the versions actually verified.
