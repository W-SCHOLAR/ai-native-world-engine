# AI Native World Worker

Minimal worker skeleton for commercial run execution.

The worker is responsible for long-running simulations, batch experiments,
projection generation, and export jobs. This phase uses an in-process job
runner so the product boundary is testable before choosing Celery, RQ, Arq, or
Temporal.

`InProcessRunQueue.recover_pending()` can rebuild pending jobs from persisted
queued/running run records after a process restart and records an audit event
when a previously running record is re-queued.

## Install and build

The Worker is an independent Python distribution. Its current in-process
runtime declares both Engine and API because it reuses run models,
repositories, provider configuration, and scenario defaults.

```bash
uv sync --project apps/worker
uv build --wheel apps/worker
```

For production PostgreSQL deployments, install
`uv sync --project apps/worker --extra postgres`.

The later independent Worker milestone can replace this in-process dependency
boundary without changing the Engine wheel.

## Standalone process

The installed package exposes a cooperative Worker process:

```bash
ai-native-world-worker --worker-id worker-local-1
```

It uses the same repository environment variables as the API. For a separate
API/Worker deployment, configure both processes with the same SQLite path and
set the API to external mode:

```bash
AI_NATIVE_WORLD_REPOSITORY=sqlite
AI_NATIVE_WORLD_SQLITE_PATH=.data/ai-native-world.sqlite3
AI_NATIVE_WORLD_WORKER_MODE=external
```

Worker controls:

- `AI_NATIVE_WORLD_WORKER_ID`
- `AI_NATIVE_WORLD_WORKER_POLL_INTERVAL`
- `AI_NATIVE_WORLD_WORKER_MAX_STEPS_PER_CYCLE`
- `AI_NATIVE_WORLD_WORKER_LEASE_SECONDS`
- `AI_NATIVE_WORLD_WORKER_HEARTBEAT_INTERVAL`
- `AI_NATIVE_WORLD_WORKER_SHUTDOWN_TIMEOUT`
- `--once`, `--max-cycles`, `--poll-interval`, `--max-steps-per-cycle`
- `--lease-seconds`, `--heartbeat-interval`, `--shutdown-timeout`

Each standalone step atomically claims one Run, heartbeats the expiring lease,
and writes through a fencing token. PostgreSQL uses `FOR UPDATE SKIP LOCKED` so
replicas can claim different Runs. SQLite uses `BEGIN IMMEDIATE` for local
multi-process coordination. JSON repository leases are process-local and must
not be used as a production multi-Worker source of truth.

The runtime retains one live `RunSession` per claimed Run across ordinary
cycles, so an in-flight Provider Future is not reconstructed on every poll.
`SIGTERM` or `SIGINT` stops new claims, drains already-owned work up to the
shutdown timeout, persists the stopped checkpoint, closes the scheduler, and
releases the lease. A second signal requests cooperative cancellation. A new
Worker resumes checkpoints stopped by this shutdown path.
