#!/usr/bin/env python3
"""Compute a parallel-execution schedule for a plan.

Reads every task-meta block in a plan, builds the dependency DAG, and
partitions tasks into topological *layers*: layer 0 is every task with no
dependencies; layer N is every task whose dependencies are all satisfied by
layers < N. Tasks in the same layer have no ordering constraint, so a
dispatcher may run them in parallel.

It then verifies that no two tasks in the same layer declare the same path in
`touches` — that would be a write-collision and makes the layer unsafe to
parallelize.

Usage:
    python scripts/harness/plan_schedule.py <plan.md>

Exit codes:
    0 - a clean, collision-free schedule was printed to stdout
    1 - schema error, dependency cycle, or a touches-collision within a layer
    2 - usage error (wrong arguments / plan file does not exist)
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import SchemaError, TaskMeta, parse_plan


def compute_layers(tasks: list[TaskMeta]) -> list[list[str]]:
    """Partition task ids into topological layers (Kahn's algorithm, by level)."""
    by_id = {t.id: t for t in tasks}
    done: set[str] = set()
    remaining = set(by_id)
    layers: list[list[str]] = []
    while remaining:
        layer = sorted(
            tid for tid in remaining
            if all(dep in done for dep in by_id[tid].depends)
        )
        if not layer:
            # parse_plan already rejects cycles; this is a defensive guard.
            raise SchemaError(f"unresolved dependencies among {sorted(remaining)}")
        layers.append(layer)
        done.update(layer)
        remaining.difference_update(layer)
    return layers


def find_collisions(
    tasks: list[TaskMeta], layers: list[list[str]]
) -> list[tuple[int, str, str, str]]:
    """Return (layer_index, path, first_task, second_task) for each same-layer clash."""
    by_id = {t.id: t for t in tasks}
    collisions: list[tuple[int, str, str, str]] = []
    for index, layer in enumerate(layers):
        owner: dict[str, str] = {}
        for tid in layer:
            for path in by_id[tid].touches:
                if path in owner:
                    collisions.append((index, path, owner[path], tid))
                else:
                    owner[path] = tid
    return collisions


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: plan_schedule.py <plan.md>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    if not plan_path.exists():
        print(f"error: {plan_path} does not exist", file=sys.stderr)
        return 2
    try:
        tasks = parse_plan(plan_path)
        layers = compute_layers(tasks)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for index, layer in enumerate(layers):
        tag = " (parallel)" if len(layer) > 1 else ""
        print(f"Layer {index}{tag}: {', '.join(layer)}")

    collisions = find_collisions(tasks, layers)
    if collisions:
        for index, path, first, second in collisions:
            print(
                f"COLLISION: layer {index} — {first} and {second} both touch {path}",
                file=sys.stderr,
            )
        return 1

    print(
        f"OK: {len(tasks)} task(s) across {len(layers)} layer(s), no collisions",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
