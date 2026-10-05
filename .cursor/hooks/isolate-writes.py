#!/usr/bin/env python3
"""Block worker agents from writing files owned by other tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from mds_tasklib import (  # noqa: E402
    detect_task_id,
    extract_tool_paths,
    find_repo_root,
    is_write_allowed,
    load_task,
)

WRITE_TOOLS = {"Write", "StrReplace", "Delete", "EditNotebook"}


def deny(message: str) -> int:
    json.dump(
        {
            "permission": "deny",
            "user_message": message,
            "agent_message": message,
        },
        sys.stdout,
    )
    return 0


def allow() -> int:
    json.dump({"permission": "allow"}, sys.stdout)
    return 0


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        root = find_repo_root(ROOT)
    except FileNotFoundError:
        return allow()
    cwd = payload.get("cwd") or str(root)
    if payload.get("workspace_roots"):
        cwd = payload["workspace_roots"][0]
    task_id = detect_task_id(root, cwd=cwd)
    if not task_id:
        return allow()
    tool = payload.get("tool_name") or ""
    if tool not in WRITE_TOOLS:
        return allow()
    try:
        task = load_task(root, task_id)
    except FileNotFoundError:
        return deny(f"This session is bound to missing task '{task_id}'.")
    for path in extract_tool_paths(payload.get("tool_input") or {}):
        ok, reason = is_write_allowed(root, task, path)
        if not ok:
            return deny(reason)
    return allow()


if __name__ == "__main__":
    raise SystemExit(main())
