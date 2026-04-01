from __future__ import annotations

import re
from pathlib import Path
from typing import List

import typer
from prompt_toolkit import HTML, PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, Completion, PathCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from .llm_client import OllamaClient
from .memory_manager import MemoryManager
from .watcher import DreamWatcher

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


class DeepSleepCompleter(Completer):
    def __init__(self) -> None:
        self.command_completer = WordCompleter(COMMAND_HINTS, ignore_case=True)
        self.path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        stripped = document.text_before_cursor.lstrip()
        completer = self.command_completer if stripped.startswith("/") else self.path_completer
        for completion in completer.get_completions(document, complete_event):
            yield completion


def _bootstrap(project_root: Path, force: bool = False) -> MemoryManager:
    manager = MemoryManager(project_root)
    manager.initialize(force=force)
    return manager


def _collect_file_context(project_root: Path, question: str, memory_manager: MemoryManager) -> List[str]:
    file_candidates: List[str] = []

    for match in FILE_TOKEN_PATTERN.finditer(question):
        token = match.group("path")
        candidate = (project_root / token).resolve()
        if candidate.exists() and candidate.is_file():
            file_candidates.append(str(candidate.relative_to(project_root)))

    lowered = question.lower()
    if "this file" in lowered or "that file" in lowered:
        recent_files = memory_manager.load()["session"]["recent_files"]
        for candidate in recent_files[:1]:
            file_candidates.append(candidate)

    deduped: List[str] = []
    for file_path in file_candidates:
        if file_path not in deduped:
            deduped.append(file_path)
    return deduped[:3]


def _render_file_context(project_root: Path, relative_paths: List[str]) -> str:
    blocks = []
    for relative_path in relative_paths:
        target = project_root / relative_path
        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        blocks.append(f"[{relative_path}]\n{content[:1800]}")
    return "\n\n".join(blocks)


def _print_banner(project_root: Path, client: OllamaClient) -> None:
    availability = "online" if client.is_available() else "offline"
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


def chat_loop(project_root: Path, model: str, host: str) -> None:
    memory_manager = _bootstrap(project_root)
    client = OllamaClient(model=model, host=host)
    session = PromptSession(
        history=FileHistory(str(memory_manager.chat_history_path)),
        completer=DeepSleepCompleter(),
        complete_while_typing=True,
    )

    _print_banner(project_root, client)

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
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed DeepSleep version and exit.",
    ),
) -> None:
    """Start interactive chat when no subcommand is passed."""

    _ = version

    if ctx.invoked_subcommand is None:
        chat_loop(path.resolve(), model, host)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Project root to initialize."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing memory.json."),
) -> None:
    """Create .deepsleep/ and memory.json in the project folder."""

    manager = _bootstrap(path.resolve(), force=force)
    typer.echo(f"Initialized DeepSleep at {manager.memory_path}")


@app.command()
def chat(
    path: Path = typer.Argument(Path("."), help="Project root to chat against."),
    model: str = typer.Option("deepseek-r1", "--model", help="Ollama model name."),
    host: str = typer.Option("http://127.0.0.1:11434", "--host", help="Ollama host."),
) -> None:
    """Open the interactive chat UI."""

    chat_loop(path.resolve(), model, host)


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

    project_root = path.resolve()
    manager = _bootstrap(project_root)
    client = OllamaClient(model=model, host=host, timeout=5)
    memory_path = manager.memory_path
    available = client.is_available()
    model_ready = client.model_available(model) if available else False
    status_data = manager.get_status()

    checks = [
        ("project-root", project_root.exists(), str(project_root)),
        ("memory-file", memory_path.exists(), str(memory_path)),
        ("activity-log", manager.activity_log_path.exists(), str(manager.activity_log_path)),
        ("prompt-history", manager.chat_history_path.exists(), str(manager.chat_history_path)),
        ("ollama-host", available, host),
        ("ollama-model", model_ready, model if available else "Ollama offline"),
    ]

    for label, ok, detail in checks:
        prefix = "OK" if ok else "WARN"
        typer.echo(f"{prefix:<4} {label:<14} {detail}")

    typer.echo(f"INFO recent-files    {', '.join(status_data['recent_files']) or 'none'}")
    typer.echo(f"INFO session-summary {status_data['session_summary']}")
    if not available:
        typer.echo("TIP  Start Ollama with: ollama serve")
    elif not model_ready:
        typer.echo(f"TIP  Pull the model with: ollama pull {model}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
