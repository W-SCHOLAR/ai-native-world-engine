"""PostgreSQL JSONB Run repository with skip-locked Worker leases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from .models import RunRecord, ScenarioRecord
from .repository import (
    LeaseLostError,
    RunLease,
    RunProgressWrite,
    _without_thought_occurrences,
    _without_thought_schedules,
)
from .scenario_defaults import default_scenarios


ConnectionFactory = Callable[[], Any]

POSTGRES_SCHEMA_STATEMENTS = (
    """
    create table if not exists scenarios (
        id text primary key,
        name text not null,
        description text not null,
        source text not null,
        defaults_json jsonb not null default '{}'::jsonb
    )
    """,
    """
    create table if not exists runs (
        id text primary key,
        owner_id text not null,
        scenario text not null,
        seed bigint not null,
        ticks integer not null,
        status text not null,
        control_state text not null,
        error text not null default '',
        created_at timestamptz not null,
        updated_at timestamptz not null,
        payload_json jsonb not null,
        lease_owner text,
        lease_token text,
        lease_expires_at timestamptz,
        lease_heartbeat_at timestamptz
    )
    """,
    """
    create table if not exists run_tick_commits (
        run_id text not null,
        commit_sequence bigint not null,
        commit_id text not null,
        checksum text not null,
        commit_json jsonb not null,
        primary key (run_id, commit_sequence)
    )
    """,
    """
    create table if not exists run_events (
        run_id text not null,
        sequence bigint not null,
        tick bigint not null,
        kind text not null,
        payload_json jsonb not null,
        primary key (run_id, sequence)
    )
    """,
    """
    create table if not exists run_traces (
        run_id text not null,
        sequence bigint not null,
        tick bigint not null,
        kind text not null,
        payload_json jsonb not null,
        primary key (run_id, sequence)
    )
    """,
    """
    create table if not exists run_checkpoints (
        run_id text not null,
        commit_sequence bigint not null,
        checkpoint_json jsonb not null,
        primary key (run_id, commit_sequence)
    )
    """,
    """
    create table if not exists run_projection_deltas (
        run_id text not null,
        sequence bigint not null,
        delta_json jsonb not null,
        primary key (run_id, sequence)
    )
    """,
    """
    create table if not exists run_projections (
        run_id text primary key,
        sequence bigint not null,
        projection_json jsonb not null
    )
    """,
    """
    create table if not exists run_provider_attempts (
        run_id text not null,
        attempt_id text not null,
        commit_sequence bigint not null,
        payload_json jsonb not null,
        primary key (run_id, attempt_id)
    )
    """,
    """
    create table if not exists run_final_results (
        run_id text primary key,
        result_json jsonb not null
    )
    """,
    "create index if not exists idx_runs_owner_id on runs(owner_id)",
    "create index if not exists idx_runs_status on runs(status)",
    "create index if not exists idx_runs_scenario on runs(scenario)",
    "create index if not exists idx_runs_updated_at on runs(updated_at)",
    "create index if not exists idx_runs_claim on runs(status, lease_expires_at, created_at)",
    "create index if not exists idx_run_events_tick on run_events(run_id, tick)",
    "create index if not exists idx_run_traces_tick on run_traces(run_id, tick)",
    "create index if not exists idx_run_provider_attempts_commit on run_provider_attempts(run_id, commit_sequence)",
)

POSTGRES_CLAIM_SQL = """
with candidate as (
    select id
    from runs
    where status in ('queued', 'running')
      and (lease_expires_at is null or lease_expires_at <= current_timestamp)
    order by created_at, id
    for update skip locked
    limit 1
)
update runs as r
set lease_owner = %s,
    lease_token = %s,
    lease_expires_at = current_timestamp + (%s * interval '1 second'),
    lease_heartbeat_at = current_timestamp
