"""Tests for DeepSleep Neural Link — cross-project memory engine."""
from __future__ import annotations

from pathlib import Path

import pytest

from deepsleep_ai.neural_link import NeuralLink, _classify_pattern


# ---------------------------------------------------------------------------
# Pattern classifier
# ---------------------------------------------------------------------------


def test_classify_auth_pattern() -> None:
    assert _classify_pattern("debugging JWT token validation in middleware") == "auth"


def test_classify_bugfix_pattern() -> None:
    assert _classify_pattern("fixed a crash caused by null pointer exception") == "bugfix"


def test_classify_api_pattern() -> None:
    assert _classify_pattern("building a REST API endpoint for user fetch") == "api"


def test_classify_database_pattern() -> None:
    assert _classify_pattern("writing a database migration for new schema") == "database"


def test_classify_general_fallback() -> None:
    # No keywords → general
    result = _classify_pattern("xyz qrs tuv")
    assert result == "general"


# ---------------------------------------------------------------------------
# Registration & listing
# ---------------------------------------------------------------------------


def test_register_project(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    project = tmp_path / "my-project"
    project.mkdir()

    info = nl.register_project(str(project))
    assert info["name"] == "my-project"
    assert info["path"] == str(project.resolve())


def test_register_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    project = tmp_path / "my-project"
    project.mkdir()

    nl.register_project(str(project))
    nl.register_project(str(project))  # should not raise

    projects = nl.list_projects()
    assert len(projects) == 1


def test_list_projects_empty(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)
    assert nl.list_projects() == []


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _make_memory(summary: str, files: list, tasks: list, changes: list) -> dict:
    return {
        "project": {"summary": "Test project summary", "goals": [], "facts": []},
        "session": {
            "summary": summary,
            "recent_files": files,
            "recent_tasks": tasks,
            "last_dream_at": None,
        },
        "ephemeral": {
            "last_user_message": "",
            "last_assistant_message": "",
            "open_questions": [],
            "recent_changes": changes,
        },
        "meta": {"last_model": "deepseek-r1"},
    }


def test_sync_records_patterns(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    project = tmp_path / "backend"
    project.mkdir()

    memory = _make_memory(
        summary="Fixed JWT token validation bug in auth middleware",
        files=["src/auth.py"],
        tasks=["debug jwt token expiry"],
        changes=["modified:src/auth.py"],
    )
    count = nl.sync_project(str(project), memory)
    assert count > 0

    stats = nl.get_stats()
    assert stats["projects"] == 1
    assert stats["snapshots"] == 1
    assert stats["patterns"] >= 1


def test_sync_multiple_times_accumulates_snapshots(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    project = tmp_path / "backend"
    project.mkdir()

    mem1 = _make_memory("Working on auth", [], [], [])
    mem2 = _make_memory("Working on database migrations", [], [], [])

    nl.sync_project(str(project), mem1)
    nl.sync_project(str(project), mem2)

    stats = nl.get_stats()
    assert stats["snapshots"] == 2


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_finds_relevant_pattern(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj_a = tmp_path / "backend-api"
    proj_a.mkdir()
    proj_b = tmp_path / "frontend"
    proj_b.mkdir()

    nl.sync_project(str(proj_a), _make_memory(
        "Fixed JWT auth token validation issue in middleware",
        ["src/auth.py", "src/middleware.py"],
        ["debug jwt refresh token"],
        [],
    ))
    nl.sync_project(str(proj_b), _make_memory(
        "Built React login form with OAuth flow",
        ["components/Login.tsx"],
        ["implement oauth login"],
        [],
    ))

    # Search from a third project — should find results from both
    results = nl.search("jwt token auth", exclude_project=str(tmp_path / "other"))
    assert len(results) > 0
    contents = " ".join(r["content"] for r in results).lower()
    assert "jwt" in contents or "auth" in contents


def test_search_excludes_current_project(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj_a = tmp_path / "backend-api"
    proj_a.mkdir()

    nl.sync_project(str(proj_a), _make_memory(
        "Working on jwt auth in backend-api",
        [], [], [],
    ))

    # Search excluding proj_a — should return nothing since only proj_a has data
    results = nl.search("jwt auth", exclude_project=str(proj_a))
    assert all(r["project_path"] != str(proj_a.resolve()) for r in results)


def test_search_with_pattern_type_filter(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj = tmp_path / "api"
    proj.mkdir()

    nl.sync_project(str(proj), _make_memory(
        "Fixed a database migration crash on deploy",
        [], ["fix migration rollback"], [],
    ))

    results = nl.search("migration", pattern_type="database")
    # All returned results should be database type (or empty — no error)
    for r in results:
        assert r["pattern_type"] == "database"


def test_search_empty_query_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)
    results = nl.search("")
    assert results == []


# ---------------------------------------------------------------------------
# Find similar patterns
# ---------------------------------------------------------------------------


def test_find_similar_patterns(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj_a = tmp_path / "project-a"
    proj_a.mkdir()
    proj_b = tmp_path / "project-b"
    proj_b.mkdir()

    nl.sync_project(str(proj_a), _make_memory(
        "Implemented OAuth2 login with JWT tokens and refresh flow",
        [], [], [],
    ))
    nl.sync_project(str(proj_b), _make_memory(
        "Working on unrelated CSS styling fixes",
        [], [], [],
    ))

    results = nl.find_similar_patterns("auth", exclude_project=str(proj_b))
    assert any(r["project_name"] == "project-a" for r in results)


# ---------------------------------------------------------------------------
# Unregister
# ---------------------------------------------------------------------------


def test_unregister_project(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj = tmp_path / "temp-project"
    proj.mkdir()

    nl.sync_project(str(proj), _make_memory("Some work", [], [], []))
    assert nl.get_stats()["projects"] == 1

    removed = nl.unregister_project(str(proj))
    assert removed is True
    assert nl.get_stats()["projects"] == 0
    assert nl.get_stats()["patterns"] == 0


def test_unregister_nonexistent_returns_false(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)
    assert nl.unregister_project("/does/not/exist") is False


# ---------------------------------------------------------------------------
# Global context
# ---------------------------------------------------------------------------


def test_get_global_context_no_projects(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)
    ctx = nl.get_global_context()
    assert "No other projects linked" in ctx or "Neural Link" in ctx


def test_get_global_context_with_projects(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj_a = tmp_path / "backend"
    proj_a.mkdir()
    proj_current = tmp_path / "frontend"
    proj_current.mkdir()

    nl.sync_project(str(proj_a), _make_memory(
        "Working on the backend API and auth middleware",
        ["src/api.py", "src/auth.py"],
        ["implement api endpoints"],
        [],
    ))

    ctx = nl.get_global_context(current_project=str(proj_current))
    assert "backend" in ctx
    assert "Neural Link" in ctx


def test_get_global_context_with_query(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)

    proj_a = tmp_path / "service"
    proj_a.mkdir()

    nl.sync_project(str(proj_a), _make_memory(
        "Debugging database connection pool exhaustion under load",
        [], [], [],
    ))

    ctx = nl.get_global_context(query="database connection")
    assert "Neural Link" in ctx


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_get_stats_structure(tmp_path: Path) -> None:
    db = tmp_path / "nl.db"
    nl = NeuralLink(db_path=db)
    stats = nl.get_stats()
    assert "projects" in stats
    assert "snapshots" in stats
    assert "patterns" in stats
    assert "db_path" in stats
    assert stats["projects"] == 0
