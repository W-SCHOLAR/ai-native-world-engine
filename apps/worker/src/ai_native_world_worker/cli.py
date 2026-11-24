"""Command-line entry point for the standalone Worker."""

from __future__ import annotations

import argparse
import json
import signal
from typing import Mapping, Sequence

from .runtime import StandaloneWorkerConfig, StandaloneWorkerRuntime


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    defaults = StandaloneWorkerConfig.from_env(environ)
    parser = argparse.ArgumentParser(prog="ai-native-world-worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--poll-interval", type=float, default=defaults.poll_interval)
    parser.add_argument("--max-steps-per-cycle", type=int, default=defaults.max_steps_per_cycle)
    parser.add_argument("--worker-id", default=defaults.worker_id)
    parser.add_argument("--lease-seconds", type=float, default=defaults.lease_seconds)
    parser.add_argument("--heartbeat-interval", type=float, default=defaults.heartbeat_interval)
    parser.add_argument("--shutdown-timeout", type=float, default=defaults.shutdown_timeout)
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = StandaloneWorkerConfig(
        worker_id=str(args.worker_id),
        poll_interval=max(float(args.poll_interval), 0.0),
        max_steps_per_cycle=max(int(args.max_steps_per_cycle), 1),
        lease_seconds=max(float(args.lease_seconds), 1.0),
        heartbeat_interval=max(
            min(float(args.heartbeat_interval), max(float(args.lease_seconds), 1.0) / 2),
            0.05,
        ),
        shutdown_timeout=max(float(args.shutdown_timeout), 0.0),
    )
    runtime = StandaloneWorkerRuntime.from_env(environ)
    runtime.config = config
    signal_count = 0

    def request_shutdown(signum: int, _frame: object) -> None:
        nonlocal signal_count
        signal_count += 1
        runtime.request_shutdown(
            signal.Signals(signum).name,
            force=signal_count > 1,
        )

    previous_handlers = {
        signal_name: signal.getsignal(signal_name)
        for signal_name in (signal.SIGTERM, signal.SIGINT)
    }
    for signal_name in previous_handlers:
        signal.signal(signal_name, request_shutdown)
    max_cycles = 1 if args.once else args.max_cycles
    try:
        for cycle in runtime.run(max_cycles=max_cycles):
            print(json.dumps(cycle, ensure_ascii=False, sort_keys=True))
    finally:
        runtime.close("worker CLI exit")
        for signal_name, previous in previous_handlers.items():
            signal.signal(signal_name, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
