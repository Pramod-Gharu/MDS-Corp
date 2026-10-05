---
id: example-task
title: Example isolated task
status: pending
allowed_paths:
  - path/to/exclusive-file.php
---

# Example isolated task

Replace this file by running:

```bash
./scripts/mds-task add your-task-id --title "Your title" --path "your/exclusive/path"
```

Work only inside `allowed_paths` and `tasks/<id>/`. Do not edit other tasks.
