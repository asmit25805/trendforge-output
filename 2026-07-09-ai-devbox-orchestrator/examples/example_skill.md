---
name: hello_world
description: Simple skill that prints a greeting and lists environment variables.
user_invocable: true
script_path: hello_world.sh
metadata:
  tags: [demo, hello]
  version: "1.0"
  box_spec:
    image: python:3.12-slim
    env:
      GREETING: "Hello from devbox"
    ports: [8080]
    volumes:
      - ["./data", "/app/data"]
    resources:
      cpu: "0.5"
      memory: "256m"
---

# Hello World Skill

This skill demonstrates a minimal, self‑contained dev box. When invoked the container runs `hello_world.sh`, which prints a greeting, shows the injected environment variable, and lists files under `/app/data`. The skill is fully declarative; the orchestrator will provision a Docker container based on the `box_spec`, mount the `data` directory, and expose port 8080 for any future service.

```sh
#!/bin/sh
echo "$GREETING"
echo "Listing /app/data:"
ls -la /app/data
```

Running the skill via the CLI:

```bash
ai-devbox-orchestrator skill run hello_world
```

Expected output (truncated):

```
Hello from devbox
Listing /app/data:
total 0
drwxr-xr-x 1 root root 0 Jan 01 00:00 .
drwxr-xr-x 1 root root 0 Jan 01 00:00 ..
```

The orchestrator will write a `RESULT.md` containing the execution result and append an entry to `LOG.md` for later reasoning.