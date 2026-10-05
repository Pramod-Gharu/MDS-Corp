# Tasks

Each folder here is one isolated job with one agent.

- Add: `./scripts/mds-task add <id> --title "..." --path "exclusive/path"`
- List: `./scripts/mds-task list`
- Remove: `./scripts/mds-task remove <id>` (only that agent’s worktree and branch)

Do not overlap `allowed_paths` with another task. See [docs/AGENTS.md](../docs/AGENTS.md).
