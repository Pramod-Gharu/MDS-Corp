#!/usr/bin/env python3
"""Auto-assign a dedicated agent whenever a task file is added or updated."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from mds_tasklib import assign_task, find_repo_root, load_task  # noqa: E402


def emit(context: str = "") -> int:
    if context:
        json.dump({"additional_context": context}, sys.stdout)
    else:
        json.dump({}, sys.stdout)
    return 0


def task_id_from_path(root: Path, file_path: str) -> str | None:
    try:
        rel = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "tasks" and parts[-1] == "TASK.md":
        if parts[1] not in {"_template"}:
            return parts[1]
    return None


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        root = find_repo_root(ROOT)
    except FileNotFoundError:
        return emit()

    file_path = payload.get("file_path")
    if not file_path:
        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("path") or tool_input.get("file_path")
    if not file_path:
        return emit()

    task_id = task_id_from_path(root, file_path)
    if not task_id:
        return emit()

    try:
        before = load_task(root, task_id)
        had_agent = bool((before.get("agent") or {}).get("agent_id"))
        task = assign_task(root, task_id, reassign=False)
    except Exception as exc:  # noqa: BLE001
        return emit(
            "Task isolation could not auto-assign an agent: "
            f"{exc}. Fix this task's allowed_paths so they do not overlap another task."
        )

    agent = task.get("agent") or {}
    action = "refreshed" if had_agent else "assigned"
    return emit(
        f"Task `{task['id']}` {action} isolated agent `{agent.get('agent_id')} ` "
        f"on branch `{agent.get('branch')}` with worktree `{agent.get('worktree_rel')}`.\n"
        "If you are the orchestrator, launch a dedicated worker for this task only, "
        "inside that worktree. Do not give it files from any other task.\n"
        "If you are already a worker, ignore this unless it is your own task."
    )


if __name__ == "__main__":
    raise SystemExit(main())
