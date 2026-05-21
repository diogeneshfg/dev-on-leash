---
name: execute-plan-task
description: Use to execute a single task from a plan (docs/plans/*.md). Reads the task's task-meta block, runs its verify command, and ticks the first checkbox of the task on success.
---

# execute-plan-task

## When to use

The user references a specific task in an existing plan and wants it executed mechanically — for example: "run T05 from the execution-harness plan". Use only when the plan + task id are known. Do NOT use to plan or design new work.

## How

1. Resolve the plan file under `docs/plans/<file>.md`.
2. Invoke the harness runner:

   ```bash
   python scripts/harness/run_task.py docs/plans/<file>.md <task_id>
   ```

3. The runner executes the task's `verify:` command and exits 0 if green. On exit 0, the first `- [ ]` checkbox of the task is replaced with `- [x]` in the plan file.

4. If `verify` fails (exit 1), DO NOT tick the checkbox by hand. Diagnose the failure, fix the underlying issue, re-run the skill.

5. If exit 2 (task id not found / usage error), the plan file or id is wrong — re-check the input.

## Constraints

- Never edit the plan file directly to tick checkboxes — only the runner is allowed to write to it. Manual ticks bypass the gate.
- Never pass `--force` or any flag to skip verify. The whole point is verify cannot be bypassed.
- If the verify command times out or hangs, investigate — it should be a fast, targeted command. Slow verify is a smell.
