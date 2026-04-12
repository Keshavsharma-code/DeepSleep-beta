# DeepSleep-beta

[![PyPI version](https://img.shields.io/pypi/v/deepsleep-ai.svg)](https://pypi.org/project/deepsleep-ai/)
[![Python versions](https://img.shields.io/pypi/pyversions/deepsleep-ai.svg)](https://pypi.org/project/deepsleep-ai/)
[![CI](https://github.com/Keshavsharma-code/DeepSleep-beta/actions/workflows/ci.yml/badge.svg)](https://github.com/Keshavsharma-code/DeepSleep-beta/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

![DeepSleep social preview](./assets/social-preview.svg)

DeepSleep is the open-source background agent for local models. It gives developers a `ds` workflow, a compact 3-layer memory file, and idle-time "dreaming" that summarizes recent work while they are away.

---

## 🔗 The Digital Ecosystem
*   **[DeepSleep-Hub](https://github.com/Keshavsharma-code/deepsleep-hub)**: Our browser-based companion. A universal neural bridge for ChatGPT, Claude, and Gemini with a 3D Visual Cortex.

---

## 🐣 The Dumbest Guide (Read this if you're lost)

### What is this?
Imagine you're coding. You take a coffee break. You come back and forget what you were doing. **DeepSleep** was watching your files while you were gone. It "dreamed" about your changes and wrote a summary. Now you just ask `ds > What was I working on?` and it tells you. **It's like a brain for your folder.**

### How to use (The 3-step shuffle)
1. **Init**: Open your terminal in your project folder and type `ds init`. This makes a tiny hidden brain folder (`.deepsleep`).
2. **Dream**: Run `ds dream` in a corner of your screen. It just sits there. When you stop typing for a bit, it writes down what you did.
3. **Chat**: Type `ds` whenever you want to talk to your code. Ask things like *"Where did I leave that API key?"* or *"What's next?"*

### How to deal with errors ️
- **"Ollama not found"**: You need [Ollama](https://ollama.com/) running. It's the engine. Download it, run it, and try again.
- **"Permission Denied"**: DeepSleep needs to write its memory file. Make sure you have permission to write in the current folder.
- **"Stuck dreaming"**: If `ds dream` isn't doing anything, make sure you actually *saved* some files. It only dreams when things change!
- **"Garbage answers"**: Local models can be silly. Type `/memory` to see what it actually remembers. If it's wrong, you can just tell it!

---

## 🎯 v1.0 Production-Grade Features (New!)

We've hardened DeepSleep for enterprise-level monorepos:

- **🔒 Atomic Security**: `FileLock` prevents memory corruption even if you run multiple `ds` instances.
- **🛡️ Path Traversal Sandbox**: DeepSleep is now locked to your project root. It will never leak your `.ssh` or `.env` files to the AI.
- **📂 Gitignore-Aware**: It respects your `.gitignore` perfectly. No more indexing `node_modules` or `dist` garbage.
- **⚡ Incremental Indexing**: Uses a local SQLite index to track millions of files instantly without slowing down your machine.
- **🔐 At-Rest Encryption**: Use `ds init --encrypt` to protect your project memory with a password (AES-256).
- **📝 Structured Observability**: Now with `structlog` for clean, machine-friendly logs and a `ds health` command.

---

## Why it lands fast

- `pip install deepsleep-ai`
- `ds init`
- `ds`
- `ds dream`

That is the product.

You initialize a repo once, ask natural questions in the terminal, and let DeepSleep update session context after you stop typing.

## Core promise

- `Zero-cost agent`: runs on local Ollama models instead of paid tokens
- `Idle-time dreaming`: watches your repo and summarizes after inactivity
- `3-layer memory`: `project`, `session`, and `ephemeral`
- `Terminal-native`: hacker-style interactive UI with file completion

## Search-friendly positioning

DeepSleep is best described as:

- an open-source AI coding agent
- a local AI developer tool
- a background agent for codebases
- a terminal copilot for Ollama
- a local-model alternative to hosted coding assistants

## Quick demo

```bash
pip install deepsleep-ai
ollama pull deepseek-r1
ds init
ds dream --once
ds
```

Then ask:

```text
What was I doing?
Refactor src/deepsleep_ai/cli.py
Summarize the recent changes
```

## 3-layer memory architecture

DeepSleep explicitly implements a 3-layer memory stack:

- `project`: long-term repo identity, goals, and facts
- `session`: what you were doing recently, which files were active, and the latest dream summary
- `ephemeral`: last turns, open questions, and the most recent file changes

All of it lives in `.deepsleep/memory.json`, and the compactor keeps that file under `2KB` so it stays fast, deterministic, and portable.

## Zero-cost local model stack

DeepSleep is built for [Ollama](https://ollama.com/) and targets `deepseek-r1` by default.

If Ollama is offline, DeepSleep still works with deterministic local fallbacks so demos do not collapse and the tool remains usable on day one.

## Idle-time dreaming

Run `ds dream`, leave your editor open, and DeepSleep watches your project for file saves.

After `5 minutes` of inactivity, it:

1. collects the files you touched
2. reads compact local snippets
3. writes a fresh session summary into memory
4. preserves only the highest-signal context under the 2KB cap

## Install

### PyPI

```bash
pip install deepsleep-ai
```

Quick check:

```bash
ds --version
ds health
```

### Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Ollama

```bash
ollama serve
ollama pull deepseek-r1
```

## Commands

```bash
ds init          # Start a new brain for your project
ds init --encrypt # Start a password-protected brain
ds               # Start chatting
ds chat          # Alias for ds
ds dream         # Start the background watcher
ds dream --once  # Run one dream cycle right now
ds status        # Peek inside the brain
ds health        # Check if everything is setup correctly
```

## Package layout

- [`cli.py`](./src/deepsleep_ai/cli.py): Typer entrypoint and Prompt Toolkit UI
- [`watcher.py`](./src/deepsleep_ai/watcher.py): Watchdog-based idle watcher and dream loop
- [`memory_manager.py`](./src/deepsleep_ai/memory_manager.py): layered memory store with 2KB compaction
- [`llm_client.py`](./src/deepsleep_ai/llm_client.py): Ollama connector with safe local fallback
- [`config.py`](./src/deepsleep_ai/config.py): Pydantic-powered configuration management

---

## 🤝 Contributing

We love builders! If you want to make DeepSleep even better:

1. **Check the Roadmap**: See what we're building in [ROADMAP.md](./ROADMAP.md).
2. **Read the Guide**: Hop into [CONTRIBUTING.md](./CONTRIBUTING.md) for setup steps.
3. **Open an Issue**: Found a bug? Tell us!
4. **Pull Requests**: Send your code. We're fast at reviewing.

*Note: Please ensure all tests pass (`pytest`) before submitting!*

---

## Trust signals

- publishable `pyproject.toml` for `pip install deepsleep-ai`
- `ds` console entrypoint
- MIT license
- GitHub Actions CI
- tests for memory compaction, watcher behavior, offline fallback, and chat exit flow
- live PyPI package: [deepsleep-ai](https://pypi.org/project/deepsleep-ai/)

## Self-test

```bash
pytest -v
python -m deepsleep_ai --help
python -m build --no-isolation
```

---

There is a practical launch playbook in [`LAUNCH.md`](./LAUNCH.md), a contributor guide in [`CONTRIBUTING.md`](./CONTRIBUTING.md), release instructions in [`RELEASING.md`](./RELEASING.md), and a project history in [`CHANGELOG.md`](./CHANGELOG.md).
