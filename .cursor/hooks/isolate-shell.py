#!/usr/bin/env python3
"""Stop worker agents from touching other tasks through the shell."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from mds_tasklib import (  # noqa: E402
    dangerous_shell_command,
    detect_task_id,
    find_repo_root,
    load_task,
)


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        root = find_repo_root(ROOT)
    except FileNotFoundError:
        json.dump({"permission": "allow"}, sys.stdout)
        return 0
    cwd = payload.get("cwd") or str(root)
    task_id = detect_task_id(root, cwd=cwd)
    task = None
    if task_id:
        try:
            task = load_task(root, task_id)
        except FileNotFoundError:
            task = None
    reason = dangerous_shell_command(root, task, payload.get("command") or "")
    if reason:
        json.dump(
            {
                "permission": "deny",
                "user_message": reason,
                "agent_message": reason,
            },
            sys.stdout,
        )
        return 0
    json.dump({"permission": "allow"}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
