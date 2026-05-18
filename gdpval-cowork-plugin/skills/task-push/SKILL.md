---
name: task-push
description: Push a completed evaluation task and its related files (reference, ground truth, report) to GitHub on a dedicated task branch and open a pull request.
user-invocable: true
disable-model-invocation: false
---

# Task Push

Commits and pushes a task directory to a dedicated branch on GitHub and opens a pull request. Never commits to `main` or any existing base branch.

## Steps

### 1. Identify the task

If a task was just worked on in this conversation, use that. Otherwise list available tasks:
```bash
ls tasks/
```
If more than one exists and context is unclear, ask: "Which task should I push?"

### 2. Pre-push checklist

Verify the task is ready to push. Check all of the following and report any issues to the user before continuing:

**Score check** — confirm a passing (< 0.8 average) main task score exists in logs:
```bash
python3 -c "
import json, glob, os
task_name = '<name>'
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime, reverse=True)
for path in logs:
    try:
        log = json.load(open(path))
        task = log.get('eval', {}).get('task', '')
        if task_name in task and not task.endswith('_ground_truth'):
            score = log['results']['scores'][0]['metrics']['mean']['value']
            model = log.get('eval', {}).get('model', 'unknown')
            print(f'score={score:.3f} model={model}')
            break
    except Exception:
        pass
"
```

If no main task log exists, warn: "No evaluation run found for this task. Run `/task-run` before pushing."
If the score is ≥ 0.8, warn: "Latest score is X.XX — models may be solving this too easily. Consider running `/difficulty-calibration` first. Proceed anyway? (yes/no)"

**Required files** — confirm `task.py`, `Dockerfile`, and `compose.yaml` exist:
```bash
ls tasks/<name>/task.py tasks/<name>/Dockerfile tasks/<name>/compose.yaml
```

**Report check** — check if a final report exists:
```bash
ls tasks/<name>/final-report/report.md 2>/dev/null && echo "found" || echo "missing"
```
If missing, suggest: "No final report found. Run `/final-report` to generate one before pushing, or continue without it."
Wait for the user's answer if it's missing.

**Git remote** — confirm a remote is configured:
```bash
git remote -v
```
If no remote is found, stop and tell the user: "No git remote is configured. Add one with `git remote add origin <url>` and try again."

### 3. Check current branch and status

```bash
git branch --show-current
git status --short
```

If there are uncommitted changes **outside** `tasks/<name>/`, warn the user:
"There are uncommitted changes outside the task directory. I'll only stage files inside `tasks/<name>/` — other changes will remain unstaged."

Never switch away from or reset the user's current working state.

### 4. Create the task branch

Branch name: `task/<name>`

Check if it already exists:
```bash
git branch --list "task/<name>"
git branch --list -r "origin/task/<name>"
```

- If the branch does **not** exist locally or remotely: create it from the current `HEAD` of `main` (or `master` if main doesn't exist):
  ```bash
  git fetch origin
  git checkout -b task/<name> origin/main
  ```
  If `origin/main` doesn't exist, try `origin/master`:
  ```bash
  git checkout -b task/<name> origin/master
  ```

- If the branch already exists locally: check it out and pull latest:
  ```bash
  git checkout task/<name>
  git pull origin task/<name> --ff-only
  ```
  If fast-forward fails, stop and ask the user how to proceed — do not force-reset.

- If the branch exists only on remote: check it out tracking the remote:
  ```bash
  git checkout -b task/<name> origin/task/<name>
  ```

After checkout, confirm the current branch is `task/<name>` and is **not** `main` or `master`:
```bash
git branch --show-current
```
If somehow on main or master, stop immediately: "Safety check failed — refusing to commit to main/master."

### 5. Stage task files

Stage only files within the task directory. Explicitly exclude the `logs/` directory:
```bash
git add tasks/<name>/
```

Check what will be committed:
```bash
git status --short tasks/<name>/
```

Show the user the list of files to be committed and ask for confirmation:
"I'm about to commit these files to branch `task/<name>`. Proceed? (yes/no)"

### 6. Commit

Write a commit message that includes:
- Task name
- Score from the latest main task run
- Whether ground truth and a final report are included

```bash
git commit -m "$(cat <<'EOF'
Add task: <name>

Score: X.XX (latest main task run, <model>)
Includes: task.py, Dockerfile, compose.yaml[, ground truth][, reference files][, final report]

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

If the commit fails (e.g. pre-commit hook), report the error to the user and do not retry automatically.

### 7. Push

```bash
git push -u origin task/<name>
```

If the push is rejected (non-fast-forward), do **not** force-push. Report to the user:
"Push was rejected — the remote branch has commits not present locally. Pull first (`git pull origin task/<name>`) and try again."

### 8. Open a pull request

Check if `gh` CLI is available:
```bash
which gh
```

If available, open a PR targeting `main` (or `master`):

```bash
gh pr create \
  --title "Task: <name>" \
  --base main \
  --head task/<name> \
  --body "$(cat <<'EOF'
## Evaluation Task: <name>

**Latest score:** X.XX (<model>)

### Contents
- `task.py` — main evaluation task with Docker sandbox
- `Dockerfile` + `compose.yaml` — sandbox environment
- `reference/` — reference files for the agent (if present)
- `ground_truth/` — human baseline outputs (if present)
- `task_ground_truth.py` — ground truth scorer (if present)
- `final-report/report.md` — evaluation report (if present)

### Rubric summary
<list each criterion and point value from RUBRIC_JSON in task.py>

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
EOF
)"
```

If `gh` is not available or the user prefers not to open a PR, print the push URL and branch name instead so the user can open a PR manually.

### 9. Confirm

Tell the user:
- Branch pushed: `task/<name>`
- PR URL (if created)
- "Run `/final-report` if you haven't already to generate a full evaluation summary."

Return to the original branch the user was on before this skill ran:
```bash
git checkout <original-branch>
```
