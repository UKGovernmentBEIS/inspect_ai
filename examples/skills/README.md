# Agent Skills Example

This example demonstrates how to use the `skill()` tool to provide specialized instructions and scripts to agents for Linux system exploration tasks.

## Overview

Agent skills are structured packages of instructions, scripts, and reference materials that agents can invoke on-demand. When an agent encounters a task that matches a skill's description, it can invoke the skill to receive detailed guidance.

Each skill consists of:
- **SKILL.md**: Instructions with YAML frontmatter (name, description) and markdown body
- **scripts/**: Optional executable scripts the agent can run
- **references/**: Optional additional documentation
- **assets/**: Optional static resources (templates, data files)

## Skills Included

This example includes three Linux system exploration skills:

| Skill | Description |
|-------|-------------|
| `system-info` | Get OS, kernel, CPU, and memory information |
| `network-info` | Explore network interfaces, routes, and DNS configuration |
| `disk-usage` | Analyze disk space and filesystem usage |

Each skill includes a helper bash script that provides structured output.

## Running the Example

```bash
# Run with default model
inspect eval examples/skills/task.py --model openai/gpt-4o

# Run with a specific sample
inspect eval examples/skills/task.py --model openai/gpt-4o --limit 1
```

The evaluation runs in a Docker container (Ubuntu 24.04) where the agent can execute system commands.

## How It Works

1. The `skill()` tool registers available skills with the agent
2. When the agent receives a task, it can invoke a skill by name
3. The skill returns instructions and the path to any scripts
4. The agent follows the instructions and uses `bash()` to execute commands
5. Skills are installed into the sandbox at `./skills/<skill-name>/`

## Creating Your Own Skills

To create a new skill:

1. Create a directory with your skill name (lowercase, hyphens allowed):
   ```
   my-skill/
   ├── SKILL.md
   └── scripts/
       └── helper.sh
   ```

2. Add YAML frontmatter to SKILL.md:
   ```markdown
   ---
   name: my-skill
   description: Brief description of what this skill does
   ---

   # My Skill

   Instructions for using this skill...
   ```

3. Add the skill to your task:
   ```python
   from inspect_ai.tool import skill

   skill(skills=[Path("path/to/my-skill")])
   ```

## Skill Specification

Skills follow the [Agent Skills Specification](https://agentskills.io/specification). Key requirements:

- **name**: Lowercase letters, numbers, and hyphens (max 64 chars)
- **description**: What the skill does and when to use it (max 1024 chars)
- **instructions**: Step-by-step guidance in the markdown body

Optional frontmatter fields:
- `license`: License identifier
- `compatibility`: Environment requirements
- `metadata`: Custom key-value data
- `allowed-tools`: Pre-approved tools for the skill
