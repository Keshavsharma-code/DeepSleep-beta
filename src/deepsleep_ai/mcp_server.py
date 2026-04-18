"""DeepSleep MCP Server.

Exposes DeepSleep's memory to any MCP-compatible AI IDE:
Cursor, Claude Desktop, Windsurf, VS Code Copilot, and others.

Usage (stdio, recommended for IDEs):
    deepsleep-mcp --path /your/project

Config for Claude Desktop / Cursor (~/.claude/config.json or cursor settings):
    {
      "mcpServers": {
        "deepsleep": {
          "command": "deepsleep-mcp",
          "args": ["--path", "/absolute/path/to/your/project"]
        }
      }
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Graceful import guard — mcp is an optional extra
# ---------------------------------------------------------------------------
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    print(
        "[DeepSleep MCP] The 'mcp' package is not installed.\n"
        "Run: pip install 'deepsleep-ai[mcp]'\n"
        "or:  pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)

from .memory_manager import MemoryManager, SecureMemoryManager
from .config import DeepSleepConfig

# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

mcp_app = FastMCP(
    "deepsleep",
    instructions=(
        "DeepSleep stores a developer's local coding session memory: "
        "what files were open, what tasks were in progress, the last AI-generated "
        "dream summary, open questions, and recent file changes. "
        "Call get_context first to orient yourself before answering anything "
        "about the developer's current work."
    ),
)

# Module-level manager cache keyed by resolved project path.
# This avoids re-loading memory on every tool call.
_managers: Dict[str, MemoryManager] = {}


def _get_manager(project_path: str = ".") -> MemoryManager:
    resolved = str(Path(project_path).resolve())
    if resolved not in _managers:
        config = DeepSleepConfig.load_from_project(Path(resolved))
        manager = MemoryManager(Path(resolved), config=config)
        # Initialize silently if not yet set up — MCP clients may call this
        # before the developer has run `ds init`.
        if not manager.memory_path.exists():
            manager.initialize()
        _managers[resolved] = manager
    return _managers[resolved]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp_app.tool()
def get_context(project_path: str = ".") -> str:
    """Return the full DeepSleep memory context for a project.

    This is the primary tool — call it to understand what the developer was
    working on, which files were active, what tasks were in flight, and the
    most recent AI-generated session summary.

    Args:
        project_path: Absolute or relative path to the project root.
                      Defaults to the current working directory.

    Returns:
        A formatted multi-line string with all three memory layers.
    """
    try:
        manager = _get_manager(project_path)
        return manager.build_context()
    except Exception as exc:
        logger.error("mcp_get_context_failed", error=str(exc))
        return f"[DeepSleep] Could not load memory: {exc}"


@mcp_app.tool()
def get_session_summary(project_path: str = ".") -> str:
    """Return only the AI-generated session dream summary.

    Shorter than get_context — useful when you just need a quick recap
    without the full memory dump.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        A paragraph summarising the last recorded working session.
    """
    try:
        manager = _get_manager(project_path)
        memory = manager.load()
        summary = memory["session"]["summary"]
        last_dream = memory["session"].get("last_dream_at") or "never"
        return f"Last dream: {last_dream}\n\nSummary: {summary}"
    except Exception as exc:
        return f"[DeepSleep] Could not load summary: {exc}"


@mcp_app.tool()
def get_recent_files(project_path: str = ".") -> List[str]:
    """Return the list of recently modified files tracked by DeepSleep.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        A list of relative file paths, most recent last.
    """
    try:
        manager = _get_manager(project_path)
        memory = manager.load()
        return memory["session"]["recent_files"]
    except Exception as exc:
        logger.error("mcp_get_recent_files_failed", error=str(exc))
        return []


@mcp_app.tool()
def get_status(project_path: str = ".") -> Dict[str, Any]:
    """Return DeepSleep's current status for a project.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        A dict with keys: project_root, memory_path, file_size,
        project_summary, session_summary, recent_files, last_dream_at,
        last_model.
    """
    try:
        manager = _get_manager(project_path)
        return manager.get_status()
    except Exception as exc:
        logger.error("mcp_get_status_failed", error=str(exc))
        return {"error": str(exc)}


@mcp_app.tool()
def get_activity_log(
    project_path: str = ".",
    since: Optional[str] = None,
    limit: int = 30,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent entries from the activity log.

    Args:
        project_path: Absolute or relative path to the project root.
        since: Optional ISO timestamp — only return entries after this time,
               e.g. "2026-04-15T00:00:00".
        limit: Maximum number of entries to return (default 30).
        event_type: Filter by type: "dream", "chat_turn", or "file_event".

    Returns:
        A list of activity log dicts, each with keys: timestamp, type, payload.
    """
    try:
        manager = _get_manager(project_path)
        entries = manager.export_activity(since=since)
        if event_type:
            entries = [e for e in entries if e.get("type") == event_type]
        return entries[-limit:]
    except Exception as exc:
        logger.error("mcp_get_activity_failed", error=str(exc))
        return []


