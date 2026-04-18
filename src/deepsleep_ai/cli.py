from __future__ import annotations

import re
import shutil
import html
import base64
from pathlib import Path
from typing import List, Optional

import typer
import structlog
from prompt_toolkit import HTML, PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, PathCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from .llm_client import OllamaClient
from .memory_manager import MemoryManager, SecureMemoryManager, ENC_MAGIC
from .watcher import DreamWatcher
from .config import DeepSleepConfig

logger = structlog.get_logger()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode=None,
    help="DeepSleep: zero-cost local coding memory with idle-time dreaming.",
)


COMMAND_HINTS = ["/help", "/status", "/memory", "/dream", "/quit"]
FILE_TOKEN_PATTERN = re.compile(r"(?P<path>(?:\.{0,2}/)?[\w\-/]+\.[A-Za-z0-9_]+)")
PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
        "brand": "ansigreen bold",
        "toolbar": "ansiblack bg:ansiwhite",
    }
)

SENSITIVE_PATTERNS = {
    r'\.env$', r'\.ssh', r'id_rsa', r'\.aws', r'\.docker', 
    r'secrets?', r'credentials', r'password', r'token'
}


class DeepSleepCompleter(Completer):
    def __init__(self) -> None:
        self.command_completer = WordCompleter(COMMAND_HINTS, ignore_case=True)
        self.path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        stripped = document.text_before_cursor.lstrip()
        completer = self.command_completer if stripped.startswith("/") else self.path_completer
        for completion in completer.get_completions(document, complete_event):
            yield completion


def _bootstrap(project_root: Path, force: bool = False, password: Optional[str] = None) -> MemoryManager:
    config = DeepSleepConfig.load_from_project(project_root)
    memory_path = project_root / ".deepsleep" / "memory.json"
    
    # Encryption Detection
    needs_encryption = config.privacy.encrypt_memory or password is not None
    
    if memory_path.exists():
        try:
            content = memory_path.read_text(encoding="utf-8")
            decoded = base64.b64decode(content[:100]) # Quick check of the start
            if decoded.startswith(ENC_MAGIC.encode()):
                needs_encryption = True
                if not password:
                    # Prompt for password if not provided but file is encrypted
                    password = typer.prompt("Project is AES-256 encrypted. Enter password", hide_input=True)
        except Exception:
            pass
            
    if needs_encryption:
        manager = SecureMemoryManager(project_root, password=password, config=config)
    else:
        manager = MemoryManager(project_root, config=config)
    
    manager.initialize(force=force)
    return manager


def _resolve_safely(project_root: Path, token: str) -> Optional[Path]:
    """Prevent path traversal attacks."""
    try:
        # Normalize and resolve
        candidate = (project_root / token).resolve()
        # Critical: Ensure resolved path is still within project root
        candidate.relative_to(project_root.resolve())
        
        # Check for symlink escape
        if candidate.is_symlink():
            real_path = candidate.resolve()
            real_path.relative_to(project_root.resolve())
            
        if not candidate.exists() or not candidate.is_file():
            return None
            
        if _is_sensitive(candidate):
            logger.warning("sensitive_file_blocked", path=str(candidate))
            return None
            
        return candidate
    except (ValueError, RuntimeError, OSError):  # ValueError from relative_to
        return None


def _is_sensitive(path: Path) -> bool:
    return any(re.search(pattern, str(path), re.I) for pattern in SENSITIVE_PATTERNS)


def _collect_file_context(project_root: Path, question: str, memory_manager: MemoryManager) -> List[str]:
    file_candidates: List[str] = []

    for match in FILE_TOKEN_PATTERN.finditer(question):
        token = match.group("path")
        safe_path = _resolve_safely(project_root, token)
        if safe_path:
            file_candidates.append(str(safe_path.relative_to(project_root)))

    lowered = question.lower()
    if "this file" in lowered or "that file" in lowered:
        memory = memory_manager.load()
        recent_files = memory["session"]["recent_files"]
        for candidate in recent_files[:1]:
            # Still verify existence for recent files in case they were deleted
            if (project_root / candidate).exists():
                file_candidates.append(candidate)

    deduped: List[str] = []
    for file_path in file_candidates:
        if file_path not in deduped:
            deduped.append(file_path)
    return deduped[:5]


