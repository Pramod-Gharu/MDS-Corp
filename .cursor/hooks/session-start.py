#!/usr/bin/env python3
"""Bind this Cursor session to one isolated task, or to the orchestrator role."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from mds_tasklib import detect_task_id, find_repo_root, load_task, session_context  # noqa: E402


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        root = find_repo_root(Path(payload.get("cwd") or ROOT))
    except FileNotFoundError:
        root = ROOT
    cwd = payload.get("cwd") or str(root)
    if payload.get("workspace_roots"):
        cwd = payload["workspace_roots"][0]
    task_id = detect_task_id(root, cwd=cwd)
    task = load_task(root, task_id) if task_id else None
    env = {"MDS_ROLE": "worker" if task else "orchestrator"}
    if task:
        env["MDS_TASK_ID"] = task["id"]
        agent_id = (task.get("agent") or {}).get("agent_id")
        if agent_id:
            env["MDS_AGENT_ID"] = agent_id
    json.dump({"env": env, "additional_context": session_context(root, task)}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
