# Agents

MDS-Corp is **agent-based**. The main checkout is the orchestrator. Each piece of work is a separate task with its own agent, git branch, and worktree.

Adding or deleting one agent must not change another agent’s files, branch, or worktree.

## Roles

| Role | Where | What it does |
|---|---|---|
| Orchestrator | Main folder (`MDS-Corp`) | Creates/removes tasks, assigns agents, launches workers. Does not implement site work. |
| Worker | `.worktrees/<task-id>/` | Implements only that task, inside exclusive `allowed_paths`. |

## Add a task (new agent)

From the project root:

```bash
./scripts/mds-task add homepage-hero \
  --title "Homepage hero" \
  --path "wp-content/themes/mds/front-page.php" \
  --body "Update the homepage hero only."
```

Repeat `--path` for more exclusive files. Paths must not overlap another task.

This creates:

- `tasks/homepage-hero/TASK.md` — brief
- `tasks/homepage-hero/agent.json` — agent id, branch, worktree
- Branch `task/homepage-hero`
- Worktree `.worktrees/homepage-hero/` (gitignored)

Then open a Cursor agent **in that worktree**, not in the main folder.

## List / show / remove

```bash
./scripts/mds-task list
./scripts/mds-task show homepage-hero
./scripts/mds-task remove homepage-hero
```

`remove` deletes only that task’s folder, worktree, and branch. Other agents stay as they are.

## Isolation rules

- One agent owns one task.
- `allowed_paths` cannot overlap.
- Workers cannot write `.cursor/` or `scripts/`.
- Workers cannot write `tasks/<other-id>/`.
- Hooks block cross-task edits in Cursor.

## Template

Copy from `tasks/_template/TASK.md` or use `mds-task add`.
