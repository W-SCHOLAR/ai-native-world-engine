#!/usr/bin/env python3
"""Start the focused Planet-and-Tribe Web demo with an embedded Worker."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
API_PYTHON = ROOT / "apps" / "api" / ".venv" / "bin" / "python"


def main() -> int:
    python = Path(os.environ.get("AI_NATIVE_WORLD_DEV_PYTHON", API_PYTHON))
    if not python.exists():
        raise SystemExit(
            "API environment is missing. Run `uv sync --project apps/api`, then retry."
        )
    node = _compatible_node()
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.exists():
        raise SystemExit("Web dependencies are missing. Run `npm install` in apps/web, then retry.")

    python_paths = [
        ROOT / "src",
        ROOT / "apps" / "api" / "src",
        ROOT / "apps" / "worker" / "src",
    ]
    environment = os.environ.copy()
    _load_local_env(environment)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        [*(str(path) for path in python_paths), *([existing_pythonpath] if existing_pythonpath else [])]
    )
    environment.setdefault("AI_NATIVE_WORLD_REPOSITORY", "sqlite")
    environment.setdefault("AI_NATIVE_WORLD_SQLITE_PATH", str(ROOT / ".data" / "demo.sqlite3"))
    environment.setdefault("AI_NATIVE_WORLD_WORKER_MODE", "embedded")
    environment.setdefault("AI_NATIVE_WORLD_PROVIDER", "deepseek")
    environment.setdefault("AI_NATIVE_WORLD_DEEPSEEK_MODEL", "deepseek-v4-flash")
    environment.setdefault("AI_NATIVE_WORLD_LOG_LLM_RESPONSES", "1")
    if environment.get("DEEPSEEK_API_KEY"):
        # This is only a non-secret UX hint consumed by Vite. The key itself
        # stays server-side and is never exposed to the Web bundle.
        environment.setdefault("VITE_AI_NATIVE_WORLD_SERVER_PROVIDER_KEY", "1")

    api_environment = environment
    # Vite must not inherit server credentials. Only VITE_* values are needed
    # by client tooling, and the server-key flag above is intentionally a
    # non-secret capability hint.
    web_environment = {
        key: value
        for key, value in environment.items()
        if key.startswith("VITE_")
        or key in {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "NODE_OPTIONS"}
    }
    processes = [
        subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                "ai_native_world_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=ROOT,
            env=api_environment,
        ),
        subprocess.Popen(
            [str(node), str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
            cwd=WEB,
            env=web_environment,
        ),
    ]

    stopping = False

    def stop_children(*_: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop_children)
    signal.signal(signal.SIGTERM, stop_children)
    print("Demo starting: http://127.0.0.1:5173")
    print("Runtime health: http://127.0.0.1:8000/api/health")

    try:
        while not stopping:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    stop_children()
                    return return_code
            time.sleep(0.2)
    finally:
        stop_children()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


def _compatible_node() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("AI_NATIVE_WORLD_DEV_NODE")
    if configured:
        candidates.append(Path(configured))
    active = shutil.which("node")
    if active:
        candidates.append(Path(active))
    candidates.extend(Path.home().glob(".nvm/versions/node/v*/bin/node"))

    compatible: list[tuple[tuple[int, int, int], Path]] = []
    for candidate in candidates:
        if not candidate.exists():
            continue
        result = subprocess.run(
            [str(candidate), "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        version = _parse_node_version(result.stdout.strip())
        if version and version[0] >= 18:
            compatible.append((version, candidate))
    if not compatible:
        raise SystemExit(
            "Node.js 18 or newer is required. Set AI_NATIVE_WORLD_DEV_NODE to a compatible binary."
        )
    return max(compatible, key=lambda item: item[0])[1]


def _load_local_env(environment: dict[str, str]) -> None:
    """Load ignored local development variables without overriding the shell."""

    env_file = ROOT / ".env.local"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator:
            continue
        name = name.strip()
        if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        environment.setdefault(name, value)


def _parse_node_version(value: str) -> tuple[int, int, int] | None:
    try:
        major, minor, patch = value.removeprefix("v").split(".", 2)
        return int(major), int(minor), int(patch)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
