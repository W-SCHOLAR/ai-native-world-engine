"""Persistence adapter skeletons.

The in-memory repository keeps the first commercial API implementation
dependency-light. A database-backed adapter can replace it without changing
engine code.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
import time
from typing import Any, Protocol
from uuid import uuid4

from .models import RunRecord, ScenarioRecord
from .scenario_defaults import default_scenarios


@dataclass(frozen=True, slots=True)
class RunLease:
    run_id: str
    worker_id: str
    token: str
    expires_at: float


@dataclass(slots=True)
class RunProgressWrite:
    """One atomic schema-v2 hot-path persistence unit."""

    run: RunRecord
    incremental: dict[str, Any]
    checkpoint: dict[str, Any] | None = None
    projection_delta: dict[str, Any] | None = None
    projection_keyframe: dict[str, Any] | None = None
    provider_attempts: list[dict[str, Any]] = field(default_factory=list)


class LeaseLostError(RuntimeError):
    pass


class RunRepository(Protocol):
    def list_scenarios(self) -> list[ScenarioRecord]:
        ...

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        ...

    def save_run(self, run: RunRecord) -> RunRecord:
        ...

    def get_run(self, run_id: str) -> RunRecord | None:
        ...

    def list_runs(self) -> list[RunRecord]:
        ...

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        ...

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        ...

    def release_run_lease(self, lease: RunLease) -> bool:
        ...

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        ...

    def save_run_progress(self, write: RunProgressWrite) -> RunRecord:
        ...

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        ...

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        ...

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        ...

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        ...

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        ...

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        ...

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        ...

    def consume_thought_occurrences(
        self, run_id: str, occurrence_ids: list[str]
    ) -> int:
        ...

    def save_final_result(self, run_id: str, result: dict[str, Any]) -> None:
        ...

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        ...

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        ...


class ClaimedRunRepository:
    """Fence Worker writes behind one live Run lease."""

    def __init__(self, repository: RunRepository, lease: RunLease) -> None:
        self.repository = repository
        self.lease = lease

    def list_scenarios(self) -> list[ScenarioRecord]:
        return self.repository.list_scenarios()

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        return self.repository.get_scenario(scenario_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        return self.repository.save_claimed_run(run, self.lease)

    def get_run(self, run_id: str) -> RunRecord | None:
        if run_id != self.lease.run_id:
            return None
        record = self.repository.get_run(run_id)
        return _copy_run(record) if record is not None else None

    def list_runs(self) -> list[RunRecord]:
        record = self.get_run(self.lease.run_id)
        return [record] if record is not None else []

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        return self.repository.claim_run(worker_id, lease_seconds)

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        renewed = self.repository.renew_run_lease(lease, lease_seconds)
        if renewed is not None and renewed.token == self.lease.token:
            self.lease = renewed
        return renewed

    def release_run_lease(self, lease: RunLease) -> bool:
        return self.repository.release_run_lease(lease)

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        return self.repository.save_claimed_run(run, lease)

    def save_run_progress(self, write: RunProgressWrite) -> RunRecord:
        method = getattr(self.repository, "save_claimed_run_progress")
        return method(write, self.lease)

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get_latest_checkpoint(run_id)

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return self.repository.list_tick_commits(run_id, after)

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self.repository.list_run_events(run_id, after, limit)

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self.repository.list_run_traces(run_id, after, limit)

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self.repository.list_projection_deltas(run_id, after, limit)

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get_latest_projection(run_id)

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        return self.repository.consume_thought_schedules(run_id, sequences)

    def consume_thought_occurrences(
        self, run_id: str, occurrence_ids: list[str]
    ) -> int:
        return self.repository.consume_thought_occurrences(run_id, occurrence_ids)

    def save_final_result(self, run_id: str, result: dict[str, Any]) -> None:
        self.repository.save_final_result(run_id, result)

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get_final_result(run_id)

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        return self.repository.get_run_recovery_data(run_id)


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._scenarios: dict[str, ScenarioRecord] = default_scenarios()
        self._leases: dict[str, RunLease] = {}
        self._lock = RLock()
        _init_incremental_store(self)

    def list_scenarios(self) -> list[ScenarioRecord]:
        return list(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        return self._scenarios.get(scenario_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        self._runs[run.id] = run
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        return list(self._runs.values())

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        now = time.time()
        with self._lock:
            for run in sorted(self._runs.values(), key=lambda item: (item.created_at, item.id)):
                if run.status.value not in {"queued", "running"}:
                    continue
                existing = self._leases.get(run.id)
                if existing is not None and existing.expires_at > now:
                    continue
                lease = _new_lease(run.id, worker_id, lease_seconds, now)
                self._leases[run.id] = lease
                return lease
        return None

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        now = time.time()
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token or current.expires_at <= now:
                return None
            renewed = RunLease(
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                token=lease.token,
                expires_at=now + max(float(lease_seconds), 0.001),
            )
            self._leases[lease.run_id] = renewed
            return renewed

    def release_run_lease(self, lease: RunLease) -> bool:
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token:
                return False
            del self._leases[lease.run_id]
            return True

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token or current.expires_at <= time.time():
                raise LeaseLostError(f"run lease lost: {lease.run_id}")
            _require_unchanged_control_state(self._runs.get(run.id), run)
            self._runs[run.id] = run
            return run

    def save_run_progress(self, write: RunProgressWrite) -> RunRecord:
        with self._lock:
            return _save_incremental_memory(self, write)

    def save_claimed_run_progress(self, write: RunProgressWrite, lease: RunLease) -> RunRecord:
        with self._lock:
            _require_memory_lease(self, lease)
            return _save_incremental_memory(self, write)

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return _latest_memory_value(self._checkpoints, run_id)

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return _memory_rows(self._tick_commits, run_id, after, 0, "commit")

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._run_events, run_id, after, limit)

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._run_traces, run_id, after, limit)

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._projection_deltas, run_id, after, limit)

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        return _copy_json(self._projections.get(run_id))

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        with self._lock:
            return _consume_memory_thought_schedules(self, run_id, sequences)

    def consume_thought_occurrences(
        self, run_id: str, occurrence_ids: list[str]
    ) -> int:
        with self._lock:
            return _consume_memory_thought_occurrences(
                self, run_id, occurrence_ids
            )

    def save_final_result(self, run_id: str, result: dict[str, Any]) -> None:
        self._final_results[run_id] = _copy_json(result)

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        return _copy_json(self._final_results.get(run_id))

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        return _memory_recovery_data(self, run_id)


class JsonFileRunRepository:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "repository.json"
        self._runs: dict[str, RunRecord] = {}
        self._scenarios: dict[str, ScenarioRecord] = default_scenarios()
        self._leases: dict[str, RunLease] = {}
        self._lock = RLock()
        _init_incremental_store(self)
        self._load()

    def list_scenarios(self) -> list[ScenarioRecord]:
        return list(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        return self._scenarios.get(scenario_id)

    def save_run(self, run: RunRecord) -> RunRecord:
        self._runs[run.id] = run
        self._persist()
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        return list(self._runs.values())

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        now = time.time()
        with self._lock:
            for run in sorted(self._runs.values(), key=lambda item: (item.created_at, item.id)):
                if run.status.value not in {"queued", "running"}:
                    continue
                existing = self._leases.get(run.id)
                if existing is not None and existing.expires_at > now:
                    continue
                lease = _new_lease(run.id, worker_id, lease_seconds, now)
                self._leases[run.id] = lease
                return lease
        return None

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        now = time.time()
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token or current.expires_at <= now:
                return None
            renewed = RunLease(
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                token=lease.token,
                expires_at=now + max(float(lease_seconds), 0.001),
            )
            self._leases[lease.run_id] = renewed
            return renewed

    def release_run_lease(self, lease: RunLease) -> bool:
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token:
                return False
            del self._leases[lease.run_id]
            return True

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        with self._lock:
            current = self._leases.get(lease.run_id)
            if current is None or current.token != lease.token or current.expires_at <= time.time():
                raise LeaseLostError(f"run lease lost: {lease.run_id}")
            _require_unchanged_control_state(self._runs.get(run.id), run)
            self._runs[run.id] = run
            self._persist()
            return run

    def save_run_progress(self, write: RunProgressWrite) -> RunRecord:
        with self._lock:
            record = _save_incremental_memory(self, write)
            self._persist()
            return record

    def save_claimed_run_progress(self, write: RunProgressWrite, lease: RunLease) -> RunRecord:
        with self._lock:
            _require_memory_lease(self, lease)
            record = _save_incremental_memory(self, write)
            self._persist()
            return record

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return _latest_memory_value(self._checkpoints, run_id)

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return _memory_rows(self._tick_commits, run_id, after, 0, "commit")

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._run_events, run_id, after, limit)

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._run_traces, run_id, after, limit)

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return _memory_rows(self._projection_deltas, run_id, after, limit)

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        return _copy_json(self._projections.get(run_id))

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        with self._lock:
            consumed = _consume_memory_thought_schedules(self, run_id, sequences)
            if consumed:
                self._persist()
            return consumed

    def consume_thought_occurrences(
        self, run_id: str, occurrence_ids: list[str]
    ) -> int:
        with self._lock:
            consumed = _consume_memory_thought_occurrences(
                self, run_id, occurrence_ids
            )
            if consumed:
                self._persist()
            return consumed

    def save_final_result(self, run_id: str, result: dict[str, Any]) -> None:
        self._final_results[run_id] = _copy_json(result)
        self._persist()

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        return _copy_json(self._final_results.get(run_id))

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        return _memory_recovery_data(self, run_id)

    def _load(self) -> None:
        if not self.path.exists():
            self._persist()
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw.get("scenarios"), list):
            self._scenarios = {
                str(item["id"]): ScenarioRecord(
                    id=str(item["id"]),
                    name=str(item.get("name", item["id"])),
                    description=str(item.get("description", "")),
                    source=str(item.get("source", "engine")),
                    defaults=_dict(item.get("defaults")),
                )
                for item in raw["scenarios"]
                if isinstance(item, dict) and item.get("id")
            }
        if isinstance(raw.get("runs"), list):
            self._runs = {
                str(item["id"]): RunRecord.from_storage_dict(item)
                for item in raw["runs"]
                if isinstance(item, dict) and item.get("id")
            }
        incremental = _dict(raw.get("incremental"))
        _load_json_incremental_store(self, incremental)

    def _persist(self) -> None:
        payload = {
            "scenarios": [scenario.to_dict() for scenario in self._scenarios.values()],
            "runs": [
                run.to_live_storage_dict()
                if run.runtime_state.get("mode") == "cooperative_tick"
                else run.to_storage_dict()
                for run in self._runs.values()
            ],
            "incremental": _dump_json_incremental_store(self),
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


class SQLiteRunRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._seed_scenarios()

    def list_scenarios(self) -> list[ScenarioRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select id, name, description, source, defaults_json from scenarios order by id"
            ).fetchall()
        return [
            ScenarioRecord(
                id=str(row["id"]),
                name=str(row["name"]),
                description=str(row["description"]),
                source=str(row["source"]),
                defaults=json.loads(str(row["defaults_json"] or "{}")),
            )
            for row in rows
        ]

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select id, name, description, source, defaults_json from scenarios where id = ?",
                (scenario_id,),
            ).fetchone()
        if row is None:
            return None
        return ScenarioRecord(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            source=str(row["source"]),
            defaults=json.loads(str(row["defaults_json"] or "{}")),
        )

    def save_run(self, run: RunRecord) -> RunRecord:
        payload = json.dumps(run.to_storage_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                insert into runs (
                    id, owner_id, scenario, seed, ticks, status, control_state, error,
                    created_at, updated_at, payload_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    owner_id = excluded.owner_id,
                    scenario = excluded.scenario,
                    seed = excluded.seed,
                    ticks = excluded.ticks,
                    status = excluded.status,
                    control_state = excluded.control_state,
                    error = excluded.error,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    run.id,
                    run.owner_id,
                    run.scenario,
                    int(run.seed),
                    int(run.ticks),
                    run.status.value,
                    run.control_state.value,
                    run.error,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    payload,
                ),
            )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select payload_json from runs where id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RunRecord.from_storage_dict(json.loads(str(row["payload_json"])))

    def list_runs(self) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select payload_json from runs order by created_at, id"
            ).fetchall()
        return [RunRecord.from_storage_dict(json.loads(str(row["payload_json"]))) for row in rows]

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        now = time.time()
        expires_at = now + max(float(lease_seconds), 0.001)
        token = uuid4().hex
        with self._connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select id
                from runs
                where status in ('queued', 'running')
                  and (lease_expires_at is null or lease_expires_at <= ?)
                order by created_at, id
                limit 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            run_id = str(row["id"])
            updated = connection.execute(
                """
                update runs
                set lease_owner = ?, lease_token = ?, lease_expires_at = ?, lease_heartbeat_at = ?
                where id = ? and (lease_expires_at is null or lease_expires_at <= ?)
                """,
                (worker_id, token, expires_at, now, run_id, now),
            )
            if updated.rowcount != 1:
                return None
        return RunLease(run_id=run_id, worker_id=worker_id, token=token, expires_at=expires_at)

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        now = time.time()
        expires_at = now + max(float(lease_seconds), 0.001)
        with self._connect() as connection:
            updated = connection.execute(
                """
                update runs
                set lease_expires_at = ?, lease_heartbeat_at = ?
                where id = ? and lease_owner = ? and lease_token = ? and lease_expires_at > ?
                """,
                (expires_at, now, lease.run_id, lease.worker_id, lease.token, now),
            )
        if updated.rowcount != 1:
            return None
        return RunLease(
            run_id=lease.run_id,
            worker_id=lease.worker_id,
            token=lease.token,
            expires_at=expires_at,
        )

    def release_run_lease(self, lease: RunLease) -> bool:
        with self._connect() as connection:
            updated = connection.execute(
                """
                update runs
                set lease_owner = null, lease_token = null,
                    lease_expires_at = null, lease_heartbeat_at = null
                where id = ? and lease_owner = ? and lease_token = ?
                """,
                (lease.run_id, lease.worker_id, lease.token),
            )
        return updated.rowcount == 1

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        now = time.time()
        payload = json.dumps(run.to_storage_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            updated = connection.execute(
                """
                update runs
                set owner_id = ?, scenario = ?, seed = ?, ticks = ?, status = ?,
                    control_state = ?, error = ?, updated_at = ?, payload_json = ?
                where id = ? and lease_owner = ? and lease_token = ? and lease_expires_at > ?
                  and control_state = ?
                """,
                (
                    run.owner_id,
                    run.scenario,
                    int(run.seed),
                    int(run.ticks),
                    run.status.value,
                    run.control_state.value,
                    run.error,
                    run.updated_at.isoformat(),
                    payload,
                    run.id,
                    lease.worker_id,
                    lease.token,
                    now,
                    run.control_state.value,
                ),
            )
        if updated.rowcount != 1:
            raise LeaseLostError(f"run lease lost: {lease.run_id}")
        return run

    def save_run_progress(self, write: RunProgressWrite) -> RunRecord:
        return self._save_run_progress(write)

    def save_claimed_run_progress(
        self, write: RunProgressWrite, lease: RunLease
    ) -> RunRecord:
        return self._save_run_progress(write, lease)

    def _save_run_progress(
        self, write: RunProgressWrite, lease: RunLease | None = None
    ) -> RunRecord:
        incremental = _copy_json(write.incremental)
        commit = _dict(incremental.get("commit"))
        sequence = int(commit.get("sequence", 0) or 0)
        checksum = str(commit.get("checksum", ""))
        if sequence <= 0 or not checksum:
            raise ValueError("incremental write requires a valid TickCommit")
        payload = json.dumps(
            write.run.to_live_storage_dict(), ensure_ascii=False, sort_keys=True
        )
        with self._connect() as connection:
            connection.execute("begin immediate")
            if lease is not None:
                row = connection.execute(
                    """
                    select status, control_state from runs
                    where id = ? and lease_owner = ? and lease_token = ?
                      and lease_expires_at > ?
                    """,
                    (lease.run_id, lease.worker_id, lease.token, time.time()),
                ).fetchone()
                if row is None:
                    raise LeaseLostError(f"run lease lost: {lease.run_id}")
            else:
                row = connection.execute(
                    "select status, control_state from runs where id = ?",
                    (write.run.id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"run not found: {write.run.id}")
            _require_progress_writable(
                str(row["status"]),
                str(row["control_state"]),
                write.run.id,
            )
            existing = connection.execute(
                """
                select checksum from run_tick_commits
                where run_id = ? and commit_sequence = ?
                """,
                (write.run.id, sequence),
            ).fetchone()
            if existing is not None and str(existing["checksum"]) != checksum:
                raise ValueError(f"divergent TickCommit sequence: {sequence}")
            connection.execute(
                """
                insert into run_tick_commits (
                    run_id, commit_sequence, commit_id, checksum, commit_json
                ) values (?, ?, ?, ?, ?)
                on conflict(run_id, commit_sequence) do nothing
                """,
                (
                    write.run.id,
                    sequence,
                    str(commit.get("id", "")),
                    checksum,
                    json.dumps(incremental, ensure_ascii=False, sort_keys=True),
                ),
            )
            for event in incremental.get("events", []):
                if not isinstance(event, dict):
                    continue
                event_sequence = int(event.get("sequence", 0) or 0)
                if event_sequence <= 0:
                    continue
                connection.execute(
                    """
                    insert into run_events (run_id, sequence, tick, kind, payload_json)
                    values (?, ?, ?, ?, ?)
                    on conflict(run_id, sequence) do nothing
                    """,
                    (
                        write.run.id,
                        event_sequence,
                        int(event.get("tick", 0) or 0),
                        str(event.get("kind", "")),
                        json.dumps(event, ensure_ascii=False, sort_keys=True),
                    ),
                )
            trace_start = _range_value(commit.get("trace_range"), 0)
            for index, trace in enumerate(incremental.get("traces", []), start=1):
                if not isinstance(trace, dict):
                    continue
                connection.execute(
                    """
                    insert into run_traces (run_id, sequence, tick, kind, payload_json)
                    values (?, ?, ?, ?, ?)
                    on conflict(run_id, sequence) do nothing
                    """,
                    (
                        write.run.id,
                        trace_start + index,
                        int(trace.get("tick", 0) or 0),
                        str(trace.get("kind", "")),
                        json.dumps(trace, ensure_ascii=False, sort_keys=True),
                    ),
                )
            attempts = [
                *incremental.get("provider_attempts", []),
                *write.provider_attempts,
            ]
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                attempt_id = str(attempt.get("attempt_id", ""))
                if not attempt_id:
                    continue
                connection.execute(
                    """
                    insert into run_provider_attempts (
                        run_id, attempt_id, commit_sequence, payload_json
                    ) values (?, ?, ?, ?)
                    on conflict(run_id, attempt_id) do nothing
                    """,
                    (
                        write.run.id,
                        attempt_id,
                        sequence,
                        json.dumps(attempt, ensure_ascii=False, sort_keys=True),
                    ),
                )
            if write.checkpoint is not None:
                connection.execute(
                    """
                    insert into run_checkpoints (run_id, commit_sequence, checkpoint_json)
                    values (?, ?, ?)
                    on conflict(run_id, commit_sequence) do update set
                        checkpoint_json = excluded.checkpoint_json
                    """,
                    (
                        write.run.id,
                        sequence,
                        json.dumps(write.checkpoint, ensure_ascii=False, sort_keys=True),
                    ),
                )
            if write.projection_delta is not None:
                connection.execute(
                    """
                    insert into run_projection_deltas (run_id, sequence, delta_json)
                    values (?, ?, ?)
                    on conflict(run_id, sequence) do update set
                        delta_json = excluded.delta_json
                    """,
                    (
                        write.run.id,
                        sequence,
                        json.dumps(
                            write.projection_delta,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
            if write.projection_keyframe is not None:
                connection.execute(
                    """
                    insert into run_projections (run_id, sequence, projection_json)
                    values (?, ?, ?)
                    on conflict(run_id) do update set
                        sequence = excluded.sequence,
                        projection_json = excluded.projection_json
                    """,
                    (
                        write.run.id,
                        sequence,
                        json.dumps(
                            write.projection_keyframe,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
                connection.execute(
                    """
                    delete from run_projection_deltas
                    where run_id = ? and sequence < ?
                    """,
                    (write.run.id, sequence),
                )
            connection.execute(
                """
                update runs set owner_id = ?, scenario = ?, seed = ?, ticks = ?,
                    status = ?, control_state = ?, error = ?, updated_at = ?,
                    payload_json = ? where id = ?
                """,
                (
                    write.run.owner_id,
                    write.run.scenario,
                    int(write.run.seed),
                    int(write.run.ticks),
                    write.run.status.value,
                    write.run.control_state.value,
                    write.run.error,
                    write.run.updated_at.isoformat(),
                    payload,
                    write.run.id,
                ),
            )
        return write.run

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return self._latest_json_row(
            "run_checkpoints", "checkpoint_json", run_id
        )

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select commit_json from run_tick_commits
                where run_id = ? and commit_sequence > ?
                order by commit_sequence
                """,
                (run_id, int(after)),
            ).fetchall()
        return [
            _dict(json.loads(str(row["commit_json"]))).get("commit", {})
            for row in rows
        ]

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json_rows("run_events", "payload_json", run_id, after, limit)

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json_rows("run_traces", "payload_json", run_id, after, limit)

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json_rows("run_projection_deltas", "delta_json", run_id, after, limit)

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        return self._latest_json_row("run_projections", "projection_json", run_id)

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        wanted = {int(value) for value in sequences if int(value) > 0}
        if not wanted:
            return 0
        with self._connect() as connection:
            rows = connection.execute(
                "select sequence, delta_json from run_projection_deltas where run_id = ?",
                (run_id,),
            ).fetchall()
            consumed = 0
            for row in rows:
                delta = _dict(json.loads(str(row["delta_json"])))
                updated, removed = _without_thought_schedules(delta, wanted)
                if removed:
                    consumed += removed
                    connection.execute(
                        "update run_projection_deltas set delta_json = ? where run_id = ? and sequence = ?",
                        (json.dumps(updated, ensure_ascii=False, sort_keys=True), run_id, int(row["sequence"])),
                    )
        return consumed

    def consume_thought_occurrences(
        self, run_id: str, occurrence_ids: list[str]
    ) -> int:
        wanted = {str(value) for value in occurrence_ids if str(value)}
        if not wanted:
            return 0
        with self._connect() as connection:
            rows = connection.execute(
                "select sequence, delta_json from run_projection_deltas where run_id = ?",
                (run_id,),
            ).fetchall()
            consumed = 0
            for row in rows:
                delta = _dict(json.loads(str(row["delta_json"])))
                updated, removed = _without_thought_occurrences(delta, wanted)
                if removed:
                    consumed += removed
                    connection.execute(
                        "update run_projection_deltas set delta_json = ? where run_id = ? and sequence = ?",
                        (
                            json.dumps(updated, ensure_ascii=False, sort_keys=True),
                            run_id,
                            int(row["sequence"]),
                        ),
                    )
        return consumed

    def save_final_result(self, run_id: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into run_final_results (run_id, result_json)
                values (?, ?)
                on conflict(run_id) do update set result_json = excluded.result_json
                """,
                (run_id, json.dumps(result, ensure_ascii=False, sort_keys=True)),
            )

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        return self._latest_json_row("run_final_results", "result_json", run_id)

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        checkpoint = self.get_latest_checkpoint(run_id) or {}
        checkpoint_commit = int(checkpoint.get("commit_sequence", 0) or 0)
        event_cursor = int(checkpoint.get("event_cursor", 0) or 0)
        trace_cursor = int(checkpoint.get("trace_cursor", 0) or 0)
        with self._connect() as connection:
            rows = connection.execute(
                """
                select commit_json from run_tick_commits
                where run_id = ? and commit_sequence > ? order by commit_sequence
                """,
                (run_id, checkpoint_commit),
            ).fetchall()
            attempt_rows = connection.execute(
                """
                select payload_json from run_provider_attempts
                where run_id = ? and commit_sequence > ? order by commit_sequence, attempt_id
                """,
                (run_id, checkpoint_commit),
            ).fetchall()
        additions = [json.loads(str(row["commit_json"])) for row in rows]
        return {
            "checkpoint": checkpoint or None,
            "commits": [_dict(item.get("commit")) for item in additions],
            "events": self.list_run_events(run_id, event_cursor, 0),
            "traces": self.list_run_traces(run_id, trace_cursor, 0),
            "provider_outputs": _flatten_additions(additions, "provider_outputs"),
            "provider_attempts": [
                json.loads(str(row["payload_json"])) for row in attempt_rows
            ],
            "provider_audits": _flatten_additions(additions, "provider_audits"),
            "intervention_audits": _flatten_additions(
                additions, "intervention_audits"
            ),
            "memory_consolidation_report": _flatten_additions(
                additions, "memory_consolidation"
            ),
            "sovereign_intent_audits": _flatten_additions(
                additions, "sovereign_intent_audits"
            ),
        }

    def _list_json_rows(
        self,
        table: str,
        column: str,
        run_id: str,
        after: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        limit_clause = "" if int(limit) <= 0 else " limit ?"
        params: tuple[object, ...] = (run_id, int(after))
        if int(limit) > 0:
            params = (*params, int(limit))
        with self._connect() as connection:
            rows = connection.execute(
                f"select {column} from {table} where run_id = ? and sequence > ? order by sequence{limit_clause}",
                params,
            ).fetchall()
        return [json.loads(str(row[column])) for row in rows]

    def _latest_json_row(
        self, table: str, column: str, run_id: str
    ) -> dict[str, Any] | None:
        if table == "run_checkpoints":
            order = " order by commit_sequence desc"
        elif table == "run_final_results":
            order = ""
        else:
            order = " order by sequence desc"
        with self._connect() as connection:
            row = connection.execute(
                f"select {column} from {table} where run_id = ?{order} limit 1",
                (run_id,),
            ).fetchone()
        return json.loads(str(row[column])) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists scenarios (
                    id text primary key,
                    name text not null,
                    description text not null,
                    source text not null,
                    defaults_json text not null default '{}'
                );

                create table if not exists runs (
                    id text primary key,
                    owner_id text not null default 'local',
                    scenario text not null,
                    seed integer not null,
                    ticks integer not null,
                    status text not null,
                    control_state text not null default 'active',
                    error text not null default '',
                    created_at text not null,
                    updated_at text not null,
                    payload_json text not null,
                    lease_owner text,
                    lease_token text,
                    lease_expires_at real,
                    lease_heartbeat_at real
                );

                create table if not exists run_tick_commits (
                    run_id text not null,
                    commit_sequence integer not null,
                    commit_id text not null,
                    checksum text not null,
                    commit_json text not null,
                    primary key (run_id, commit_sequence)
                );

                create table if not exists run_events (
                    run_id text not null,
                    sequence integer not null,
                    tick integer not null,
                    kind text not null,
                    payload_json text not null,
                    primary key (run_id, sequence)
                );

                create table if not exists run_traces (
                    run_id text not null,
                    sequence integer not null,
                    tick integer not null,
                    kind text not null,
                    payload_json text not null,
                    primary key (run_id, sequence)
                );

                create table if not exists run_checkpoints (
                    run_id text not null,
                    commit_sequence integer not null,
                    checkpoint_json text not null,
                    primary key (run_id, commit_sequence)
                );

                create table if not exists run_projection_deltas (
                    run_id text not null,
                    sequence integer not null,
                    delta_json text not null,
                    primary key (run_id, sequence)
                );

                create table if not exists run_projections (
                    run_id text primary key,
                    sequence integer not null,
                    projection_json text not null
                );

                create table if not exists run_provider_attempts (
                    run_id text not null,
                    attempt_id text not null,
                    commit_sequence integer not null,
                    payload_json text not null,
                    primary key (run_id, attempt_id)
                );

                create table if not exists run_final_results (
                    run_id text primary key,
                    result_json text not null
                );

                create index if not exists idx_runs_status on runs(status);
                create index if not exists idx_runs_scenario on runs(scenario);
                create index if not exists idx_runs_updated_at on runs(updated_at);
                create index if not exists idx_run_events_tick on run_events(run_id, tick);
                create index if not exists idx_run_traces_tick on run_traces(run_id, tick);
                create index if not exists idx_run_provider_attempts_commit on run_provider_attempts(run_id, commit_sequence);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("pragma table_info(scenarios)").fetchall()
            }
            if "defaults_json" not in columns:
                connection.execute("alter table scenarios add column defaults_json text not null default '{}'")
            run_columns = {
                str(row["name"])
                for row in connection.execute("pragma table_info(runs)").fetchall()
            }
            if "owner_id" not in run_columns:
                connection.execute("alter table runs add column owner_id text not null default 'local'")
            if "control_state" not in run_columns:
                connection.execute("alter table runs add column control_state text not null default 'active'")
            if "lease_owner" not in run_columns:
                connection.execute("alter table runs add column lease_owner text")
            if "lease_token" not in run_columns:
                connection.execute("alter table runs add column lease_token text")
            if "lease_expires_at" not in run_columns:
                connection.execute("alter table runs add column lease_expires_at real")
            if "lease_heartbeat_at" not in run_columns:
                connection.execute("alter table runs add column lease_heartbeat_at real")
            connection.execute("create index if not exists idx_runs_owner_id on runs(owner_id)")
            connection.execute(
                "create index if not exists idx_runs_claim on runs(status, lease_expires_at, created_at)"
            )

    def _seed_scenarios(self) -> None:
        with self._connect() as connection:
            for scenario in default_scenarios().values():
                connection.execute(
                    """
                    insert into scenarios (id, name, description, source, defaults_json)
                    values (?, ?, ?, ?, ?)
                    on conflict(id) do update set
                        name = excluded.name,
                        description = excluded.description,
                        source = excluded.source,
                        defaults_json = excluded.defaults_json
                    """,
                    (
                        scenario.id,
                        scenario.name,
                        scenario.description,
                        scenario.source,
                        json.dumps(scenario.defaults, ensure_ascii=False, sort_keys=True),
                    ),
                )


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _new_lease(run_id: str, worker_id: str, lease_seconds: float, now: float) -> RunLease:
    return RunLease(
        run_id=run_id,
        worker_id=str(worker_id),
        token=uuid4().hex,
        expires_at=now + max(float(lease_seconds), 0.001),
    )


def _copy_run(run: RunRecord) -> RunRecord:
    return RunRecord.from_storage_dict(run.to_storage_dict())


def _init_incremental_store(repository: object) -> None:
    repository._tick_commits = {}  # type: ignore[attr-defined]
    repository._run_events = {}  # type: ignore[attr-defined]
    repository._run_traces = {}  # type: ignore[attr-defined]
    repository._checkpoints = {}  # type: ignore[attr-defined]
    repository._projection_deltas = {}  # type: ignore[attr-defined]
    repository._projections = {}  # type: ignore[attr-defined]
    repository._provider_attempts = {}  # type: ignore[attr-defined]
    repository._final_results = {}  # type: ignore[attr-defined]


def _without_thought_schedules(value: dict[str, Any], wanted: set[int]) -> tuple[dict[str, Any], int]:
    result = _copy_json(value)
    schedules = result.get("thought_schedules")
    if not isinstance(schedules, list):
        return result, 0
    retained = [
        item for item in schedules
        if not isinstance(item, dict) or int(item.get("sequence", 0) or 0) not in wanted
    ]
    result["thought_schedules"] = retained
    return result, len(schedules) - len(retained)


def _without_thought_occurrences(
    value: dict[str, Any], wanted: set[str]
) -> tuple[dict[str, Any], int]:
    result = _copy_json(value)
    schedules = result.get("thought_schedules")
    if not isinstance(schedules, list):
        return result, 0
    retained_schedules = []
    consumed = 0
    for raw_schedule in schedules:
        if not isinstance(raw_schedule, dict):
            retained_schedules.append(raw_schedule)
            continue
        schedule = _copy_json(raw_schedule)
        occurrences = schedule.get("occurrences")
        if not isinstance(occurrences, list):
            retained_schedules.append(schedule)
            continue
        retained_occurrences = []
        for occurrence in occurrences:
            occurrence_id = (
                str(occurrence.get("occurrence_id", ""))
                if isinstance(occurrence, dict)
                else ""
            )
            if occurrence_id and occurrence_id in wanted:
                consumed += 1
            else:
                retained_occurrences.append(occurrence)
        if retained_occurrences:
            schedule["occurrences"] = retained_occurrences
            retained_schedules.append(schedule)
    result["thought_schedules"] = retained_schedules
    return result, consumed


def _consume_memory_thought_schedules(repository: object, run_id: str, sequences: list[int]) -> int:
    wanted = {int(value) for value in sequences if int(value) > 0}
    if not wanted:
        return 0
    consumed = 0
    deltas = repository._projection_deltas.get(run_id, {})  # type: ignore[attr-defined]
    for sequence, delta in list(deltas.items()):
        updated, removed = _without_thought_schedules(_dict(delta), wanted)
        if removed:
            deltas[sequence] = updated
            consumed += removed
    return consumed


def _consume_memory_thought_occurrences(
    repository: object, run_id: str, occurrence_ids: list[str]
) -> int:
    wanted = {str(value) for value in occurrence_ids if str(value)}
    if not wanted:
        return 0
    consumed = 0
    deltas = repository._projection_deltas.get(run_id, {})  # type: ignore[attr-defined]
    for sequence, delta in list(deltas.items()):
        updated, removed = _without_thought_occurrences(_dict(delta), wanted)
        if removed:
            deltas[sequence] = updated
            consumed += removed
    return consumed


def _save_incremental_memory(repository: object, write: RunProgressWrite) -> RunRecord:
    current_run = repository._runs.get(write.run.id)  # type: ignore[attr-defined]
    if current_run is None:
        raise KeyError(f"run not found: {write.run.id}")
    _require_progress_writable(
        current_run.status.value,
        current_run.control_state.value,
        write.run.id,
    )
    incremental = _copy_json(write.incremental) or {}
    commit = _dict(incremental.get("commit"))
    sequence = int(commit.get("sequence", 0) or 0)
    if sequence <= 0:
        raise ValueError("incremental write requires a positive commit sequence")
    commits = repository._tick_commits.setdefault(write.run.id, {})  # type: ignore[attr-defined]
    existing = commits.get(sequence)
    if existing is not None:
        existing_commit = _dict(existing.get("commit"))
        if existing_commit.get("checksum") != commit.get("checksum"):
            raise ValueError(f"divergent TickCommit sequence: {sequence}")
    else:
        commits[sequence] = incremental
        events = repository._run_events.setdefault(write.run.id, {})  # type: ignore[attr-defined]
        for event in incremental.get("events", []):
            if isinstance(event, dict):
                event_sequence = int(event.get("sequence", 0) or 0)
                if event_sequence > 0:
                    events.setdefault(event_sequence, _copy_json(event))
        traces = repository._run_traces.setdefault(write.run.id, {})  # type: ignore[attr-defined]
        trace_start = int(_range_value(commit.get("trace_range"), 0))
        for index, trace in enumerate(incremental.get("traces", []), start=1):
            if isinstance(trace, dict):
                traces.setdefault(trace_start + index, _copy_json(trace))
        attempts = repository._provider_attempts.setdefault(write.run.id, {})  # type: ignore[attr-defined]
        for attempt in [*incremental.get("provider_attempts", []), *write.provider_attempts]:
            if not isinstance(attempt, dict):
                continue
            attempt_id = str(attempt.get("attempt_id", ""))
            if attempt_id:
                attempts.setdefault(attempt_id, _copy_json(attempt))
    if write.checkpoint is not None:
        repository._checkpoints.setdefault(write.run.id, {})[sequence] = _copy_json(  # type: ignore[attr-defined]
            write.checkpoint
        )
    if write.projection_delta is not None:
        deltas = repository._projection_deltas.setdefault(write.run.id, {})  # type: ignore[attr-defined]
        deltas[sequence] = _copy_json(
            write.projection_delta
        )
    if write.projection_keyframe is not None:
        repository._projections[write.run.id] = _copy_json(write.projection_keyframe)  # type: ignore[attr-defined]
        deltas = repository._projection_deltas.setdefault(write.run.id, {})  # type: ignore[attr-defined]
        for cursor in list(deltas):
            if cursor < sequence:
                del deltas[cursor]
    repository._runs[write.run.id] = write.run  # type: ignore[attr-defined]
    return write.run


def _require_memory_lease(repository: object, lease: RunLease) -> None:
    current = repository._leases.get(lease.run_id)  # type: ignore[attr-defined]
    if (
        current is None
        or current.token != lease.token
        or current.expires_at <= time.time()
    ):
        raise LeaseLostError(f"run lease lost: {lease.run_id}")


def _require_progress_writable(status: str, control_state: str, run_id: str) -> None:
    if control_state != "active" or status in {"completed", "failed"}:
        raise LeaseLostError(f"run no longer accepts progress: {run_id}")


def _require_unchanged_control_state(
    persisted: RunRecord | None, incoming: RunRecord
) -> None:
    if persisted is None:
        raise KeyError(f"run not found: {incoming.id}")
    terminal_changed = (
        persisted.status.value in {"completed", "failed"}
        and persisted.status != incoming.status
    )
    if persisted.control_state != incoming.control_state or terminal_changed:
        raise LeaseLostError(f"run control state changed: {incoming.id}")


def _memory_rows(
    collection: dict[str, dict[int, dict[str, Any]]],
    run_id: str,
    after: int,
    limit: int,
    nested_key: str = "",
) -> list[dict[str, Any]]:
    rows = [
        value
        for cursor, value in sorted(collection.get(run_id, {}).items())
        if int(cursor) > int(after)
    ]
    if limit > 0:
        rows = rows[: max(int(limit), 0)]
    if nested_key:
        rows = [_dict(row.get(nested_key)) for row in rows]
    return [_copy_json(row) or {} for row in rows]


def _latest_memory_value(
    collection: dict[str, dict[int, dict[str, Any]]], run_id: str
) -> dict[str, Any] | None:
    rows = collection.get(run_id, {})
    if not rows:
        return None
    return _copy_json(rows[max(rows)])


def _memory_recovery_data(repository: object, run_id: str) -> dict[str, Any]:
    checkpoint = _latest_memory_value(repository._checkpoints, run_id) or {}  # type: ignore[attr-defined]
    checkpoint_commit = int(checkpoint.get("commit_sequence", 0) or 0)
    event_cursor = int(checkpoint.get("event_cursor", 0) or 0)
    trace_cursor = int(checkpoint.get("trace_cursor", 0) or 0)
    additions = [
        value
        for sequence, value in sorted(
            repository._tick_commits.get(run_id, {}).items()  # type: ignore[attr-defined]
        )
        if int(sequence) > checkpoint_commit
    ]
    return {
        "checkpoint": checkpoint or None,
        "commits": [_dict(item.get("commit")) for item in additions],
        "events": _memory_rows(repository._run_events, run_id, event_cursor, 0),  # type: ignore[attr-defined]
        "traces": _memory_rows(repository._run_traces, run_id, trace_cursor, 0),  # type: ignore[attr-defined]
        "provider_outputs": _flatten_additions(additions, "provider_outputs"),
        "provider_attempts": list(
            attempt
            for attempt_id, attempt in repository._provider_attempts.get(run_id, {}).items()  # type: ignore[attr-defined]
            if _attempt_commit_after(repository, run_id, attempt_id, checkpoint_commit)
        ),
        "provider_audits": _flatten_additions(additions, "provider_audits"),
        "intervention_audits": _flatten_additions(
            additions, "intervention_audits"
        ),
        "memory_consolidation_report": _flatten_additions(
            additions, "memory_consolidation"
        ),
        "sovereign_intent_audits": _flatten_additions(
            additions, "sovereign_intent_audits"
        ),
    }


def _flatten_additions(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [
        _copy_json(item) or {}
        for row in rows
        for item in row.get(key, [])
        if isinstance(item, dict)
    ]


def _attempt_commit_after(repository: object, run_id: str, attempt_id: str, after: int) -> bool:
    for sequence, row in repository._tick_commits.get(run_id, {}).items():  # type: ignore[attr-defined]
        if int(sequence) <= int(after):
            continue
        attempts = row.get("provider_attempts", [])
        if isinstance(attempts, list) and any(
            isinstance(item, dict) and str(item.get("attempt_id", "")) == str(attempt_id)
            for item in attempts
        ):
            return True
    return False


def _dump_json_incremental_store(repository: object) -> dict[str, Any]:
    return {
        "tick_commits": repository._tick_commits,  # type: ignore[attr-defined]
        "events": repository._run_events,  # type: ignore[attr-defined]
        "traces": repository._run_traces,  # type: ignore[attr-defined]
        "checkpoints": repository._checkpoints,  # type: ignore[attr-defined]
        "projection_deltas": repository._projection_deltas,  # type: ignore[attr-defined]
        "projections": repository._projections,  # type: ignore[attr-defined]
        "provider_attempts": repository._provider_attempts,  # type: ignore[attr-defined]
        "final_results": repository._final_results,  # type: ignore[attr-defined]
    }


def _load_json_incremental_store(repository: object, value: dict[str, object]) -> None:
    mapping_fields = {
        "tick_commits": "_tick_commits",
        "events": "_run_events",
        "traces": "_run_traces",
        "checkpoints": "_checkpoints",
        "projection_deltas": "_projection_deltas",
    }
    for source, target in mapping_fields.items():
        raw_runs = _dict(value.get(source))
        setattr(
            repository,
            target,
            {
                str(run_id): {
                    int(cursor): _dict(row)
                    for cursor, row in _dict(rows).items()
                }
                for run_id, rows in raw_runs.items()
            },
        )
    for source, target in (
        ("projections", "_projections"),
        ("provider_attempts", "_provider_attempts"),
        ("final_results", "_final_results"),
    ):
        setattr(repository, target, _dict(value.get(source)))


def _copy_json(value: object) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False))


def _range_value(value: object, index: int) -> int:
    return int(value[index] or 0) if isinstance(value, list) and len(value) > index else 0