def _render_file_context(project_root: Path, relative_paths: List[str]) -> str:
    blocks = []
    for relative_path in relative_paths:
        target = project_root / relative_path
        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        
        # Sanitize for prompt
        sanitized = html.escape(content[:4000])
        blocks.append(f"---BEGIN_FILE: {relative_path}---\n{sanitized}\n---END_FILE---")
    return "\n\n".join(blocks)


OLLAMA_INSTALL_HINT = (
    "Ollama is not running or not installed.\n"
    "  Install : https://ollama.com/download\n"
    "  Start   : ollama serve\n"
    "  Pull    : ollama pull deepseek-r1\n"
    "DeepSleep will answer from saved local memory until Ollama is available."
)


def _print_banner(project_root: Path, client: OllamaClient) -> None:
    availability = "online" if client.is_available() else "offline (run: ollama serve)"
    print_formatted_text(
        HTML(
            "<brand>DeepSleep</brand> "
            f"<prompt>project=</prompt>{project_root.name} "
            f"<prompt>model=</prompt>{client.model} "
            f"<prompt>ollama=</prompt>{availability}"
        ),
        style=PROMPT_STYLE,
    )
    print_formatted_text(
        HTML("<toolbar> /help  /status  /memory  /dream  /quit </toolbar>"),
        style=PROMPT_STYLE,
    )


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(__version__)
        raise typer.Exit()


def _handle_slash_command(
    command: str,
    project_root: Path,
    memory_manager: MemoryManager,
    client: OllamaClient,
) -> str:
    if command == "/quit":
        return "quit"
    if command == "/help":
        typer.echo("Commands: /help, /status, /memory, /dream, /quit")
        typer.echo("Ask natural questions like: What was I doing? or Refactor app/main.py")
        return "handled"
    if command == "/status":
        status = memory_manager.get_status()
        typer.echo(f"project: {status['project_root']}")
        typer.echo(f"memory: {status['memory_path']}")
        typer.echo(f"last dream: {status['last_dream_at'] or 'never'}")
        typer.echo(f"recent files: {', '.join(status['recent_files']) or 'none'}")
        typer.echo(f"model: {status['last_model']}")
        return "handled"
    if command == "/memory":
        typer.echo(memory_manager.build_context())
        return "handled"
    if command == "/dream":
        watcher = DreamWatcher(project_root, memory_manager, client, idle_seconds=300)
        reply = watcher.dream_once_if_idle(force=True)
        if reply is None:
            typer.echo("Nothing new to dream about yet.")
        else:
            typer.echo(reply.text)
        return "handled"
    return "unhandled"


def chat_loop(project_root: Path, model: str, host: str, password: Optional[str] = None) -> None:
    memory_manager = _bootstrap(project_root, password=password)
    client = OllamaClient(model=model, host=host)
    session = PromptSession(
        history=FileHistory(str(memory_manager.chat_history_path)),
        completer=DeepSleepCompleter(),
        complete_while_typing=True,
    )

    _print_banner(project_root, client)
    if not client.is_available():
        typer.echo(OLLAMA_INSTALL_HINT)

    while True:
        try:
            message = session.prompt(HTML("<prompt>ds</prompt> > "), style=PROMPT_STYLE)
        except KeyboardInterrupt:
            continue
        except EOFError:
            typer.echo("DeepSleep ended.")
            break

        message = message.strip()
        if not message:
            continue

        if message.startswith("/"):
            command_state = _handle_slash_command(
                message,
                project_root,
                memory_manager,
                client,
            )
            if command_state == "quit":
                typer.echo("DeepSleep ended.")
                break
            if command_state == "handled":
                continue

        relative_files = _collect_file_context(project_root, message, memory_manager)
        file_context = _render_file_context(project_root, relative_files)
        reply = client.answer_question(message, memory_manager.build_context(), file_context)
        print_formatted_text(HTML(f"<brand>DeepSleep</brand>\n{reply.text}"), style=PROMPT_STYLE)
        memory_manager.record_chat_turn(message, reply.text, relative_files)


@app.callback(invoke_without_command=True)
def default_chat(
    ctx: typer.Context,
    path: Path = typer.Option(Path("."), "--path", help="Project root to watch and chat against."),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password for encrypted memory."),
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed DeepSleep version and exit.",
    ),
) -> None:
    """Start interactive chat when no subcommand is passed."""

    if ctx.invoked_subcommand is None:
        chat_loop(path.resolve(), model, host, password=password)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Project root to initialize."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing memory.json."),
    encrypt: bool = typer.Option(False, "--encrypt", help="Enable AES-256 memory encryption."),
) -> None:
    """Create .deepsleep/ and memory.json in the project folder."""
    password = None
    if encrypt:
        password = typer.prompt("Enter AES-256 encryption password", hide_input=True)
    
    manager = _bootstrap(path.resolve(), force=force, password=password)
    typer.echo(f"Initialized DeepSleep at {manager.memory_path}")
    if encrypt:
        typer.echo("AES-256 GCM Encryption enabled.")


