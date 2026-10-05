# MDS-Corp agents

This project uses **one agent per task**.

- **Orchestrator** (this checkout): add/remove tasks with `./scripts/mds-task`. Do not implement WordPress or page work here.
- **Worker**: runs in `.worktrees/<task-id>/` and may edit only that task’s `allowed_paths` plus `tasks/<task-id>/`.

Full guide: [docs/AGENTS.md](docs/AGENTS.md)

```bash
./scripts/mds-task add <id> --title "..." --path "exclusive/file"
./scripts/mds-task list
./scripts/mds-task remove <id>
```

Removing one task does not affect other agents.
