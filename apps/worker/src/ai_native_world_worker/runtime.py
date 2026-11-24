"""Standalone Worker process orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Event, Lock, Thread
from time import perf_counter, sleep
from typing import Any, Mapping

from ai_native_world_engine.core import RunSession

from ai_native_world_api.repository import (
    ClaimedRunRepository,
    LeaseLostError,
    RunLease,
    RunRepository,
)
from ai_native_world_api.repository_config import create_run_repository
from ai_native_world_api.provider_config import create_runtime_provider_config

from .jobs import InProcessRunQueue, RuntimeProviderFactory


JsonDict = dict[str, Any]

WORKER_ID_ENV = "AI_NATIVE_WORLD_WORKER_ID"
WORKER_POLL_INTERVAL_ENV = "AI_NATIVE_WORLD_WORKER_POLL_INTERVAL"
WORKER_MAX_STEPS_ENV = "AI_NATIVE_WORLD_WORKER_MAX_STEPS_PER_CYCLE"
WORKER_LEASE_SECONDS_ENV = "AI_NATIVE_WORLD_WORKER_LEASE_SECONDS"
WORKER_HEARTBEAT_INTERVAL_ENV = "AI_NATIVE_WORLD_WORKER_HEARTBEAT_INTERVAL"
WORKER_SHUTDOWN_TIMEOUT_ENV = "AI_NATIVE_WORLD_WORKER_SHUTDOWN_TIMEOUT"


@dataclass(frozen=True, slots=True)
class StandaloneWorkerConfig:
    worker_id: str
    poll_interval: float = 0.6
    max_steps_per_cycle: int = 1
    lease_seconds: float = 60.0
    heartbeat_interval: float = 15.0
    shutdown_timeout: float = 30.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "StandaloneWorkerConfig":
        values = env if env is not None else os.environ
        lease_seconds = max(float(values.get(WORKER_LEASE_SECONDS_ENV, 60.0) or 60.0), 1.0)
        heartbeat_interval = max(
            float(values.get(WORKER_HEARTBEAT_INTERVAL_ENV, 15.0) or 15.0),
            0.05,
        )
        return cls(
            worker_id=str(values.get(WORKER_ID_ENV, f"worker-{os.getpid()}")),
            poll_interval=max(float(values.get(WORKER_POLL_INTERVAL_ENV, 0.6) or 0.6), 0.0),
            max_steps_per_cycle=max(int(values.get(WORKER_MAX_STEPS_ENV, 1) or 1), 1),
            lease_seconds=lease_seconds,
            heartbeat_interval=min(heartbeat_interval, lease_seconds / 2),
            shutdown_timeout=max(
                float(values.get(WORKER_SHUTDOWN_TIMEOUT_ENV, 30.0) or 30.0),
                0.0,
            ),
        )


class LeaseHeartbeat:
    def __init__(
        self,
        repository: RunRepository,
        lease: RunLease,
        lease_seconds: float,
        interval: float,
    ) -> None:
        self.repository = repository
        self._lease = lease
        self.lease_seconds = max(float(lease_seconds), 0.001)
        self.interval = max(float(interval), 0.001)
        self._stop = Event()
        self._lost = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    @property
    def lease(self) -> RunLease:
        with self._lock:
            return self._lease

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread = Thread(target=self._run, name=f"lease-heartbeat-{self._lease.run_id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.interval * 2, 0.1))

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            renewed = self.repository.renew_run_lease(self.lease, self.lease_seconds)
            if renewed is None:
                self._lost.set()
                return
            with self._lock:
                self._lease = renewed


class StandaloneWorkerRuntime:
    def __init__(
        self,
        repository: RunRepository,
        config: StandaloneWorkerConfig,
        runtime_provider_factory: RuntimeProviderFactory = create_runtime_provider_config,
    ) -> None:
        self.repository = repository
        self.config = config
        self.runtime_provider_factory = runtime_provider_factory
        self.sessions: dict[str, RunSession] = {}
        self._shutdown_requested = Event()
        self._force_cancel_requested = Event()
        self._shutdown_reason = ""
        self.queue = self._queue_for(repository)

    @property
    def accepting_claims(self) -> bool:
        return not self._shutdown_requested.is_set()

    def request_shutdown(
        self,
        reason: str = "worker shutdown requested",
        *,
        force: bool = False,
    ) -> None:
        if self._shutdown_requested.is_set() or force:
            self._force_cancel_requested.set()
        self._shutdown_reason = str(reason)
        self._shutdown_requested.set()
        for session in list(self.sessions.values()):
            if self._force_cancel_requested.is_set():
                session.request_cancel(f"worker shutdown: {reason}")
            else:
                session.request_stop(
                    f"worker shutdown: {reason}",
                    deadline_seconds=self.config.shutdown_timeout,
                )

    def close(self, reason: str = "worker runtime closed") -> None:
        for run_id, session in list(self.sessions.items()):
            if not session.terminal:
                session.request_cancel(reason)
            session.close(reason)
            self.sessions.pop(run_id, None)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "StandaloneWorkerRuntime":
        return cls(
            repository=create_run_repository(env),
            config=StandaloneWorkerConfig.from_env(env),
        )

    def run_cycle(self) -> JsonDict:
        results: list[JsonDict] = []
        recovered_run_ids: list[str] = []
        skipped_run_ids: list[str] = []
        canceled_run_ids = self._sync_persisted_controls()
        for _ in range(self.config.max_steps_per_cycle):
            if not self.accepting_claims:
                break
            lease = self.repository.claim_run(
                self.config.worker_id,
                self.config.lease_seconds,
            )
            if lease is None:
                break
            claimed_repository = ClaimedRunRepository(self.repository, lease)
            self.queue = self._queue_for(claimed_repository)
            claimed_record = self.repository.get_run(lease.run_id)
            previous_worker = ""
            if claimed_record is not None:
                previous_worker = str(claimed_record.runtime_state.get("worker_id", ""))
            recovery = self.queue.recover_pending(
                mark_running_recovery=bool(
                    previous_worker and previous_worker != self.config.worker_id
                )
            )
            recovered_run_ids.extend(str(item) for item in recovery["recovered_run_ids"])
            skipped_run_ids.extend(str(item) for item in recovery["skipped_run_ids"])
            heartbeat = LeaseHeartbeat(
                self.repository,
                lease,
                lease_seconds=self.config.lease_seconds,
                interval=self.config.heartbeat_interval,
            )
            try:
                with heartbeat:
                    result = self.queue.process_run(lease.run_id)
                    if self._shutdown_requested.is_set():
                        result = self._drain_claimed_run(
                            lease.run_id,
                            heartbeat,
                            result,
                        )
            except LeaseLostError:
                result = {
                    "status": "lease_lost",
                    "run_id": lease.run_id,
                    "worker_id": self.config.worker_id,
                }
            released = self.repository.release_run_lease(heartbeat.lease)
            result["lease_released"] = released
            results.append(result)
            if result.get("status") == "paused":
                break
            if result.get("status") == "lease_lost":
                break
        unique_recovered = list(dict.fromkeys(recovered_run_ids))
        unique_skipped = list(dict.fromkeys(skipped_run_ids))
        return {
            "worker_id": self.config.worker_id,
            "worker_mode": "standalone",
            "recovery": {
                "status": "recovered",
                "recovered_count": len(unique_recovered),
                "recovered_run_ids": unique_recovered,
                "skipped_count": len(unique_skipped),
                "skipped_run_ids": unique_skipped,
                "pending_count": 0,
            },
            "processed_count": len(results),
            "results": results,
            "pending_count": 0,
            "accepting_claims": self.accepting_claims,
            "shutdown_requested": self._shutdown_requested.is_set(),
            "canceled_run_ids": canceled_run_ids,
        }

    def _sync_persisted_controls(self) -> list[str]:
        canceled: list[str] = []
        for run_id, session in list(self.sessions.items()):
            record = self.repository.get_run(run_id)
            if record is None:
                session.request_cancel("run record removed")
                session.close("run record removed")
                self.sessions.pop(run_id, None)
                canceled.append(run_id)
                continue
            if record.control_state.value != "canceled":
                continue
            session.request_cancel("persisted run cancellation")
            session.close("persisted run cancellation")
            self.sessions.pop(run_id, None)
            canceled.append(run_id)
        return canceled

    def _drain_claimed_run(
        self,
        run_id: str,
        heartbeat: LeaseHeartbeat,
        result: JsonDict,
        deadline_at: float | None = None,
    ) -> JsonDict:
        deadline = deadline_at or (
            perf_counter() + max(float(self.config.shutdown_timeout), 0.0)
        )
        session = self.sessions.get(run_id)
        if session is not None and not session.terminal:
            session.request_stop(
                f"worker shutdown: {self._shutdown_reason or 'signal'}",
                deadline_seconds=max(deadline - perf_counter(), 0.0),
            )
        while (
            session is not None
            and not session.terminal
            and not heartbeat.lost
            and perf_counter() < deadline
            and not self._force_cancel_requested.is_set()
        ):
            result = self.queue.process_run(run_id)
            session = self.sessions.get(run_id)
        if session is not None and not session.terminal:
            session.request_cancel(
                f"worker shutdown: {self._shutdown_reason or 'deadline exceeded'}"
            )
            session.close("worker shutdown cancellation")
            self.sessions.pop(run_id, None)
        elif session is not None:
            session.close("worker shutdown drained")
            self.sessions.pop(run_id, None)
        return result

    def _drain_shutdown_sessions(self) -> list[JsonDict]:
        """Reclaim only already-owned Runs and persist their graceful stop."""

        results: list[JsonDict] = []
        deadline = perf_counter() + max(float(self.config.shutdown_timeout), 0.0)
        while self.sessions and perf_counter() < deadline:
            lease = self.repository.claim_run(
                self.config.worker_id,
                self.config.lease_seconds,
            )
            if lease is None:
                break
            if lease.run_id not in self.sessions:
                self.repository.release_run_lease(lease)
                break
            claimed_repository = ClaimedRunRepository(self.repository, lease)
            self.queue = self._queue_for(claimed_repository)
            self.queue.recover_pending(mark_running_recovery=False)
            heartbeat = LeaseHeartbeat(
                self.repository,
                lease,
                lease_seconds=self.config.lease_seconds,
                interval=self.config.heartbeat_interval,
            )
            try:
                with heartbeat:
                    result = self._drain_claimed_run(
                        lease.run_id,
                        heartbeat,
                        {
                            "status": "worker_shutdown_draining",
                            "run_id": lease.run_id,
                        },
                        deadline_at=deadline,
                    )
            except LeaseLostError:
                session = self.sessions.pop(lease.run_id, None)
                if session is not None:
                    session.request_cancel("worker shutdown lease lost")
                    session.close("worker shutdown lease lost")
                result = {
                    "status": "lease_lost",
                    "run_id": lease.run_id,
                    "worker_id": self.config.worker_id,
                }
            result["lease_released"] = self.repository.release_run_lease(
                heartbeat.lease
            )
            results.append(result)
        return results

    def _queue_for(self, repository: RunRepository) -> InProcessRunQueue:
        return InProcessRunQueue(
            repository,
            auto_drain=False,
            cooperative_ticks=True,
            worker_id=self.config.worker_id,
            worker_mode="standalone",
            sessions=self.sessions,
            runtime_provider_factory=self.runtime_provider_factory,
        )

    def run(self, max_cycles: int | None = None) -> list[JsonDict]:
        cycles: list[JsonDict] = []
        cycle_index = 0
        while (
            not self._shutdown_requested.is_set()
            and (max_cycles is None or cycle_index < max(int(max_cycles), 0))
        ):
            result = self.run_cycle()
            cycles.append(result)
            cycle_index += 1
            if result["processed_count"] == 0 and (max_cycles is None or cycle_index < max_cycles):
                sleep(self.config.poll_interval)
        if self._shutdown_requested.is_set():
            shutdown_results = self._drain_shutdown_sessions()
            if shutdown_results:
                cycles.append(
                    {
                        "worker_id": self.config.worker_id,
                        "worker_mode": "standalone",
                        "shutdown_drain": True,
                        "processed_count": len(shutdown_results),
                        "results": shutdown_results,
                        "pending_count": 0,
                        "accepting_claims": False,
                        "shutdown_requested": True,
                    }
                )
            self.close("worker shutdown complete")
        return cycles