@app.command()
def chat(
    path: Path = typer.Argument(Path("."), help="Project root to chat against."),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password for encrypted memory."),
) -> None:
    """Open the interactive chat UI."""

    chat_loop(path.resolve(), model, host, password=password)


@app.command()
def dream(
    path: Path = typer.Argument(Path("."), help="Project root to watch."),
    idle_seconds: int = typer.Option(
        300,
        "--idle-seconds",
        min=1,
        help="Dream after this many seconds of inactivity.",
    ),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
    once: bool = typer.Option(False, "--once", help="Run one forced dream pass and exit."),
) -> None:
    """Start the idle-time watcher."""

    project_root = path.resolve()
    manager = _bootstrap(project_root)
    watcher = DreamWatcher(project_root, manager, OllamaClient(model=model, host=host), idle_seconds=idle_seconds)

    if once:
        reply = watcher.dream_once_if_idle(force=True)
        if reply is None:
            typer.echo("No pending changes to summarize.")
        else:
            typer.echo(reply.text)
        return

    typer.echo(f"Watching {project_root} for changes. DeepSleep will dream after {idle_seconds} idle seconds.")
    watcher.run_forever()


@app.command()
def status(
    path: Path = typer.Argument(Path("."), help="Project root to inspect."),
) -> None:
    """Show the current layered memory snapshot."""

    manager = _bootstrap(path.resolve())
    status_data = manager.get_status()
    typer.echo(f"project: {status_data['project_root']}")
    typer.echo(f"memory: {status_data['memory_path']}")
    typer.echo(f"activity log: {status_data['activity_log_path']}")
    typer.echo(f"file size: {status_data['file_size']} bytes")
    typer.echo(f"last dream: {status_data['last_dream_at'] or 'never'}")
    typer.echo(f"project summary: {status_data['project_summary']}")
    typer.echo(f"session summary: {status_data['session_summary']}")
    typer.echo(f"recent files: {', '.join(status_data['recent_files']) or 'none'}")
    typer.echo(f"last model: {status_data['last_model']}")


@app.command()
def doctor(
    path: Path = typer.Argument(Path("."), help="Project root to inspect."),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
) -> None:
    """Check local setup before launch or demo."""
    _run_health_checks(path, model, host, format="text", exit_on_fail=False)


@app.command()
def health(
    path: Path = typer.Argument(Path("."), help="Project root to inspect."),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
    format: str = typer.Option("text", "--format", help="text|json"),
) -> None:
    """Comprehensive system health check."""
    _run_health_checks(path, model, host, format=format, exit_on_fail=True)


def _run_health_checks(
    path: Path,
    model: str,
    host: str,
    format: str = "text",
    exit_on_fail: bool = True,
) -> None:
    project_root = path.resolve()
    # Bootstrap might prompt for password
    manager = _bootstrap(project_root)
    client = OllamaClient(model=model, host=host)
    
    available = client.is_available()
    encrypted = isinstance(manager, SecureMemoryManager)
    
    checks = [
        ("project-root", project_root.exists()),
        ("memory-file", manager.memory_path.exists()),
        ("activity-log", manager.activity_log_path.exists()),
        ("prompt-history", manager.chat_history_path.exists()),
        ("ollama-host", available),
        ("ollama-model", client.model_available(model) if available else False),
        ("disk-space", shutil.disk_usage(project_root).free > 1e9),  # 1GB
        ("git-repo", (project_root / ".git").exists()),
        ("aes-256-encryption", encrypted)
    ]
    
    if format == "json":
        import json
        typer.echo(json.dumps(dict(checks), indent=2))
    else:
        for label, ok in checks:
            status = "OK" if ok else "WARN" if not exit_on_fail else "FAIL"
            typer.echo(f"{status:<5} {label}")
            
    if exit_on_fail and not all(ok for _, ok in checks):
        raise typer.Exit(code=1)


