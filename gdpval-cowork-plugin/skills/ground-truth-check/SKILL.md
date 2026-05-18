---
name: ground-truth-check
description: Score the ground truth file against the task rubric, diagnose failures, and iteratively fix rubric criteria or the ground truth file until the score reaches 0.8. Run after task-init when a ground truth file exists.
user-invocable: true
disable-model-invocation: false
---

# Ground Truth Check

Validates that the human-created ground truth achieves ≥ 0.8 against the task rubric before running the full evaluation. Helps diagnose and fix mismatches between the rubric and the actual deliverable.

The user can type **"skip"** at any point to stop and proceed to `/task-run` instead.

## Steps

### 1. Identify the task

If a task was just created in this conversation, use that. Otherwise list available tasks:
```bash
ls tasks/
```
If more than one exists and context is unclear, ask which task to check.

Check that the ground truth file exists:
```bash
ls tasks/<name>/task_ground_truth.py
ls tasks/<name>/ground_truth/
```

If neither exists, tell the user: "No ground truth found for this task. Run `/task-run` to evaluate the main task directly."

### 2. Choose a scoring model

Default: `anthropic/claude-sonnet-4-6`

Ask: "Which model should I use to score the ground truth? Default is claude-sonnet-4-6 — press enter to accept or name another."

The user may name one or more models. If multiple, run each and average the scores.

### 3. Run the ground truth eval

```bash
inspect eval tasks/<name>/task_ground_truth.py --model <provider/model> --log-format json --log-dir ./logs
```

Extract the score:
```bash
python3 -c "
import json, glob, os
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
log = json.load(open(logs[-1]))
print(log['results']['scores'][0]['metrics']['mean']['value'])
"
```

Extract only the failing criteria:
```bash
python3 -c "
import json, glob, os
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
log = json.load(open(logs[-1]))
samples = log.get('samples', [])
if samples:
    explanation = list(samples[0]['scores'].values())[0].get('explanation', '')
    for line in explanation.split('\n'):
        if line.startswith('[✗'):
            print(line)
"
```

### 4. If score ≥ 0.8

Tell the user: "Ground truth scores X.XX — the rubric is well-calibrated. Run `/task-run` to evaluate LLM performance on the main task."

Stop here.

### 5. If score < 0.8 — diagnose failures

Show the failing criteria to the user. For each failing criterion, determine whether the failure is due to:

**A — Rubric mismatch**: The criterion is checking for something the ground truth file genuinely does not contain (wrong quote, wrong label, version mismatch). Fix: update the criterion in `tasks/<name>/task.py`.

**B — Extraction gap**: The ground truth file likely does contain this, but plain text extraction is losing structural information (e.g. bold, list markers, line spacing). These are expected limitations — note them as "scoring ceiling" items rather than fixable issues.

**C — Genuine gap in the ground truth**: The criterion is valid and verifiable, but the human deliverable actually doesn't meet it. Fix: ask the user to update the ground truth file.

Present your diagnosis to the user as a grouped list:
```
Rubric mismatches to fix in task.py:
  - [criterion text] → suggested fix

Extraction limitations (expected ceiling):
  - [criterion text] — cannot be verified from text

Ground truth gaps (ask user to update the file):
  - [criterion text]
```

Ask the user to confirm before making any changes.

### 6. Apply fixes

**For rubric mismatches** (type A): Edit `tasks/<name>/task.py` directly — update the `criterion` text in `RUBRIC_JSON` to match what is actually in the ground truth file.

**For extraction limitations** (type B): Do not edit anything. Note the expected ceiling score and ask the user whether it's acceptable (e.g. "Structural checks account for X pts. Maximum achievable score from text is Y.YY. Is that acceptable to proceed?"). If yes, treat as passing.

**For ground truth gaps** (type C): Ask the user to update their ground truth file and re-copy it:
```bash
cp "<updated_local_path>" tasks/<name>/ground_truth/<filename>
```
Wait for confirmation before re-running.

### 7. Re-run and loop

After fixes are applied, go back to Step 3 and re-run the eval. Continue until:
- Score ≥ 0.8 (or user accepts the ceiling score) → suggest `/task-run`
- User types "skip" → suggest `/task-run`
- No more fixable failures remain → explain the ceiling and suggest `/task-run`
