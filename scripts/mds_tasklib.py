#!/usr/bin/env python3
"""Isolated per-task agent registry for the MDS-Corp WordPress project."""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

TASKS_DIR = "tasks"
WORKTREES_DIR = ".worktrees"
CURRENT_TASK_FILE = ".mds/current-task"
AGENT_FILE = "agent.json"
TASK_FILE = "TASK.md"
RESERVED_IDS = {"_template", "README"}

# Worker agents may always write inside their own task folder.
# They must never write other task folders, isolation tooling, or git metadata.
PROTECTED_PREFIXES = (
    ".cursor/",
    "scripts/",
    ".git/",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def find_repo_root(start: Optional[Path] = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "scripts" / "mds_tasklib.py").exists():
            return candidate
        if (candidate / ".git").exists() and (candidate / "tasks").exists():
            return candidate
    raise FileNotFoundError("Could not find the MDS-Corp project root.")


def rel_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "task"


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for raw_line in parts[1].splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\s+-\s+", line) and current_key:
            item = line.strip()[2:].strip().strip('"').strip("'")
            existing = data.get(current_key)
            if not isinstance(existing, list):
                data[current_key] = [] if existing in (None, "") else [existing]
            data[current_key].append(item)
            continue
        match = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        current_key = key
        if value == "":
            data[key] = []
        elif value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
        else:
            data[key] = value.strip('"').strip("'")
    return data, parts[2].lstrip("\n")


def dump_frontmatter(meta: Dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


def task_dir(root: Path, task_id: str) -> Path:
    return root / TASKS_DIR / task_id


def load_task(root: Path, task_id: str) -> Dict[str, Any]:
    folder = task_dir(root, task_id)
    md_path = folder / TASK_FILE
    if not md_path.exists():
        raise FileNotFoundError(f"Task '{task_id}' is missing {TASK_FILE}.")
    meta, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    agent_path = folder / AGENT_FILE
    agent = {}
    if agent_path.exists():
        agent = json.loads(agent_path.read_text(encoding="utf-8"))
    allowed = meta.get("allowed_paths") or agent.get("allowed_paths") or []
    if isinstance(allowed, str):
        allowed = [allowed]
    return {
        "id": str(meta.get("id") or task_id),
        "title": str(meta.get("title") or task_id),
        "status": str(meta.get("status") or agent.get("status") or "pending"),
        "allowed_paths": [str(p) for p in allowed],
        "body": body,
        "meta": meta,
        "agent": agent,
        "path": str(md_path),
    }


def list_task_ids(root: Path) -> List[str]:
    base = root / TASKS_DIR
    if not base.exists():
        return []
    ids = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name not in RESERVED_IDS and (child / TASK_FILE).exists():
            ids.append(child.name)
    return ids


def load_all_tasks(root: Path) -> List[Dict[str, Any]]:
    return [load_task(root, task_id) for task_id in list_task_ids(root)]


def path_matches(rel: str, pattern: str) -> bool:
    rel_n = rel.replace("\\", "/").lstrip("./")
    pat = pattern.replace("\\", "/").lstrip("./")
    if pat.endswith("/**"):
        prefix = pat[:-3].rstrip("/")
        return rel_n == prefix or rel_n.startswith(prefix + "/")
    if pat.endswith("/"):
        return rel_n.startswith(pat)
    if any(ch in pat for ch in "*?[]"):
        return fnmatch.fnmatch(rel_n, pat) or fnmatch.fnmatch(rel_n, pat.rstrip("/"))
    return rel_n == pat or rel_n.startswith(pat + "/")


def paths_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    left_list = list(left)
    right_list = list(right)
    for a in left_list:
        for b in right_list:
            if path_matches(a, b) or path_matches(b, a):
                return True
    return False


def overlapping_tasks(root: Path, task_id: str, allowed_paths: Iterable[str]) -> List[str]:
    hits = []
    for other in load_all_tasks(root):
        if other["id"] == task_id:
            continue
        other_paths = other.get("agent", {}).get("allowed_paths") or other.get("allowed_paths") or []
        if paths_overlap(allowed_paths, other_paths):
            hits.append(other["id"])
    return hits


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def git_available(root: Path) -> bool:
    return (root / ".git").exists() or git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def current_branch(root: Path) -> str:
    result = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return (result.stdout or "").strip()


def has_commit(root: Path) -> bool:
    return git(root, "rev-parse", "HEAD", check=False).returncode == 0


def write_current_task_marker(worktree: Path, task_id: str) -> None:
    marker = worktree / CURRENT_TASK_FILE
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(task_id + "\n", encoding="utf-8")


def ensure_worktree(root: Path, task: Dict[str, Any]) -> Optional[str]:
    if not git_available(root) or not has_commit(root):
        return None
    branch = task["agent"]["branch"]
    worktree = root / task["agent"]["worktree_rel"]
    listed = git(root, "worktree", "list", "--porcelain", check=False).stdout
    if str(worktree) in listed or f"[{branch}]" in listed:
        if worktree.exists():
            write_current_task_marker(worktree, task["id"])
        return str(worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch_exists = git(root, "show-ref", "--verify", f"refs/heads/{branch}", check=False).returncode == 0
    if branch_exists:
        git(root, "worktree", "add", str(worktree), branch)
    else:
        git(root, "worktree", "add", "-b", branch, str(worktree))
    write_current_task_marker(worktree, task["id"])
    return str(worktree)


def remove_worktree(root: Path, task: Dict[str, Any]) -> None:
    if not git_available(root):
        return
    worktree = root / task.get("agent", {}).get("worktree_rel", f"{WORKTREES_DIR}/{task['id']}")
    branch = task.get("agent", {}).get("branch", f"task/{task['id']}")
    if worktree.exists():
        git(root, "worktree", "remove", "--force", str(worktree), check=False)
    git(root, "worktree", "prune", check=False)
    git(root, "branch", "-D", branch, check=False)


def new_agent_id(task_id: str, previous: Optional[str] = None) -> str:
    suffix = uuid.uuid4().hex[:6]
    if previous:
        return f"agent-{task_id}-{suffix}"
    return f"agent-{task_id}"


def assign_task(root: Path, task_id: str, reassign: bool = False) -> Dict[str, Any]:
    task = load_task(root, task_id)
    allowed = task["allowed_paths"]
    if not allowed:
        raise ValueError(f"Task '{task_id}' has no allowed_paths. Isolation requires an exclusive file list.")
    conflicts = overlapping_tasks(root, task_id, allowed)
    if conflicts:
        raise ValueError(
            f"Task '{task_id}' overlaps allowed_paths with: {', '.join(conflicts)}. "
            "Each task must own exclusive files so agents cannot harm each other."
        )
    existing = task.get("agent") or {}
    if existing.get("agent_id") and not reassign:
        existing["allowed_paths"] = allowed
        existing["updated_at"] = utc_now()
        (task_dir(root, task_id) / AGENT_FILE).write_text(
            json.dumps(existing, indent=2) + "\n", encoding="utf-8"
        )
        task["agent"] = existing
        ensure_worktree(root, task)
        return task

    agent = {
        "task_id": task_id,
        "agent_id": new_agent_id(task_id, existing.get("agent_id") if reassign else None),
        "branch": existing.get("branch") or f"task/{task_id}",
        "worktree_rel": existing.get("worktree_rel") or f"{WORKTREES_DIR}/{task_id}",
        "allowed_paths": allowed,
        "status": "assigned",
        "assigned_at": utc_now(),
    }
    if reassign and existing.get("agent_id"):
        agent["replaced_agent_id"] = existing["agent_id"]
    (task_dir(root, task_id) / AGENT_FILE).write_text(
        json.dumps(agent, indent=2) + "\n", encoding="utf-8"
    )
    meta = task["meta"]
    meta["id"] = task_id
    meta["status"] = meta.get("status") or "pending"
    meta["agent_id"] = agent["agent_id"]
    (task_dir(root, task_id) / TASK_FILE).write_text(
        dump_frontmatter(meta, task["body"]), encoding="utf-8"
    )
    task["agent"] = agent
    ensure_worktree(root, task)
    return load_task(root, task_id)


def add_task(
    root: Path,
    task_id: str,
    title: str,
    allowed_paths: List[str],
    body: str = "",
) -> Dict[str, Any]:
    task_id = slugify(task_id)
    if task_id in RESERVED_IDS:
        raise ValueError(f"'{task_id}' is reserved.")
    folder = task_dir(root, task_id)
    if folder.exists():
        raise FileExistsError(f"Task '{task_id}' already exists.")
    conflicts = overlapping_tasks(root, task_id, allowed_paths)
    if conflicts:
        raise ValueError(
            f"New task '{task_id}' overlaps allowed_paths with: {', '.join(conflicts)}."
        )
    folder.mkdir(parents=True, exist_ok=True)
    body = body.strip() or (
        f"# {title}\n\nWork only inside this task's allowed paths. "
        "Do not edit other tasks, agents, or shared isolation files.\n"
    )
    meta = {
        "id": task_id,
        "title": title,
        "status": "pending",
        "allowed_paths": allowed_paths,
    }
    (folder / TASK_FILE).write_text(dump_frontmatter(meta, body + "\n"), encoding="utf-8")
    return assign_task(root, task_id)


def remove_task(root: Path, task_id: str) -> None:
    if task_id not in list_task_ids(root):
        raise FileNotFoundError(f"Task '{task_id}' does not exist.")
    task = load_task(root, task_id)
    remove_worktree(root, task)
    folder = task_dir(root, task_id)
    for child in sorted(folder.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    if folder.exists():
        folder.rmdir()


def sync_assignments(root: Path) -> List[Dict[str, Any]]:
    synced = []
    for task_id in list_task_ids(root):
        synced.append(assign_task(root, task_id, reassign=False))
    return synced


def detect_task_id(root: Path, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    env = env or os.environ
    if env.get("MDS_TASK_ID"):
        return env["MDS_TASK_ID"]
    cwd_path = Path(cwd or os.getcwd()).resolve()
    marker = cwd_path / CURRENT_TASK_FILE
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip()
    rel = rel_posix(root, cwd_path)
    match = re.match(rf"{re.escape(WORKTREES_DIR)}/([^/]+)", rel)
    if match and match.group(1) in list_task_ids(root):
        return match.group(1)
    branch = current_branch(cwd_path if (cwd_path / ".git").exists() else root)
    if branch.startswith("task/"):
        candidate = branch[len("task/") :]
        if candidate in list_task_ids(root):
            return candidate
    return None


def extract_tool_paths(tool_input: Any) -> List[str]:
    if not isinstance(tool_input, dict):
        return []
    paths = []
    for key in ("path", "file_path", "target_notebook"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    return paths


def is_write_allowed(root: Path, task: Dict[str, Any], abs_path: str) -> Tuple[bool, str]:
    path = Path(abs_path)
    rel = rel_posix(root, path)
    if rel.startswith("tasks/") and not rel.startswith(f"tasks/{task['id']}/"):
        return False, f"Workers cannot change another task's files ({rel})."
    if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return False, f"Workers cannot change isolation or shared tooling files ({rel})."
    own_task_prefix = f"tasks/{task['id']}/"
    if rel.startswith(own_task_prefix) or rel == own_task_prefix.rstrip("/"):
        return True, ""
    allowed = task.get("agent", {}).get("allowed_paths") or task.get("allowed_paths") or []
    for pattern in allowed:
        if path_matches(rel, pattern):
            return True, ""
    return False, (
        f"Path '{rel}' is outside task '{task['id']}' allowed_paths: "
        + ", ".join(allowed)
    )


def dangerous_shell_command(root: Path, task: Optional[Dict[str, Any]], command: str) -> Optional[str]:
    compact = " ".join(command.split())
    lowered = compact.lower()
    other_ids = [tid for tid in list_task_ids(root) if not task or tid != task["id"]]
    for other in other_ids:
        if f".worktrees/{other}" in compact or f"tasks/{other}" in compact:
            return f"This command references another task ({other}) and is blocked."
        if f"task/{other}" in compact and any(
            token in lowered for token in ("worktree remove", "branch -d", "branch -d", "reset --hard")
        ):
            return f"This command would affect another task branch ({other}) and is blocked."
    if task:
        if re.search(r"\bgit\s+push\s+.*--force", lowered):
            return "Force-push is blocked for worker agents."
        if "mds-task remove" in lowered and task["id"] not in compact:
            return "Worker agents cannot remove other tasks."
    return None


def session_context(root: Path, task: Optional[Dict[str, Any]]) -> str:
    if not task:
        pending = []
        for item in load_all_tasks(root):
            agent = item.get("agent") or {}
            pending.append(
                f"- {item['id']}: agent `{agent.get('agent_id') or 'unassigned'}` "
                f"(status {item['status']})"
            )
        extra = "\n".join(pending) or "- none yet"
        return (
            "You are the MDS-Corp orchestrator in the main checkout.\n"
            "When a new task is added, assign a dedicated agent and launch it in that "
            "task's git worktree only. Never implement WordPress work yourself.\n"
            "Never edit one task's files while servicing another.\n"
            f"Current tasks:\n{extra}\n"
        )
    agent = task.get("agent") or {}
    paths = "\n".join(f"- {p}" for p in (agent.get("allowed_paths") or task["allowed_paths"]))
    return (
        f"You are worker agent `{agent.get('agent_id') or 'unassigned'}` "
        f"for isolated task `{task['id']}`: {task['title']}.\n"
        "Work only in this task. Do not read other agents' plans to copy their work, "
        "and do not edit files owned by any other task.\n"
        f"Allowed write paths:\n{paths}\n"
        f"Own task folder: tasks/{task['id']}/\n"
        "If a change needs files outside this list, stop and report the gap. "
        "Do not expand your scope.\n"
    )
