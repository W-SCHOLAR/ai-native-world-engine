# AI Native World Web

TypeScript + React product frontend skeleton.

The viewer consumes backend projection data by default. It does not own the
authoritative world state and does not reimplement engine rules in the browser.

`src/features/viewer/InteractiveGlobeViewer.tsx` is the React runtime migrated
from the legacy static Canvas viewer. The old static viewer now lives at
`examples/earth-viewer-static` and is kept only as a migration fallback.

## Browser E2E

The process-level browser test starts Vite, FastAPI in authenticated external
Worker mode, and a standalone Worker against an isolated temporary SQLite
database. It verifies the default Engine-backed Tribe Survival journey,
automatic anonymous sessions, pause/resume and Sovereign Intent before Worker
execution, cross-session Run isolation, retained cursor expiration, and
observational GET behavior.

Prerequisites:

```bash
uv sync --project apps/api
npm install
```

Run with Node 18 or newer:

```bash
npm run test:e2e
```

The harness uses `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` when configured, system
Google Chrome on macOS when available, and otherwise Playwright Chromium. CI
without a browser should run `npx playwright install chromium` first.

## Regression ceilings

The Python release suite runs a 96-tick Tribe Survival cooperative session and
requires exactly 64 retained frames. Timeline JSON must stay below 8,000,000
bytes and stream JSON below 8,500,000 bytes. The primary raw production
JavaScript asset must stay below 300,000 bytes. The lazy Three.js world-book
renderer is isolated from that primary asset and must stay below 650,000 raw
bytes. Intentional threshold changes must be reviewed with the corresponding
OpenSpec change.