from candidate
where r.id = candidate.id
returning r.id, extract(epoch from r.lease_expires_at) as lease_expires_epoch
"""


class PostgresRunRepository:
    def __init__(self, dsn: str, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = str(dsn)
        if not self.dsn:
            raise ValueError("PostgreSQL database URL is required")
        self._connection_factory = connection_factory or _psycopg_connection_factory(self.dsn)
        self._init_schema()
        self._seed_scenarios()

    def list_scenarios(self) -> list[ScenarioRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select id, name, description, source, defaults_json from scenarios order by id"
            ).fetchall()
        return [_scenario_from_row(row) for row in rows]

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select id, name, description, source, defaults_json from scenarios where id = %s",
                (scenario_id,),
            ).fetchone()
        return _scenario_from_row(row) if row is not None else None

    def save_run(self, run: RunRecord) -> RunRecord:
        payload = json.dumps(run.to_storage_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                insert into runs (
                    id, owner_id, scenario, seed, ticks, status, control_state, error,
                    created_at, updated_at, payload_json
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
                _run_parameters(run, payload),
            )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select payload_json from runs where id = %s",
                (run_id,),
            ).fetchone()
        return _run_from_row(row) if row is not None else None

    def list_runs(self) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select payload_json from runs order by created_at, id"
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def claim_run(self, worker_id: str, lease_seconds: float) -> RunLease | None:
        token = uuid4().hex
        with self._connect() as connection:
            row = connection.execute(
                POSTGRES_CLAIM_SQL,
                (str(worker_id), token, max(float(lease_seconds), 0.001)),
            ).fetchone()
        if row is None:
            return None
        return RunLease(
            run_id=str(row["id"]),
            worker_id=str(worker_id),
            token=token,
            expires_at=float(row["lease_expires_epoch"]),
        )

    def renew_run_lease(self, lease: RunLease, lease_seconds: float) -> RunLease | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                update runs
                set lease_expires_at = current_timestamp + (%s * interval '1 second'),
                    lease_heartbeat_at = current_timestamp
                where id = %s and lease_owner = %s and lease_token = %s
                  and lease_expires_at > current_timestamp
                returning extract(epoch from lease_expires_at) as lease_expires_epoch
                """,
                (
                    max(float(lease_seconds), 0.001),
                    lease.run_id,
                    lease.worker_id,
                    lease.token,
                ),
            ).fetchone()
        if row is None:
            return None
        return RunLease(
            run_id=lease.run_id,
            worker_id=lease.worker_id,
            token=lease.token,
            expires_at=float(row["lease_expires_epoch"]),
        )

    def release_run_lease(self, lease: RunLease) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                update runs
                set lease_owner = null, lease_token = null,
                    lease_expires_at = null, lease_heartbeat_at = null
                where id = %s and lease_owner = %s and lease_token = %s
                returning id
                """,
                (lease.run_id, lease.worker_id, lease.token),
            ).fetchone()
        return row is not None

    def save_claimed_run(self, run: RunRecord, lease: RunLease) -> RunRecord:
        payload = json.dumps(run.to_storage_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            row = connection.execute(
                """
                update runs
                set owner_id = %s, scenario = %s, seed = %s, ticks = %s,
                    status = %s, control_state = %s, error = %s,
                    updated_at = %s, payload_json = %s::jsonb
                where id = %s and lease_owner = %s and lease_token = %s
                  and lease_expires_at > current_timestamp
                  and control_state = %s
                returning id
                """,
                (
                    run.owner_id,
                    run.scenario,
                    int(run.seed),
                    int(run.ticks),
                    run.status.value,
                    run.control_state.value,
                    run.error,
                    run.updated_at,
                    payload,
                    run.id,
                    lease.worker_id,
                    lease.token,
                    run.control_state.value,
                ),
            ).fetchone()
        if row is None:
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
        incremental = _json_dict(write.incremental)
        commit = _json_dict(incremental.get("commit"))
        sequence = int(commit.get("sequence", 0) or 0)
        checksum = str(commit.get("checksum", ""))
        if sequence <= 0 or not checksum:
            raise ValueError("incremental write requires a valid TickCommit")
        with self._connect() as connection:
            if lease is not None:
                lease_row = connection.execute(
                    """
                    select status, control_state from runs where id = %s and lease_owner = %s
                      and lease_token = %s and lease_expires_at > current_timestamp
                    for update
                    """,
                    (lease.run_id, lease.worker_id, lease.token),
                ).fetchone()
                if lease_row is None:
                    raise LeaseLostError(f"run lease lost: {lease.run_id}")
            else:
                lease_row = connection.execute(
                    "select status, control_state from runs where id = %s for update",
                    (write.run.id,),
                ).fetchone()
                if lease_row is None:
                    raise KeyError(f"run not found: {write.run.id}")
            _require_progress_writable(
                str(lease_row["status"]),
                str(lease_row["control_state"]),
                write.run.id,
            )
            existing = connection.execute(
                """
                select checksum from run_tick_commits
                where run_id = %s and commit_sequence = %s
                """,
                (write.run.id, sequence),
            ).fetchone()
            if existing is not None and str(existing["checksum"]) != checksum:
                raise ValueError(f"divergent TickCommit sequence: {sequence}")
            connection.execute(
                """
                insert into run_tick_commits (
                    run_id, commit_sequence, commit_id, checksum, commit_json
                ) values (%s, %s, %s, %s, %s::jsonb)
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
                    values (%s, %s, %s, %s, %s::jsonb)
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
            trace_range = commit.get("trace_range")
            trace_start = (
                int(trace_range[0] or 0)
                if isinstance(trace_range, list) and trace_range
                else 0
            )
            for index, trace in enumerate(incremental.get("traces", []), start=1):
                if not isinstance(trace, dict):
                    continue
                connection.execute(
                    """
                    insert into run_traces (run_id, sequence, tick, kind, payload_json)
                    values (%s, %s, %s, %s, %s::jsonb)
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
            for attempt in [
                *incremental.get("provider_attempts", []),
                *write.provider_attempts,
            ]:
                if not isinstance(attempt, dict):
                    continue
                attempt_id = str(attempt.get("attempt_id", ""))
                if not attempt_id:
                    continue
                connection.execute(
                    """
                    insert into run_provider_attempts (
                        run_id, attempt_id, commit_sequence, payload_json
                    ) values (%s, %s, %s, %s::jsonb)
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
                    values (%s, %s, %s::jsonb)
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
                    values (%s, %s, %s::jsonb)
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
                    values (%s, %s, %s::jsonb)
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
                    where run_id = %s and sequence < %s
                    """,
                    (write.run.id, sequence),
                )
            row = connection.execute(
                """
                update runs set owner_id = %s, scenario = %s, seed = %s,
                    ticks = %s, status = %s, control_state = %s, error = %s,
                    updated_at = %s, payload_json = %s::jsonb
                where id = %s returning id
                """,
                (
                    write.run.owner_id,
                    write.run.scenario,
                    int(write.run.seed),
                    int(write.run.ticks),
                    write.run.status.value,
                    write.run.control_state.value,
                    write.run.error,
                    write.run.updated_at,
                    json.dumps(
                        write.run.to_live_storage_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    write.run.id,
                ),
            ).fetchone()
        if row is None:
            raise KeyError(f"run not found: {write.run.id}")
        return write.run

    def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return self._latest_json(
            "run_checkpoints", "checkpoint_json", "commit_sequence", run_id
        )

    def list_tick_commits(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        rows = self._list_json(
            "run_tick_commits", "commit_json", "commit_sequence", run_id, after, 0
        )
        return [_json_dict(row.get("commit")) for row in rows]

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json("run_events", "payload_json", "sequence", run_id, after, limit)

    def list_run_traces(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json("run_traces", "payload_json", "sequence", run_id, after, limit)

    def list_projection_deltas(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list_json("run_projection_deltas", "delta_json", "sequence", run_id, after, limit)

    def get_latest_projection(self, run_id: str) -> dict[str, Any] | None:
        return self._latest_json("run_projections", "projection_json", "sequence", run_id)

    def consume_thought_schedules(self, run_id: str, sequences: list[int]) -> int:
        wanted = {int(value) for value in sequences if int(value) > 0}
        if not wanted:
            return 0
        with self._connect() as connection:
            rows = connection.execute(
                "select sequence, delta_json from run_projection_deltas where run_id = %s",
                (run_id,),
            ).fetchall()
            consumed = 0
            for row in rows:
                delta = _json_dict(row["delta_json"])
                updated, removed = _without_thought_schedules(delta, wanted)
                if removed:
                    consumed += removed
                    connection.execute(
                        "update run_projection_deltas set delta_json = %s::jsonb where run_id = %s and sequence = %s",
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
                "select sequence, delta_json from run_projection_deltas where run_id = %s",
                (run_id,),
            ).fetchall()
            consumed = 0
            for row in rows:
                delta = _json_dict(row["delta_json"])
                updated, removed = _without_thought_occurrences(delta, wanted)
                if removed:
                    consumed += removed
                    connection.execute(
                        "update run_projection_deltas set delta_json = %s::jsonb where run_id = %s and sequence = %s",
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
                values (%s, %s::jsonb)
                on conflict(run_id) do update set result_json = excluded.result_json
                """,
                (run_id, json.dumps(result, ensure_ascii=False, sort_keys=True)),
            )

    def get_final_result(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "select result_json from run_final_results where run_id = %s",
                (run_id,),
            ).fetchone()
        return _json_dict(row["result_json"]) if row is not None else None

    def get_run_recovery_data(self, run_id: str) -> dict[str, Any]:
        checkpoint = self.get_latest_checkpoint(run_id) or {}
        checkpoint_commit = int(checkpoint.get("commit_sequence", 0) or 0)
        event_cursor = int(checkpoint.get("event_cursor", 0) or 0)
        trace_cursor = int(checkpoint.get("trace_cursor", 0) or 0)
        additions = self._list_json(
            "run_tick_commits", "commit_json", "commit_sequence", run_id, checkpoint_commit, 0
        )
        attempts = self._list_json(
            "run_provider_attempts",
            "payload_json",
            "commit_sequence",
            run_id,
            checkpoint_commit,
            0,
        )
        return {
            "checkpoint": checkpoint or None,
            "commits": [_json_dict(item.get("commit")) for item in additions],
            "events": self.list_run_events(run_id, event_cursor, 0),
            "traces": self.list_run_traces(run_id, trace_cursor, 0),
            "provider_outputs": _flatten(additions, "provider_outputs"),
            "provider_attempts": attempts,
            "provider_audits": _flatten(additions, "provider_audits"),
            "intervention_audits": _flatten(additions, "intervention_audits"),
            "memory_consolidation_report": _flatten(
                additions, "memory_consolidation"
            ),
            "sovereign_intent_audits": _flatten(
                additions, "sovereign_intent_audits"
            ),
        }

    def _list_json(
        self,
        table: str,
        column: str,
        cursor: str,
        run_id: str,
        after: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        suffix = "" if int(limit) <= 0 else " limit %s"
        parameters: tuple[object, ...] = (run_id, int(after))
        if int(limit) > 0:
            parameters = (*parameters, int(limit))
        with self._connect() as connection:
            rows = connection.execute(
                f"select {column} from {table} where run_id = %s and {cursor} > %s order by {cursor}{suffix}",
                parameters,
            ).fetchall()
        return [_json_dict(row[column]) for row in rows]

    def _latest_json(
        self, table: str, column: str, cursor: str, run_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                f"select {column} from {table} where run_id = %s order by {cursor} desc limit 1",
                (run_id,),
            ).fetchone()
        return _json_dict(row[column]) if row is not None else None

    def _connect(self) -> Any:
        return self._connection_factory()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            for statement in POSTGRES_SCHEMA_STATEMENTS:
                connection.execute(statement)

    def _seed_scenarios(self) -> None:
        with self._connect() as connection:
            for scenario in default_scenarios().values():
                connection.execute(
                    """
                    insert into scenarios (id, name, description, source, defaults_json)
                    values (%s, %s, %s, %s, %s::jsonb)
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


def _psycopg_connection_factory(dsn: str) -> ConnectionFactory:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PostgreSQL mode requires the ai-native-world-api[postgres] extra"
        ) from exc

    def connect() -> Any:
        return psycopg.connect(dsn, row_factory=dict_row)

    return connect


def _scenario_from_row(row: Any) -> ScenarioRecord:
    return ScenarioRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        source=str(row["source"]),
        defaults=_json_dict(row["defaults_json"]),
    )


def _run_from_row(row: Any) -> RunRecord:
    return RunRecord.from_storage_dict(_json_dict(row["payload_json"]))


def _run_parameters(run: RunRecord, payload: str) -> tuple[object, ...]:
    return (
        run.id,
        run.owner_id,
        run.scenario,
        int(run.seed),
        int(run.ticks),
        run.status.value,
        run.control_state.value,
        run.error,
        run.created_at,
        run.updated_at,
        payload,
    )


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        loaded = json.loads(value)
        return dict(loaded) if isinstance(loaded, dict) else {}
    return {}


def _require_progress_writable(status: str, control_state: str, run_id: str) -> None:
    if control_state != "active" or status in {"completed", "failed"}:
        raise LeaseLostError(f"run no longer accepts progress: {run_id}")


def _flatten(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [
        _json_dict(item)
        for row in rows
        for item in row.get(key, [])
        if isinstance(item, dict)
    ]


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
