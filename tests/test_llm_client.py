from deepsleep_ai.llm_client import OllamaClient


def test_fallback_answer_when_ollama_is_offline() -> None:
    client = OllamaClient(host="http://127.0.0.1:9", timeout=1)
    reply = client.answer_question(
        "What was I doing?",
        "Project layer:\n- Summary: Test project\n\nSession layer:\n- Summary: You were refactoring cli.py",
        "",
    )

    assert reply.used_fallback is True
    assert "local memory snapshot" in reply.text


def test_fallback_summary_mentions_changed_files() -> None:
    client = OllamaClient(host="http://127.0.0.1:9", timeout=1)
    reply = client.summarize_activity(
        ["src/deepsleep_ai/cli.py", "README.md"],
        {"README.md": "# Title\nNew heading"},
        "Polishing the package.",
    )

    assert reply.used_fallback is True
    assert "README.md" in reply.text
