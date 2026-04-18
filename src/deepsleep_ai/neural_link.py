"""DeepSleep Neural Link — Cross-Project Memory.

Maintains a global SQLite index at ~/.deepsleep/neural_link.db that aggregates
session summaries, file patterns, and task history from every DeepSleep-enabled
project on the machine.

Usage:
    from deepsleep_ai.neural_link import NeuralLink

    nl = NeuralLink()
    nl.register_project("/path/to/my-project")
    nl.sync_project("/path/to/my-project", memory_dict)

    results = nl.search("jwt auth token validation")
    similar = nl.find_similar_patterns("auth", exclude_project="/current/project")
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Global index location
# ---------------------------------------------------------------------------

NEURAL_LINK_DIR = Path.home() / ".deepsleep"
NEURAL_LINK_DB = NEURAL_LINK_DIR / "neural_link.db"

# ---------------------------------------------------------------------------
# Pattern classifiers — keyword-based, no ML required
# ---------------------------------------------------------------------------

PATTERN_KEYWORDS: Dict[str, List[str]] = {
    "auth": [
        "auth", "jwt", "token", "login", "logout", "session", "oauth",
        "password", "credential", "bearer", "refresh", "middleware", "cookie",
    ],
    "bugfix": [
        "fix", "bug", "error", "exception", "crash", "issue", "broken",
        "incorrect", "wrong", "fail", "null", "none", "undefined", "traceback",
    ],
    "api": [
        "api", "endpoint", "route", "request", "response", "rest", "graphql",
        "webhook", "fetch", "http", "post", "get", "put", "delete", "patch",
    ],
    "database": [
        "database", "migration", "query", "schema", "model", "sql", "orm",
        "table", "index", "foreign", "transaction", "prisma", "sequelize",
    ],
    "refactor": [
        "refactor", "cleanup", "restructure", "rename", "extract", "simplify",
        "reorganize", "move", "split", "merge", "abstract",
    ],
    "performance": [
        "performance", "slow", "optimize", "cache", "memory", "latency",
        "bottleneck", "profil", "benchmark", "speed", "efficient",
    ],
    "test": [
        "test", "spec", "assert", "mock", "stub", "fixture", "coverage",
        "unit", "integration", "e2e", "pytest", "jest",
    ],
}


def _classify_pattern(text: str) -> str:
    """Return the best-matching pattern type for a block of text."""
    lowered = text.lower()
    scores: Dict[str, int] = {}
    for pattern_type, keywords in PATTERN_KEYWORDS.items():
        scores[pattern_type] = sum(1 for kw in keywords if kw in lowered)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "general"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# NeuralLink
# ---------------------------------------------------------------------------


class NeuralLink:
    """Cross-project memory index — persists to ~/.deepsleep/neural_link.db."""

    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or NEURAL_LINK_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT    UNIQUE NOT NULL,
                name        TEXT    NOT NULL,
                registered_at TEXT  NOT NULL,
                last_synced TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      INTEGER NOT NULL REFERENCES projects(id),
                synced_at       TEXT    NOT NULL,
                session_summary TEXT,
                recent_files    TEXT,   -- JSON array
                recent_tasks    TEXT,   -- JSON array
                project_summary TEXT
            );

            CREATE TABLE IF NOT EXISTS patterns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id   INTEGER NOT NULL REFERENCES projects(id),
                snapshot_id  INTEGER REFERENCES snapshots(id),
                pattern_type TEXT    NOT NULL,
                content      TEXT    NOT NULL,
                source_file  TEXT,
                recorded_at  TEXT    NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS patterns_fts USING fts5(
                content,
                pattern_type,
                source_file,
                content='patterns',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS patterns_ai AFTER INSERT ON patterns BEGIN
                INSERT INTO patterns_fts(rowid, content, pattern_type, source_file)
                VALUES (new.id, new.content, new.pattern_type, new.source_file);
            END;

            CREATE TRIGGER IF NOT EXISTS patterns_ad AFTER DELETE ON patterns BEGIN
                INSERT INTO patterns_fts(patterns_fts, rowid, content, pattern_type, source_file)
                VALUES ('delete', old.id, old.content, old.pattern_type, old.source_file);
            END;

            CREATE INDEX IF NOT EXISTS idx_snapshots_project ON snapshots(project_id);
            CREATE INDEX IF NOT EXISTS idx_patterns_project ON patterns(project_id);
            CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(pattern_type);
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Project registration
    # ------------------------------------------------------------------

    def _register_project_locked(self, conn: sqlite3.Connection, resolved: str) -> None:
        """Insert project row — caller must already hold self._lock."""
        name = Path(resolved).name
        conn.execute(
            """
            INSERT INTO projects (path, name, registered_at)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO NOTHING
            """,
            (resolved, name, _utc_now()),
        )

    def register_project(self, project_path: str) -> Dict[str, Any]:
        """Register a project in the neural link. Idempotent."""
        resolved = str(Path(project_path).resolve())
        name = Path(resolved).name
        conn = self._connect()
        with self._lock:
            self._register_project_locked(conn, resolved)
            conn.commit()
        project = conn.execute(
            "SELECT * FROM projects WHERE path = ?", (resolved,)
        ).fetchone()
        logger.info("neural_link_registered", project=name, path=resolved)
        return dict(project)

    def unregister_project(self, project_path: str) -> bool:
        """Remove a project and all its data from the neural link."""
        resolved = str(Path(project_path).resolve())
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT id FROM projects WHERE path = ?", (resolved,)
            ).fetchone()
            if not row:
                return False
            project_id = row["id"]
            # Rebuild FTS index after deleting patterns (safest approach with content tables)
            conn.execute("DELETE FROM patterns WHERE project_id = ?", (project_id,))
            # Rebuild the FTS shadow tables to remove orphaned entries
            conn.execute("INSERT INTO patterns_fts(patterns_fts) VALUES ('rebuild')")
            conn.execute("DELETE FROM snapshots WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        logger.info("neural_link_unregistered", path=resolved)
        return True

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return all registered projects."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_synced DESC NULLS LAST"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Syncing memory → global index
    # ------------------------------------------------------------------

    def sync_project(self, project_path: str, memory: Dict[str, Any]) -> int:
        """Push a project's current memory snapshot into the global index.

        Returns the number of new patterns recorded.
        """
        resolved = str(Path(project_path).resolve())
        conn = self._connect()

        with self._lock:
            # Ensure project is registered (lock-free internal version — we already hold the lock)
            self._register_project_locked(conn, resolved)
            row = conn.execute(
                "SELECT id FROM projects WHERE path = ?", (resolved,)
            ).fetchone()
            project_id = row["id"]

            session = memory.get("session", {})
            project = memory.get("project", {})

            recent_files = json.dumps(session.get("recent_files", []))
            recent_tasks = json.dumps(session.get("recent_tasks", []))

            conn.execute(
                """
                INSERT INTO snapshots
                    (project_id, synced_at, session_summary, recent_files, recent_tasks, project_summary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    _utc_now(),
                    session.get("summary", ""),
                    recent_files,
                    recent_tasks,
                    project.get("summary", ""),
                ),
            )
            snapshot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Extract patterns from session summary + tasks
            patterns_added = 0
            texts_to_index = [
                (session.get("summary", ""), None),
                (project.get("summary", ""), None),
            ]
            for task in session.get("recent_tasks", []):
                texts_to_index.append((task, None))
            for change in memory.get("ephemeral", {}).get("recent_changes", []):
                # changes are like "modified:src/auth/middleware.py"
                parts = change.split(":", 1)
                file_path = parts[1] if len(parts) == 2 else change
                texts_to_index.append((change, file_path))

            for text, source_file in texts_to_index:
                if not text or len(text.strip()) < 10:
                    continue
                pattern_type = _classify_pattern(text)
                conn.execute(
                    """
                    INSERT INTO patterns (project_id, snapshot_id, pattern_type, content, source_file, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, snapshot_id, pattern_type, text[:600], source_file, _utc_now()),
                )
                patterns_added += 1

            conn.execute(
                "UPDATE projects SET last_synced = ? WHERE id = ?",
                (_utc_now(), project_id),
            )
            conn.commit()

        logger.info("neural_link_synced", project=Path(resolved).name, patterns=patterns_added)
        return patterns_added

    # ------------------------------------------------------------------
    # Search & retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 8,
        exclude_project: Optional[str] = None,
        pattern_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Full-text search across all project patterns.

        Returns ranked results with project name, pattern type, content,
        source file, and when it was recorded.
        """
        conn = self._connect()
        exclude_path = str(Path(exclude_project).resolve()) if exclude_project else None

        # Escape FTS special chars
        safe_query = re.sub(r'[^\w\s]', ' ', query).strip()
        if not safe_query:
            return []

        try:
            if pattern_type:
                rows = conn.execute(
                    """
                    SELECT p.content, p.pattern_type, p.source_file, p.recorded_at,
                           pr.name AS project_name, pr.path AS project_path,
                           bm25(patterns_fts) AS rank
                    FROM patterns_fts
                    JOIN patterns p ON patterns_fts.rowid = p.id
                    JOIN projects pr ON p.project_id = pr.id
                    WHERE patterns_fts MATCH ? AND p.pattern_type = ?
                      AND (? IS NULL OR pr.path != ?)
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (safe_query, pattern_type, exclude_path, exclude_path, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT p.content, p.pattern_type, p.source_file, p.recorded_at,
                           pr.name AS project_name, pr.path AS project_path,
                           bm25(patterns_fts) AS rank
                    FROM patterns_fts
                    JOIN patterns p ON patterns_fts.rowid = p.id
                    JOIN projects pr ON p.project_id = pr.id
                    WHERE patterns_fts MATCH ?
                      AND (? IS NULL OR pr.path != ?)
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (safe_query, exclude_path, exclude_path, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            # FTS query syntax error — fall back to LIKE
            rows = conn.execute(
                """
                SELECT p.content, p.pattern_type, p.source_file, p.recorded_at,
                       pr.name AS project_name, pr.path AS project_path,
                       0 AS rank
                FROM patterns p
                JOIN projects pr ON p.project_id = pr.id
                WHERE p.content LIKE ?
                  AND (? IS NULL OR pr.path != ?)
                ORDER BY p.recorded_at DESC
                LIMIT ?
                """,
                (f"%{query}%", exclude_path, exclude_path, limit),
            ).fetchall()

        return [dict(r) for r in rows]

    def find_similar_patterns(
        self,
        pattern_type: str,
        exclude_project: Optional[str] = None,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """Find recent patterns of a given type from other projects."""
        conn = self._connect()
        exclude_path = str(Path(exclude_project).resolve()) if exclude_project else None

        rows = conn.execute(
            """
            SELECT p.content, p.pattern_type, p.source_file, p.recorded_at,
                   pr.name AS project_name, pr.path AS project_path
            FROM patterns p
            JOIN projects pr ON p.project_id = pr.id
            WHERE p.pattern_type = ?
              AND (? IS NULL OR pr.path != ?)
            ORDER BY p.recorded_at DESC
            LIMIT ?
            """,
            (pattern_type, exclude_path, exclude_path, limit),
        ).fetchall()

        return [dict(r) for r in rows]

    def get_global_context(
        self,
        current_project: Optional[str] = None,
        query: Optional[str] = None,
    ) -> str:
        """Build a rich cross-project context string for LLM injection.

        If query is given, search results are prioritised. Otherwise recent
        snapshots from all other projects are returned.
        """
        lines: List[str] = ["=== DeepSleep Neural Link — Cross-Project Memory ===\n"]

        projects = self.list_projects()
        current_path = str(Path(current_project).resolve()) if current_project else None

        other_projects = [p for p in projects if p["path"] != current_path]
        if not other_projects:
            return "[Neural Link] No other projects linked yet. Run `ds link` in another project."

        lines.append(f"Linked projects: {', '.join(p['name'] for p in other_projects)}\n")

        if query:
            results = self.search(query, limit=6, exclude_project=current_project)
            if results:
                lines.append(f"Relevant patterns matching '{query}':")
                for r in results:
                    ts = r["recorded_at"][:10]
                    src = f" [{r['source_file']}]" if r["source_file"] else ""
                    lines.append(
                        f"  [{r['pattern_type'].upper()}] {r['project_name']}{src} ({ts})\n"
                        f"  → {r['content'][:200]}"
                    )
            else:
                lines.append(f"No cross-project matches found for '{query}'.")
        else:
            # Recent snapshots from each other project
            conn = self._connect()
            for proj in other_projects[:4]:
                snap = conn.execute(
                    """
                    SELECT session_summary, recent_files, recent_tasks, synced_at
                    FROM snapshots WHERE project_id = ?
                    ORDER BY synced_at DESC LIMIT 1
                    """,
                    (proj["id"],),
                ).fetchone()
                if snap:
                    files = json.loads(snap["recent_files"] or "[]")
                    tasks = json.loads(snap["recent_tasks"] or "[]")
                    ts = snap["synced_at"][:16]
                    lines.append(
                        f"\n[{proj['name']}] (last synced {ts})\n"
                        f"  Summary : {(snap['session_summary'] or 'none')[:180]}\n"
                        f"  Files   : {', '.join(files[:5]) or 'none'}\n"
                        f"  Tasks   : {', '.join(tasks[:3]) or 'none'}"
                    )

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Return counts for the global index."""
        conn = self._connect()
        return {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
            "patterns": conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0],
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
