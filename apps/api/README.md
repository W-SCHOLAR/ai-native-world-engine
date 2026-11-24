# AI Native World API

Minimal commercial API skeleton for the AI native world engine.

This app owns product-facing HTTP boundaries, request DTOs, run orchestration,
and persistence adapters. The engine remains in `src/ai_native_world_engine`
for this phase and is called only through application services.

FastAPI is an application dependency, not an engine dependency. The modules in
this skeleton keep FastAPI imports optional so core service tests can run before
the API dependency set is installed.

## Install and build

The API is an independent Python distribution and declares its Engine
dependency. Monorepo development resolves Engine through `tool.uv.sources`;
published wheel metadata keeps the versioned package requirement.

```bash
uv sync --project apps/api
uv build --wheel apps/api
```

The Worker integration is optional at API import time. Installing only Engine
and API still supports synchronous runs and repository/service usage; a Worker
package is required for cooperative queued execution.

Worker ownership is configured with
`AI_NATIVE_WORLD_WORKER_MODE=embedded|external|disabled`. Embedded is the local
demo default. External mode persists queued work for a separately started
`ai-native-world-worker` process using the same durable repository.

## User sessions and Run ownership

All product users have the same interaction capabilities. Authentication does
not introduce viewer, operator, or sovereign roles: every user can create,
inspect, control, advance, intervene in, and submit sovereign intent to runs
they own. Run ownership prevents one user from reading or mutating another
user's world.

- `AI_NATIVE_WORLD_AUTH_MODE=disabled|session`
- `AI_NATIVE_WORLD_SESSION_SECRET=<at-least-32-byte-secret>` in session mode
- `AI_NATIVE_WORLD_SESSION_TTL_SECONDS=86400`

Disabled mode is the local default and assigns all work to the stable `local`
owner. Hosted deployments use session mode. `POST /api/sessions` issues an
expiring signed anonymous bearer token; `GET /api/scenarios`, API docs, and the
session endpoint remain public. All Run routes require
`Authorization: Bearer <token>` in session mode.

The API never stores raw bearer tokens. The Web client requests and reuses an
anonymous session automatically after its first 401 response. Production
deployments must use TLS and a randomly generated signing secret.

## Persistence adapters

The product API currently ships four repository adapters:

- `InMemoryRunRepository` for fast tests and ephemeral demos.
- `JsonFileRunRepository` for dependency-light local persistence.
- `SQLiteRunRepository` for embedded database persistence using Python's
  standard `sqlite3` module.
- `PostgresRunRepository` for production JSONB persistence and atomic Worker
  leases. Install it with `uv sync --project apps/api --extra postgres`.

The SQLite adapter stores scenario rows, run summary columns, and the full
JSON-compatible `RunRecord` payload so timeline frames, status events,
scorecards, projections, and provider audits survive process restarts.

## Runtime repository configuration

`create_app()` selects the product runtime repository from environment
variables. SQLite is the default so local API runs are durable without an
external database service.

- `AI_NATIVE_WORLD_REPOSITORY=sqlite|memory|json|postgres`
- `AI_NATIVE_WORLD_DATA_DIR=.data`
- `AI_NATIVE_WORLD_SQLITE_PATH=.data/ai-native-world.sqlite3`
- `AI_NATIVE_WORLD_JSON_DATA_DIR=.data/json-repository`
- `AI_NATIVE_WORLD_DATABASE_URL=postgresql://...` in PostgreSQL mode

Use `AI_NATIVE_WORLD_REPOSITORY=memory` for ephemeral demos and tests. Use
`json` only when a human-readable local repository is useful. Redis is not used
as the run record source of truth.

PostgreSQL is the production multi-process mode. It stores complete Run
records in JSONB, keeps indexed owner/status/control/timestamp columns, and
coordinates Workers with skip-locked claims, expiring leases, heartbeat
renewal, and fencing tokens. SQLite remains the local default and uses atomic
lease transactions for local Worker coordination.

## Runtime provider configuration

Product runs use deterministic scheduler providers by default. To let the
enterprise scheduler use DeepSeek-backed JSON LLM providers, configure:

- `AI_NATIVE_WORLD_PROVIDER=deterministic|deepseek`
- `DEEPSEEK_API_KEY=<secret>`
- `AI_NATIVE_WORLD_DEEPSEEK_MODEL=deepseek-v4-flash`
- `AI_NATIVE_WORLD_DEEPSEEK_BASE_URL=https://api.deepseek.com`
- `AI_NATIVE_WORLD_DEEPSEEK_TIMEOUT=60`
- `AI_NATIVE_WORLD_DEEPSEEK_TEMPERATURE=0.2`
- `AI_NATIVE_WORLD_DEEPSEEK_MAX_ATTEMPTS=1` (local live-debug runs may raise this to `3` for boundary repair)
- `AI_NATIVE_WORLD_LOG_LLM_RESPONSES=1` to log parsed model JSON responses for local debugging

Only non-secret provider metadata is stored in run config. API keys stay in the
API or worker process environment.

## Sovereign intent compiler configuration

Product sovereign intent ingress always uses the Engine
`SovereignIntentCompiler`. Deterministic mode is the offline default; DeepSeek
mode swaps in the real JSON model client while preserving the same effect
allowlist and declarative dynamic-rule normalization.

- `AI_NATIVE_WORLD_SOVEREIGN_COMPILER=deterministic|deepseek`
- `AI_NATIVE_WORLD_SOVEREIGN_MODEL=deepseek-v4-flash`
- `AI_NATIVE_WORLD_SOVEREIGN_BASE_URL=https://api.deepseek.com`
- `AI_NATIVE_WORLD_SOVEREIGN_TIMEOUT=60`
- `AI_NATIVE_WORLD_SOVEREIGN_TEMPERATURE=0.2`
- `DEEPSEEK_API_KEY=<secret>` when DeepSeek mode is selected

Compiler metadata is persisted, but API keys are never stored in run records.