def _render_markdown_report(entries: list, project_name: str) -> str:
    from datetime import date
    lines = [
        f"# DeepSleep Standup — {project_name}",
        f"**Date:** {date.today().isoformat()}",
        "",
    ]

    dreams = [e for e in entries if e["type"] == "dream"]
    chats  = [e for e in entries if e["type"] == "chat_turn"]
    files  = [e for e in entries if e["type"] == "file_event"]

    if dreams:
        lines.append("## 🌙 Dream Summaries")
        for d in dreams:
            ts = d["timestamp"][:16]
            summary = d["payload"].get("summary", "")
            lines.append(f"- **{ts}** — {summary}")
        lines.append("")

    if chats:
        lines.append("## 💬 Chat Activity")
        for c in chats:
            ts = c["timestamp"][:16]
            user_msg = c["payload"].get("user", "")[:120]
            lines.append(f"- **{ts}** — {user_msg}")
        lines.append("")

    touched = list({e["payload"]["path"] for e in files})
    if touched:
        lines.append("## 📂 Files Touched")
        for f in touched:
            lines.append(f"- `{f}`")
        lines.append("")

    if not dreams and not chats and not touched:
        lines.append("_No activity recorded._")

    return "\n".join(lines)


@app.command()
def forget(
    path: Path = typer.Argument(Path("."), help="Project root."),
    layer: Optional[str] = typer.Option(None, "--layer", help="Layer to wipe: project, session, or ephemeral."),
    key: Optional[str] = typer.Option(None, "--key", help="Specific field to wipe, e.g. session.recent_files"),
    all: bool = typer.Option(False, "--all", help="Full memory reset."),
) -> None:
    """Selectively wipe parts of DeepSleep memory."""
    manager = _bootstrap(path.resolve())

    if all:
        confirm = typer.confirm("This will wipe ALL memory. Are you sure?")
        if not confirm:
            typer.echo("Aborted.")
            return
        manager.initialize(force=True)
        typer.echo("Memory fully reset.")
        return

    if key:
        parts = key.split(".", 1)
        if len(parts) != 2:
            typer.echo("--key must be in format layer.field, e.g. session.recent_files")
            raise typer.Exit(1)
        manager.forget_key(parts[0], parts[1])
        typer.echo(f"Cleared: {key}")
        return

    if layer:
        confirm = typer.confirm(f"Wipe the '{layer}' layer?")
        if not confirm:
            typer.echo("Aborted.")
            return
        manager.forget_layer(layer)
        typer.echo(f"Layer '{layer}' reset to defaults.")
        return

    typer.echo("What do you want to forget?")
    typer.echo("  1) session   (recent files, tasks, dream summary)")
    typer.echo("  2) ephemeral (last chat, open questions, recent changes)")
    typer.echo("  3) project   (goals, facts, project summary)")
    typer.echo("  4) everything")
    choice = typer.prompt("Choice [1-4]")
    layer_map = {"1": "session", "2": "ephemeral", "3": "project"}
    if choice == "4":
        manager.initialize(force=True)
        typer.echo("Memory fully reset.")
    elif choice in layer_map:
        manager.forget_layer(layer_map[choice])
        typer.echo(f"Layer '{layer_map[choice]}' cleared.")
    else:
        typer.echo("Invalid choice.")


