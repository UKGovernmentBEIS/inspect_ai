---
name: secret-code
description: Retrieve a secret code by reading a bundled asset file and executing a companion script. Use when the user asks to reveal, decode, or look up the secret code from this skill's assets.
---

# Secret Code Skill

Reveals the secret code by reading the asset and running the bundled script.

## Workflow

1. Read the contents of `assets/secret.txt` and report the value to the user.
2. Execute `bash scripts/reveal.sh` to retrieve the complete answer.

Both steps are required — the asset provides partial context and the script provides the full code.
