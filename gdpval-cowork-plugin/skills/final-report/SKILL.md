---
name: final-report
description: Compose a markdown evaluation report for a task, using either the latest log results or fresh re-runs. Saves to tasks/<name>/final-report/report.md.
user-invocable: true
disable-model-invocation: false
---

# Final Report

Composes a structured evaluation report from ground truth and main task results, and saves it to `tasks/<name>/final-report/report.md`.

## Steps

### 1. Identify the task

If a task was just worked on in this conversation, use that. Otherwise list available tasks:
```bash
ls tasks/
```
If more than one exists and context is unclear, ask which task to report on.

### 2. Discover available log files

Scan the logs directory for runs belonging to this task. Logs are matched by filename patterns containing the task name (both main task and ground truth):

```bash
ls -lt logs/*.json 2>/dev/null | head -40
```

Then filter relevant logs:
```bash
python3 -c "
import json, glob, os
task_name = '<name>'
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
for path in logs:
    try:
        log = json.load(open(path))
        task = log.get('eval', {}).get('task', '')
        if task_name in task:
            ts = log.get('eval', {}).get('created', 'unknown')
            model = log.get('eval', {}).get('model', 'unknown')
            score = log['results']['scores'][0]['metrics']['mean']['value']
            print(f'{os.path.basename(path)} | task={task} | model={model} | score={score:.3f} | created={ts}')
    except Exception:
        pass
"
```

Tell the user which runs were found (task name, model, score, timestamp). Group them into **main task** runs and **ground truth** runs (ground truth logs have task names ending in `_ground_truth`).

### 3. Ask what to use as inputs

Ask the user:
> "I found the following runs for **<name>**:
>
> Main task runs: [list]
> Ground truth runs: [list or 'none found']
>
> Would you like to:
> A. Use the latest log results (no re-run)
> B. Re-run the main task before reporting
> C. Re-run the ground truth before reporting
> D. Re-run both before reporting"

Accept any combination. If the user chooses to re-run anything, follow the same procedure as `/task-run` for that subset (confirm models, run sequentially, collect scores). Then proceed to report generation with the freshest logs available.

If no logs exist at all, inform the user: "No evaluation logs found for this task. Run `/task-run` first, then come back to generate the report."

### 4. Parse results from logs

For each relevant log file (newest per task+model combination), extract:

```bash
python3 -c "
import json, glob, os
task_name = '<name>'
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
results = []
for path in logs:
    try:
        log = json.load(open(path))
        task = log.get('eval', {}).get('task', '')
        if task_name not in task:
            continue
        model = log.get('eval', {}).get('model', 'unknown')
        score = log['results']['scores'][0]['metrics']['mean']['value']
        samples = log.get('samples', [])
        failing = []
        if samples:
            explanation = list(samples[0]['scores'].values())[0].get('explanation', '')
            for line in explanation.split('\n'):
                if line.startswith('[✗'):
                    failing.append(line)
        results.append({
            'task': task,
            'model': model,
            'score': score,
            'failing': failing,
            'created': log.get('eval', {}).get('created', ''),
        })
        print(json.dumps(results[-1]))
    except Exception as e:
        pass
"
```

Deduplicate: if the same model ran multiple times for the same task variant, keep only the most recent (logs are sorted by mtime, so the last match wins).

### 5. Compute summary statistics

From the parsed results:

- **Main task scores**: all entries where task does NOT end in `_ground_truth`
- **Ground truth scores**: all entries where task ends in `_ground_truth`
- Average main task score = mean of main task model scores
- Average ground truth score = mean of ground truth model scores
- Score gap = ground truth average − main task average (positive means humans outperform LLMs)
- Models used for main task: list
- Models used for ground truth: list

### 6. Write the report

Create the output directory and write the report:

```bash
mkdir -p tasks/<name>/final-report
```

Write `tasks/<name>/final-report/report.md` using this structure:

```markdown
# Evaluation Report: <task display name>

**Task:** `<name>`
**Generated:** <current date>

---

## Summary

| Metric | Value |
|--------|-------|
| Main task average score | X.XX |
| Ground truth average score | X.XX (or N/A) |
| Score gap (human − LLM) | +X.XX (or N/A) |
| Main task runs | N (models: ...) |
| Ground truth runs | N (models: ...) (or N/A) |

---

## Main Task Results

| Model | Score |
|-------|-------|
| claude-sonnet-4-6 | 0.XX |
| gpt-4o | 0.XX |
| ... | ... |
| **Average** | **0.XX** |

### Failing Checks by Model

**claude-sonnet-4-6**
- [✗ 0/N] <criterion>
- ...

**gpt-4o**
- [✗ 0/N] <criterion>
- ...

---

## Ground Truth Results

*(Include this section only if ground truth runs exist.)*

| Model | Score |
|-------|-------|
| claude-sonnet-4-6 | 0.XX |
| **Average** | **0.XX** |

### Failing Checks

**claude-sonnet-4-6**
- [✗ 0/N] <criterion>
- ...

---

## Score Gap Analysis

*(Include only if both main task and ground truth scores are available.)*

The ground truth (human baseline) scored **X.XX** on average, compared to **X.XX** for LLMs — a gap of **+X.XX**.

Criteria met by humans but missed by all LLMs:
- <criterion> — missed by all N models

Criteria missed by both humans and LLMs (potential rubric/extraction issue):
- <criterion>
```

Fill in all values from the parsed results. For the gap analysis:
- "Missed by all LLMs" = failing for every main task model but not failing in ground truth
- "Missed by both" = failing in both ground truth and at least one main task model

### 7. Confirm

Tell the user: "Report saved to `tasks/<name>/final-report/report.md`." Print the full report content so the user can review it inline.