@app.command()
def export(
    path: Path = typer.Argument(Path("."), help="Project root."),
    since: Optional[str] = typer.Option(None, "--since", help="Only include entries from this ISO date onward, e.g. 2025-01-01."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write output to this file instead of stdout."),
    format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Export the activity log and memory as a standup report."""
    import json as json_module

    manager = _bootstrap(path.resolve())
    entries = manager.export_activity(since=since)

    if not entries:
        typer.echo("No activity found for the given filters.")
        return

    if format == "json":
        output = json_module.dumps(entries, indent=2, ensure_ascii=False)
    else:
        output = _render_markdown_report(entries, path.resolve().name)

    if out:
        out.write_text(output, encoding="utf-8")
        typer.echo(f"Report saved to {out}")
    else:
        typer.echo(output)


@app.command()
def mcp(
    path: Path = typer.Argument(Path("."), help="Project root to serve memory for."),
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio (default)."),
) -> None:
    """Start the DeepSleep MCP server for Cursor, Claude Desktop, Windsurf, and other AI IDEs.

    Add to your IDE's MCP config:

      {
        "mcpServers": {
          "deepsleep": {
            "command": "deepsleep-mcp",
            "args": ["--path", "/absolute/path/to/your/project"]
          }
        }
      }
    """
    try:
        from .mcp_server import mcp_app, _get_manager
    except ImportError:
        typer.echo(
            "The MCP server requires the 'mcp' package.\n"
            "Install it with: pip install 'deepsleep-ai[mcp]'",
            err=True,
        )
        raise typer.Exit(1)

    project_root = path.resolve()
    try:
        _get_manager(str(project_root))
        typer.echo(f"DeepSleep MCP server starting for {project_root} (transport={transport})", err=True)
    except Exception as exc:
        typer.echo(f"Warning: could not pre-warm memory: {exc}", err=True)

    mcp_app.run(transport=transport)


@app.command()
def link(
    path: Path = typer.Argument(Path("."), help="Project root to link into the Neural Link."),
    sync: bool = typer.Option(True, "--sync/--no-sync", help="Immediately sync current memory after linking."),
) -> None:
    """Register this project in DeepSleep's Neural Link (cross-project memory).

    After linking, DeepSleep can surface patterns from this project when you're
    working in other projects:

      "You solved this auth bug in backend-api two weeks ago."
    """
    from .neural_link import NeuralLink

    project_root = path.resolve()
    nl = NeuralLink()
    info = nl.register_project(str(project_root))
    typer.echo(f"Linked: {info['name']} ({project_root})")

    if sync:
        manager = _bootstrap(project_root)
        memory = manager.load()
        count = nl.sync_project(str(project_root), memory)
        typer.echo(f"Synced {count} pattern(s) into Neural Link.")

    stats = nl.get_stats()
    typer.echo(f"Neural Link now tracks {stats['projects']} project(s), {stats['patterns']} pattern(s).")


@app.command()
def unlink(
    path: Path = typer.Argument(Path("."), help="Project root to remove from Neural Link."),
) -> None:
    """Remove this project from the Neural Link index."""
    from .neural_link import NeuralLink

    project_root = path.resolve()
    nl = NeuralLink()
    removed = nl.unregister_project(str(project_root))
    if removed:
        typer.echo(f"Unlinked: {project_root.name}")
    else:
        typer.echo(f"{project_root.name} was not in the Neural Link.")


@app.command()
def search(
    query: str = typer.Argument(..., help="What to search for across all linked projects."),
    path: Path = typer.Option(Path("."), "--path", help="Current project root (excluded from results)."),
    pattern_type: Optional[str] = typer.Option(
        None, "--type", help="Filter by type: auth, bugfix, api, database, refactor, performance, test"
    ),
    limit: int = typer.Option(8, "--limit", help="Max results to return."),
    format: str = typer.Option("text", "--format", help="text|json"),
) -> None:
    """Search your entire coding history across all linked projects.

    Examples:

      ds search "jwt token validation"
      ds search "database migration" --type bugfix
      ds search "auth middleware" --format json
    """
    import json as _json
    from .neural_link import NeuralLink

    nl = NeuralLink()
    results = nl.search(
        query,
        limit=limit,
        exclude_project=str(path.resolve()),
        pattern_type=pattern_type,
    )

    if not results:
        typer.echo(f"No cross-project matches for '{query}'.")
        typer.echo("Tip: run `ds link` in your other projects to build the Neural Link index.")
        return

    if format == "json":
        typer.echo(_json.dumps(results, indent=2, ensure_ascii=False))
        return

    typer.echo(f"\nNeural Link — {len(results)} result(s) for '{query}'\n")
    for r in results:
        ts = r["recorded_at"][:10]
        src = f"  {r['source_file']}" if r["source_file"] else ""
        typer.echo(f"  [{r['pattern_type'].upper()}] {r['project_name']} · {ts}{src}")
        typer.echo(f"  {r['content'][:200]}")
        typer.echo("")


@app.command()
def neural(
    path: Path = typer.Argument(Path("."), help="Current project root."),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Optional search query."),
) -> None:
    """Show the global Neural Link context — patterns from all linked projects.

    Use --query to filter relevant results for your current task.
    """
    from .neural_link import NeuralLink

    nl = NeuralLink()
    stats = nl.get_stats()
    if stats["projects"] == 0:
        typer.echo("Neural Link is empty. Run `ds link` in your projects to get started.")
        return

    context = nl.get_global_context(
        current_project=str(path.resolve()),
        query=query,
    )
    typer.echo(context)
    typer.echo(f"\n[{stats['projects']} projects · {stats['patterns']} patterns · {stats['db_path']}]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