@mcp_app.tool()
def get_open_questions(project_path: str = ".") -> List[str]:
    """Return open/unresolved questions from the current session.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        A list of open question strings.
    """
    try:
        manager = _get_manager(project_path)
        memory = manager.load()
        return memory["ephemeral"].get("open_questions", [])
    except Exception as exc:
        return []


@mcp_app.tool()
def get_project_facts(project_path: str = ".") -> Dict[str, Any]:
    """Return the long-term project layer: summary, goals, and facts.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        A dict with keys: summary, goals, facts.
    """
    try:
        manager = _get_manager(project_path)
        memory = manager.load()
        return {
            "summary": memory["project"]["summary"],
            "goals": memory["project"]["goals"],
            "facts": memory["project"]["facts"],
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp_app.tool()
def record_file_opened(
    file_path: str,
    project_path: str = ".",
) -> str:
    """Tell DeepSleep that a file was opened in the IDE.

    Use this to keep DeepSleep's recent-files list in sync when the
    developer opens files directly in the IDE (outside of the terminal).

    Args:
        file_path: Path to the file that was opened (relative or absolute).
        project_path: Absolute or relative path to the project root.

    Returns:
        A confirmation message.
    """
    try:
        manager = _get_manager(project_path)
        # Normalise to relative
        try:
            rel = str(Path(file_path).resolve().relative_to(Path(project_path).resolve()))
        except ValueError:
            rel = file_path
        manager.record_file_event(rel, "opened")
        return f"Recorded: {rel}"
    except Exception as exc:
        return f"[DeepSleep] Could not record file event: {exc}"


@mcp_app.tool()
def add_project_note(note: str, project_path: str = ".") -> str:
    """Add a factual note to the long-term project memory.

    Great for recording decisions, constraints, or anything the AI should
    remember across sessions.

    Args:
        note: The note to store (keep it concise, ≤ 160 characters).
        project_path: Absolute or relative path to the project root.

    Returns:
        A confirmation message.
    """
    try:
        manager = _get_manager(project_path)
        manager.record_project_note(note)
        return f"Noted: {note[:80]}{'...' if len(note) > 80 else ''}"
    except Exception as exc:
        return f"[DeepSleep] Could not save note: {exc}"


# ---------------------------------------------------------------------------
# Neural Link MCP tools — cross-project memory
# ---------------------------------------------------------------------------


@mcp_app.tool()
def cross_project_search(
    query: str,
    project_path: str = ".",
    limit: int = 8,
    pattern_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search your entire coding history across ALL linked DeepSleep projects.

    This is the Neural Link — it surfaces patterns, solutions, and context from
    every project on your machine.

    Example questions it can answer:
    - "Did I solve this auth bug before?" → cross_project_search("jwt token validation")
    - "How did I handle database migrations?" → cross_project_search("migration rollback", pattern_type="database")
    - "What auth patterns have I used?" → cross_project_search("auth middleware", pattern_type="auth")

    Args:
        query: Natural language search query.
        project_path: Current project path (excluded from results so you only get cross-project hits).
        limit: Maximum number of results (default 8).
        pattern_type: Optional filter — auth, bugfix, api, database, refactor, performance, test.

    Returns:
        List of matching patterns with project_name, content, pattern_type, source_file, recorded_at.
    """
    try:
        from .neural_link import NeuralLink
        nl = NeuralLink()
        return nl.search(
            query,
            limit=limit,
            exclude_project=project_path,
            pattern_type=pattern_type,
        )
    except Exception as exc:
        logger.error("mcp_cross_project_search_failed", error=str(exc))
        return []


@mcp_app.tool()
def get_neural_context(
    project_path: str = ".",
    query: Optional[str] = None,
) -> str:
    """Get full cross-project context from all linked DeepSleep projects.

    Call this alongside get_context to give the AI a machine-wide view of
    the developer's coding patterns, not just the current project.

    Args:
        project_path: Current project root (excluded from results).
        query: Optional query to filter relevant cross-project patterns.

    Returns:
        A formatted context string covering all linked projects.
    """
    try:
        from .neural_link import NeuralLink
        nl = NeuralLink()
        return nl.get_global_context(current_project=project_path, query=query)
    except Exception as exc:
        return f"[Neural Link] Unavailable: {exc}"


@mcp_app.tool()
def get_similar_patterns(
    pattern_type: str,
    project_path: str = ".",
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Find recent patterns of a specific type from other linked projects.

    Great for when the AI recognises what kind of problem the developer is
    solving and wants to surface prior solutions automatically.

    Args:
        pattern_type: One of: auth, bugfix, api, database, refactor, performance, test, general.
        project_path: Current project (excluded from results).
        limit: Max results.

    Returns:
        List of matching patterns with project context.
    """
    try:
        from .neural_link import NeuralLink
        nl = NeuralLink()
        return nl.find_similar_patterns(
            pattern_type=pattern_type,
            exclude_project=project_path,
            limit=limit,
        )
    except Exception as exc:
        logger.error("mcp_similar_patterns_failed", error=str(exc))
        return []


@mcp_app.tool()
def get_neural_link_stats() -> Dict[str, Any]:
    """Return Neural Link index statistics — how many projects, snapshots, and patterns are indexed.

    Returns:
        Dict with projects, snapshots, patterns counts and db_path.
    """
    try:
        from .neural_link import NeuralLink
        nl = NeuralLink()
        return nl.get_stats()
    except Exception as exc:
        return {"error": str(exc)}


@mcp_app.tool()
def sync_to_neural_link(project_path: str = ".") -> str:
    """Push the current project's memory into the global Neural Link index.

    Call this after a dream cycle or when you want to make the current
    session available to cross-project searches.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        Confirmation with number of patterns indexed.
    """
    try:
        from .neural_link import NeuralLink
        manager = _get_manager(project_path)
        memory = manager.load()
        nl = NeuralLink()
        count = nl.sync_project(project_path, memory)
        stats = nl.get_stats()
        return f"Synced {count} pattern(s) from {Path(project_path).resolve().name}. Neural Link total: {stats['patterns']} patterns across {stats['projects']} projects."
    except Exception as exc:
        return f"[Neural Link] Sync failed: {exc}"


# ---------------------------------------------------------------------------
# Resources — expose memory as readable MCP resources
# ---------------------------------------------------------------------------


@mcp_app.resource("deepsleep://memory/{project_path}")
def memory_resource(project_path: str) -> str:
    """Full raw memory.json as a readable MCP resource."""
    try:
        decoded_path = project_path.replace("|", "/")
        manager = _get_manager(decoded_path)
        memory = manager.load()
        return json.dumps(memory, indent=2, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(path: str = ".") -> None:
    """Start the DeepSleep MCP server in stdio mode."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="deepsleep-mcp",
        description="DeepSleep MCP server — exposes coding session memory to AI IDEs.",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Project root to serve memory for (default: current directory).",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio"],
        help="Transport mode (only stdio is supported currently).",
    )
    args = parser.parse_args()

    # Pre-warm the manager so the first tool call is fast.
    try:
        _get_manager(args.path)
        logger.info("mcp_server_ready", path=args.path)
    except Exception as exc:
        logger.warning("mcp_server_prewarm_failed", error=str(exc))

    mcp_app.run(transport=args.transport)


if __name__ == "__main__":
    main()
