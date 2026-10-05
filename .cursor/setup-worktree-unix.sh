#!/bin/sh
set -eu

mkdir -p .mds
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
case "$branch" in
  task/*)
    echo "${branch#task/}" > .mds/current-task
    ;;
esac

if [ -n "${ROOT_WORKTREE_PATH:-}" ] && [ -f "$ROOT_WORKTREE_PATH/.env.example" ] && [ ! -f .env.example ]; then
  cp "$ROOT_WORKTREE_PATH/.env.example" .env.example
fi
