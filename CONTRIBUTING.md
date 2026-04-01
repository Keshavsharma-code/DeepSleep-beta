# Contributing

DeepSleep will move faster if contributors can reproduce the core loop in a few minutes.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## What to work on

- better local-model prompts
- richer memory compaction strategies
- more terminal UX polish
- safer file-aware editing flows
- more dream triggers and integrations

## Ground rules

- keep the local-first promise
- do not add hosted API requirements by default
- keep the memory file deterministic and compact
- prefer small, composable commands over hidden magic
- include tests for behavior changes

## Before opening a PR

Run:

```bash
pytest -q
ds doctor
```

If you add a user-facing command, update the README.
