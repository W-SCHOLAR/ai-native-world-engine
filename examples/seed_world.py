"""运行确定性种子场景并打印快照、事件和追踪。"""

from __future__ import annotations

import json

from ai_native_world_engine import World


def main() -> None:
    world = World.scenario("seed", seed=7)
    for _ in range(3):
        world.step()
    print(json.dumps(world.snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

