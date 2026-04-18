# Changelog

## 0.2.0 - 2026-04-18

### MCP Server
- added official MCP server (`deepsleep-mcp`) — connects DeepSleep memory to Cursor, Claude Desktop, Windsurf, and any MCP-compatible AI IDE
- added `ds mcp` CLI command to start the MCP server in stdio mode
- exposed 9 MCP tools: `get_context`, `get_session_summary`, `get_recent_files`, `get_status`, `get_activity_log`, `get_open_questions`, `get_project_facts`, `record_file_opened`, `add_project_note`
- added `deepsleep://memory/{path}` MCP resource for raw memory access
- added `pip install 'deepsleep-ai[mcp]'` optional extra

### Memory & Context Improvements
- raised memory cap from 2KB to 8KB — preserves 4× more session context without aggressive loss
- increased context window from 3 files / 1,800 chars to 5 files / 4,000 chars per chat query
- raised all compaction limits: session summary (420→1200 chars), project summary (260→800 chars), recent files (8→15), recent tasks (5→10), recent changes (8→15), goals (4→8), facts (5→10)
- switched default compression level from `aggressive` to `conservative`

### Windows Support
- normalized all stored file paths to forward slashes on Windows via `Path.as_posix()`
- fixed SQLite index connection with `check_same_thread=False` for thread-safe watcher operation on Windows

### Developer Experience
- when Ollama is offline, chat now prints install + start instructions on launch instead of silently falling back
- banner now shows `ollama=offline (run: ollama serve)` instead of just `offline`
- fixed unused imports across `cli.py`, `config.py`, and `memory_manager.py`

---

## 0.1.0 - 2026-04-01

- launched `deepsleep-ai` on PyPI with the `ds` CLI
- added `ds init`, `ds chat`, `ds dream`, `ds status`, and `ds doctor`
- implemented a 3-layer memory model with deterministic 2KB compaction
- added Ollama `deepseek-r1` support with offline fallback behavior
- added Watchdog-based idle dreaming and one-shot `ds dream --once`
- added GitHub Actions CI and trusted publishing workflow
