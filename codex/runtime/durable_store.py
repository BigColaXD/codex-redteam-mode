from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .models import EvidenceNode, OperationState, ToolCallResult, utc_now
from .security import redact_sensitive, secure_directory, secure_file


SCHEMA_VERSION = 2


class DurableStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        secure_directory(self.root)
        self.path = self.root / "runtime.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        secure_file(self.path)
        secure_file(self.path.with_name(f"{self.path.name}-wal"))
        secure_file(self.path.with_name(f"{self.path.name}-shm"))
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.transaction(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operations_session
                    ON operations(session_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS operation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES operations(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS action_leases (
                    run_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(run_id, action_id),
                    FOREIGN KEY(run_id) REFERENCES operations(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS action_results (
                    run_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, idempotency_key),
                    FOREIGN KEY(run_id) REFERENCES operations(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS evidence_nodes (
                    evidence_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    node_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, action_id, artifact_type, tool, content_hash),
                    FOREIGN KEY(run_id) REFERENCES operations(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            evidence_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(evidence_nodes)").fetchall()
            }
            if "tool" not in evidence_columns:
                legacy_rows = connection.execute(
                    "SELECT evidence_id, run_id, action_id, artifact_type, content_hash, node_json, created_at FROM evidence_nodes"
                ).fetchall()
                connection.execute("ALTER TABLE evidence_nodes RENAME TO evidence_nodes_v1")
                connection.execute(
                    """
                    CREATE TABLE evidence_nodes (
                        evidence_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        action_id TEXT NOT NULL,
                        artifact_type TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        node_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(run_id, action_id, artifact_type, tool, content_hash),
                        FOREIGN KEY(run_id) REFERENCES operations(run_id) ON DELETE CASCADE
                    )
                    """
                )
                for row in legacy_rows:
                    try:
                        node_payload = json.loads(str(row["node_json"]))
                    except json.JSONDecodeError:
                        node_payload = {}
                    tool = str(node_payload.get("tool") or "legacy") if isinstance(node_payload, dict) else "legacy"
                    connection.execute(
                        "INSERT OR IGNORE INTO evidence_nodes(evidence_id, run_id, action_id, artifact_type, tool, content_hash, node_json, created_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["evidence_id"],
                            row["run_id"],
                            row["action_id"],
                            row["artifact_type"],
                            tool,
                            row["content_hash"],
                            row["node_json"],
                            row["created_at"],
                        ),
                    )
                connection.execute("DROP TABLE evidence_nodes_v1")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence_nodes(run_id, created_at, evidence_id)"
            )
            connection.execute(
                "INSERT INTO schema_metadata(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def save_operation(self, state: OperationState, *, event_type: str = "state_saved", event: Mapping[str, Any] | None = None) -> None:
        state.updated_at = utc_now()
        serialized = json.dumps(redact_sensitive(state.to_dict()), ensure_ascii=False, sort_keys=True, default=str)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO operations(run_id, session_id, goal_id, workflow_id, status, state_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    goal_id=excluded.goal_id,
                    workflow_id=excluded.workflow_id,
                    status=excluded.status,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (
                    state.run_id,
                    state.session_id,
                    state.goal.goal_id,
                    state.workflow_id,
                    state.status,
                    serialized,
                    state.created_at,
                    state.updated_at,
                ),
            )
            connection.execute(
                "INSERT INTO operation_events(run_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?)",
                (
                    state.run_id,
                    event_type,
                    json.dumps(redact_sensitive(dict(event or {})), ensure_ascii=False, sort_keys=True, default=str),
                    utc_now(),
                ),
            )

    def create_operation(self, state: OperationState, *, event: Mapping[str, Any]) -> OperationState:
        state.updated_at = utc_now()
        serialized = json.dumps(redact_sensitive(state.to_dict()), ensure_ascii=False, sort_keys=True, default=str)
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO operations(run_id, session_id, goal_id, workflow_id, status, state_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (
                    state.run_id,
                    state.session_id,
                    state.goal.goal_id,
                    state.workflow_id,
                    state.status,
                    serialized,
                    state.created_at,
                    state.updated_at,
                ),
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO operation_events(run_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?)",
                    (
                        state.run_id,
                        "operation_started",
                        json.dumps(redact_sensitive(dict(event)), ensure_ascii=False, sort_keys=True, default=str),
                        utc_now(),
                    ),
                )
                return state
            row = connection.execute("SELECT state_json FROM operations WHERE run_id=?", (state.run_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"operation_create_race:{state.run_id}")
        payload = json.loads(str(row["state_json"]))
        existing = OperationState.from_dict(payload) if isinstance(payload, dict) else None
        if existing is None:
            raise RuntimeError(f"operation_state_corrupt:{state.run_id}")
        return existing

    def load_operation(self, run_id: str) -> OperationState | None:
        with self.connection() as connection:
            row = connection.execute("SELECT state_json FROM operations WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["state_json"]))
        except json.JSONDecodeError:
            return None
        try:
            return OperationState.from_dict(payload) if isinstance(payload, dict) else None
        except (TypeError, ValueError, OverflowError):
            return None

    def latest_operation(self, session_id: str, *, include_terminal: bool = True) -> OperationState | None:
        query = "SELECT state_json FROM operations WHERE session_id=?"
        parameters: tuple[Any, ...] = (session_id,)
        if not include_terminal:
            query += " AND status NOT IN ('completed', 'failed', 'cancelled')"
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self.connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["state_json"]))
        except json.JSONDecodeError:
            return None
        try:
            return OperationState.from_dict(payload) if isinstance(payload, dict) else None
        except (TypeError, ValueError, OverflowError):
            return None

    def operations_for_batch(self, batch_session_id: str) -> tuple[OperationState, ...]:
        batch_id = batch_session_id.strip()
        if not batch_id:
            return ()
        escaped = batch_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT state_json FROM operations WHERE session_id LIKE ? ESCAPE '\\' ORDER BY created_at, session_id",
                (f"{escaped}:%",),
            ).fetchall()
        states: list[OperationState] = []
        for row in rows:
            try:
                payload = json.loads(str(row["state_json"]))
                state = OperationState.from_dict(payload) if isinstance(payload, dict) else None
            except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
                continue
            if state is not None and state.goal.starting_context.get("batch_session_id") == batch_id:
                states.append(state)
        states.sort(key=lambda item: int(item.goal.starting_context.get("batch_index") or 0))
        return tuple(states)

    def append_event(self, run_id: str, event_type: str, payload: Mapping[str, Any] | None = None) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO operation_events(run_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?)",
                (run_id, event_type, json.dumps(redact_sensitive(dict(payload or {})), ensure_ascii=False, default=str), utc_now()),
            )

    def events(self, run_id: str, *, after_event_id: int = 0, limit: int = 200) -> tuple[dict[str, Any], ...]:
        bounded_limit = max(1, min(1000, int(limit)))
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT event_id, event_type, payload_json, created_at FROM operation_events "
                "WHERE run_id=? AND event_id>? ORDER BY event_id LIMIT ?",
                (run_id, max(0, int(after_event_id)), bounded_limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                payload = {}
            events.append(
                {
                    "event_id": int(row["event_id"]),
                    "event_type": str(row["event_type"]),
                    "payload": payload,
                    "created_at": str(row["created_at"]),
                }
            )
        return tuple(events)

    def acquire_lease(self, run_id: str, action_id: str, owner: str, *, ttl_seconds: float = 120.0) -> bool:
        now = time.time()
        expires_at = now + max(1.0, ttl_seconds)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM action_leases WHERE run_id=? AND action_id=? AND expires_at<=?",
                (run_id, action_id, now),
            )
            row = connection.execute(
                "SELECT owner FROM action_leases WHERE run_id=? AND action_id=?",
                (run_id, action_id),
            ).fetchone()
            if row is not None and str(row["owner"]) != owner:
                return False
            connection.execute(
                """
                INSERT INTO action_leases(run_id, action_id, owner, expires_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(run_id, action_id) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at
                """,
                (run_id, action_id, owner, expires_at),
            )
        return True

    def release_lease(self, run_id: str, action_id: str, owner: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM action_leases WHERE run_id=? AND action_id=? AND owner=?",
                (run_id, action_id, owner),
            )

    def cache_action_result(self, run_id: str, action_id: str, idempotency_key: str, result: ToolCallResult) -> None:
        payload = redact_sensitive({
            "status": result.status,
            "output": result.output,
            "error": result.error,
            "tool": result.tool,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "retryable": result.retryable,
        })
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO action_results(run_id, action_id, idempotency_key, result_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(run_id, idempotency_key) DO NOTHING
                """,
                (run_id, action_id, idempotency_key, json.dumps(payload, ensure_ascii=False, default=str), utc_now()),
            )

    def cached_action_result(self, run_id: str, idempotency_key: str) -> ToolCallResult | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM action_results WHERE run_id=? AND idempotency_key=?",
                (run_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["result_json"]))
        except json.JSONDecodeError:
            return None
        return ToolCallResult(
            status=str(payload.get("status") or "failed"),
            output=payload.get("output"),
            error=str(payload.get("error") or ""),
            tool=str(payload.get("tool") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or utc_now()),
            retryable=bool(payload.get("retryable", False)),
        )

    def save_evidence(self, node: EvidenceNode) -> None:
        serialized = json.dumps(redact_sensitive(node.to_dict()), ensure_ascii=False, sort_keys=True, default=str)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO evidence_nodes(evidence_id, run_id, action_id, artifact_type, tool, content_hash, node_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, action_id, artifact_type, tool, content_hash) DO NOTHING
                """,
                (
                    node.evidence_id,
                    node.run_id,
                    node.action_id,
                    node.artifact_type,
                    node.tool,
                    node.content_hash,
                    serialized,
                    node.created_at,
                ),
            )

    def evidence(self, run_id: str) -> tuple[EvidenceNode, ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT content_hash, node_json FROM evidence_nodes WHERE run_id=? ORDER BY created_at, evidence_id",
                (run_id,),
            ).fetchall()
        nodes: list[EvidenceNode] = []
        for row in rows:
            try:
                payload = json.loads(str(row["node_json"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                try:
                    node = EvidenceNode.from_dict(payload)
                except (TypeError, ValueError, OverflowError):
                    continue
                if node.content_hash == str(row["content_hash"]):
                    nodes.append(node)
        return tuple(nodes)
