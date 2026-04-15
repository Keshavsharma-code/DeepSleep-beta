<div align="center">

# 🧠 DeepSleep

### Your codebase has a memory now.

*A zero-cost background agent that watches your files, dreams while you're away, and answers "what was I doing?" — 100% local, no subscriptions, no cloud.*

[![PyPI version](https://img.shields.io/pypi/v/deepsleep-ai.svg?style=flat-square&color=blueviolet)](https://pypi.org/project/deepsleep-ai/)
[![Python versions](https://img.shields.io/pypi/pyversions/deepsleep-ai.svg?style=flat-square)](https://pypi.org/project/deepsleep-ai/)
[![CI](https://github.com/Keshavsharma-code/DeepSleep-beta/actions/workflows/ci.yml/badge.svg?style=flat-square)](https://github.com/Keshavsharma-code/DeepSleep-beta/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](./LICENSE)
[![PyPI Downloads](https://img.shields.io/pypi/dm/deepsleep-ai?style=flat-square&color=orange)](https://pypi.org/project/deepsleep-ai/)
[![GitHub Stars](https://img.shields.io/github/stars/Keshavsharma-code/DeepSleep-beta?style=flat-square&color=yellow)](https://github.com/Keshavsharma-code/DeepSleep-beta/stargazers)

<br>

<a href="https://www.producthunt.com/products/deepsleep-2?embed=true&utm_source=badge-featured&utm_medium=badge&utm_campaign=badge-deepsleep" target="_blank" rel="noopener noreferrer">
  <img alt="DeepSleep - The coding agent that dreams while you sleep | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1122051&theme=light&t=1776152379902">
</a>

<br><br>

![DeepSleep social preview](./assets/social-preview.svg)

</div>

---

## The Problem

You take a coffee break. You come back. You stare at the screen.

**"Wait... what was I doing?"**

GitHub Copilot can't help you. ChatGPT doesn't know your codebase. And scrolling through git log at 9am is not a vibe.

**DeepSleep fixes this.** It runs silently in the background, watches your files, and the moment you go idle — it *dreams*. It reads what changed, writes a compact summary, and stores it locally. When you're back, just ask:

```bash
ds > What was I working on?
```

That's it. No cloud. No tokens burned. No subscription.

---

## How It Works

```mermaid
flowchart TD
    A([🧑‍💻 You start coding]) --> B[ds init\nCreates .deepsleep/memory.json]
    B --> C[ds dream\nBackground watcher starts]
    C --> D{Watching for\nfile changes...}
    D -->|Files saved| E[📁 Track changed files\nincremental SQLite index]
    D -->|5 min idle| F[💤 Dream Cycle Triggered]
    E --> D
    F --> G[Read compact file snippets\nfrom changed paths]
    G --> H[🤖 Send to local Ollama model\ndeepseek-r1 by default]
    H --> I[✍️ Generate session summary]
    I --> J[🧠 Write to memory.json\nunder 2KB cap]
    J --> K{You return\nto keyboard}
    K --> L[ds >\nWhat was I doing?]
    L --> M[💡 Instant answer\nfrom local memory]
    M --> D

    style A fill:#1a1a2e,color:#fff,stroke:#7c3aed
    style F fill:#312e81,color:#fff,stroke:#7c3aed
    style H fill:#1e3a5f,color:#fff,stroke:#3b82f6
    style M fill:#14532d,color:#fff,stroke:#22c55e
    style J fill:#4a1942,color:#fff,stroke:#a855f7
```

---

## Memory Architecture

DeepSleep uses a **3-layer memory stack** — all stored in a single `.deepsleep/memory.json` file kept under **2KB**.

```mermaid
block-beta
  columns 3

  space:1
  title["🧠 .deepsleep/memory.json (≤ 2KB)"]:1
  space:1

  project["📌 PROJECT LAYER\n──────────────\nRepo identity\nLong-term goals\nKey facts & decisions\n\n(Permanent)"]
  session["🕐 SESSION LAYER\n──────────────\nRecent activity\nActive files\nLatest dream summary\n\n(Updated each dream)"]
  ephemeral["⚡ EPHEMERAL LAYER\n──────────────\nCurrent chat turns\nOpen questions\nFile changes buffer\n\n(Cleared each session)"]

  compact["🗜️ Memory Compactor — keeps total file under 2KB\nDrops low-signal context, preserves what matters"]:3

  style title fill:#1e1b4b,color:#c4b5fd,stroke:#7c3aed
  style project fill:#14532d,color:#86efac,stroke:#22c55e
  style session fill:#1e3a5f,color:#93c5fd,stroke:#3b82f6
  style ephemeral fill:#4a1942,color:#f0abfc,stroke:#a855f7
  style compact fill:#1a1a2e,color:#94a3b8,stroke:#475569
```

---

## Security Architecture

```mermaid
flowchart LR
    subgraph SANDBOX["🛡️ Path Traversal Sandbox"]
        direction TB
        root["📁 Project Root\n(allowed zone)"]
        blocked1["🚫 ~/.ssh"]
        blocked2["🚫 .env files"]
        blocked3["🚫 ../outside"]
    end

    subgraph MEMORY["🔐 Memory Protection"]
        direction TB
        lock["🔒 FileLock\nAtomic writes only"]
        enc["🛡️ AES-256 Encryption\nds init --encrypt"]
    end

    subgraph INDEXING["⚡ Efficient Indexing"]
        direction TB
        sqlite["📊 SQLite Index\nMillions of files, no slowdown"]
        gitignore["📂 .gitignore Aware\nSkips node_modules, dist, etc."]
    end

    DS["🧠 DeepSleep Engine"] --> SANDBOX
    DS --> MEMORY
    DS --> INDEXING

    style DS fill:#1e1b4b,color:#c4b5fd,stroke:#7c3aed
    style SANDBOX fill:#1a1a1a,color:#fca5a5,stroke:#ef4444
    style MEMORY fill:#1a1a1a,color:#86efac,stroke:#22c55e
    style INDEXING fill:#1a1a1a,color:#93c5fd,stroke:#3b82f6
```

---

## Quickstart

```bash
# 1. Install
pip install deepsleep-ai

# 2. Make sure Ollama is running
ollama serve
ollama pull deepseek-r1

# 3. Initialize your project brain
cd your-project/
ds init

# 4. Start the background watcher
ds dream

# 5. Come back later and just ask
ds
> What was I working on?
> What files did I touch today?
> What's the next thing I should do?
```

> **One-liner demo:**
> ```bash
> pip install deepsleep-ai && ollama pull deepseek-r1 && ds init && ds dream --once && ds
> ```

---

## Commands

| Command | What it does |
|---|---|
| `ds init` | Initialize a memory brain for your project |
| `ds init --encrypt` | Same, but password-protected (AES-256) |
| `ds` | Open the chat interface |
| `ds chat` | Alias for `ds` |
| `ds dream` | Start the background file watcher |
| `ds dream --once` | Run one dream cycle immediately |
| `ds status` | Inspect what's in memory |
| `ds health` | Verify Ollama + DeepSleep setup |

---

## v1.0 Production Features

| Feature | Detail |
|---|---|
| 🔒 **Atomic Security** | `FileLock` prevents memory corruption across concurrent instances |
| 🛡️ **Path Sandbox** | Locked to project root — can never leak `.ssh` or `.env` to the model |
| 📂 **Gitignore-Aware** | Respects `.gitignore` — skips `node_modules`, `dist`, build artifacts |
| ⚡ **Incremental Indexing** | SQLite-based tracker handles millions of files instantly |
| 🔐 **At-Rest Encryption** | Optional AES-256 password protection via `ds init --encrypt` |
| 📝 **Structured Logging** | `structlog` integration + `ds health` for clean observability |
| 📴 **Offline Fallback** | Deterministic local fallbacks when Ollama is unavailable |

---

## Why Local-First?

```mermaid
graph LR
    A["☁️ Cloud Copilots"] -->|"💸 $10-20/mo\n🌐 Sends your code to servers\n📵 Breaks offline\n🔑 API keys to manage"| X["❌"]
    B["🧠 DeepSleep"] -->|"✅ $0 forever\n✅ Your code never leaves\n✅ Works offline\n✅ pip install and done"| Y["✅"]

    style A fill:#3b0d0d,color:#fca5a5,stroke:#ef4444
    style B fill:#14532d,color:#86efac,stroke:#22c55e
    style X fill:#3b0d0d,color:#fca5a5,stroke:#ef4444
    style Y fill:#14532d,color:#86efac,stroke:#22c55e
```

No tokens. No subscriptions. No code leaves your machine. Ever.

---

## Ecosystem

| Project | What it is |
|---|---|
| **[DeepSleep-beta](https://github.com/Keshavsharma-code/DeepSleep-beta)** (you are here) | Python CLI background agent |
| **[DeepSleep-Hub](https://github.com/Keshavsharma-code/deepsleep-hub)** | Browser extension — universal neural bridge for ChatGPT, Claude & Gemini with 3D Visual Cortex |

---

## Troubleshooting

| Error | Fix |
|---|---|
| `"Ollama not found"` | Install [Ollama](https://ollama.com/), run `ollama serve`, then retry |
| `"Permission Denied"` | DeepSleep needs write access to the current folder |
| `"Stuck dreaming"` | Save some files — it only dreams after actual file changes |
| `"Garbage answers"` | Type `/memory` to inspect what it knows; correct it directly in chat |

---

## Package Layout

```
src/deepsleep_ai/
├── cli.py             # Typer entrypoint + Prompt Toolkit chat UI
├── watcher.py         # Watchdog-based idle watcher + dream loop
├── memory_manager.py  # 3-layer memory store with 2KB compactor
├── llm_client.py      # Ollama connector + offline fallback
└── config.py          # Pydantic-powered configuration
```

---

## Contributing

1. Check [ROADMAP.md](./ROADMAP.md) for what's being built
2. Read [CONTRIBUTING.md](./CONTRIBUTING.md) for setup
3. Open an issue or send a PR — we review fast

```bash
# Local dev setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

---

## Trust Signals

- Live on PyPI: [`pip install deepsleep-ai`](https://pypi.org/project/deepsleep-ai/)
- MIT licensed
- GitHub Actions CI on every push
- Tests cover: memory compaction, watcher behavior, offline fallback, chat exit flow
- `ds` console entrypoint — works right after install

---

<div align="center">

**If DeepSleep saved your brain at least once, give it a ⭐**

*Made for developers who actually forget things (all of us)*

</div>