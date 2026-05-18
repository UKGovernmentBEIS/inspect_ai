---
name: task-run
description: Run an inspect_ai evaluation task against multiple LLMs, report per-model scores, and suggest next steps based on average score.
user-invocable: true
disable-model-invocation: false
---

# Run Inspect AI Evaluation Task

Runs a task from `tasks/` against multiple LLMs and reports scores.

## Steps

### 1. Identify the task

If a task was just created in this conversation, use that directory. Otherwise list available tasks:
```bash
ls tasks/
```
Each task is a subdirectory. If there is more than one and context is unclear, ask: "Which task should I run?"

### 2. Choose what to run

Check whether a ground truth file exists for the identified task:
```bash
ls tasks/<name>/task_ground_truth.py
```

- If **only `task.py` exists**: proceed with the main task only, no need to ask.
- If **both exist** and ground truth was **already run during `/ground-truth-check` in this conversation**: default to running only the main task. Tell the user: "Ground truth was already scored during `/ground-truth-check`. I'll run the main task only — let me know if you'd like to run ground truth again too."
- If **both exist** and ground truth has **not been run in this conversation**: ask the user: "I found both `task.py` and `task_ground_truth.py` in `tasks/<name>/`. Would you like to run the main task, the ground truth, or both?"

If the user explicitly asks to run both at any point, honor that regardless.

When both are selected: run main task first, then ground truth — each gets its own full model loop and results table.

### 3. Confirm models

Default models:
- `anthropic/claude-sonnet-4-6`
- `openai/gpt-4o`
- `google/gemini-2.0-flash`

Ask the user: "I'll run the evaluation against these 3 models by default. Would you like to change this — swap a model, add more, or run against just one?"

Adjust the list based on their answer before proceeding.

### 4. Run evaluations

For each model, run sequentially. Announce each model before starting it.

```bash
inspect eval tasks/<name>/task.py --model <provider/model> --log-format json --log-dir ./logs
```

For ground truth:
```bash
inspect eval tasks/<name>/task_ground_truth.py --model <provider/model> --log-format json --log-dir ./logs
```

Provider prefixes:
- Anthropic: `anthropic/claude-sonnet-4-6`
- OpenAI: `openai/gpt-4o`
- Google: `google/gemini-2.0-flash`

After each run, extract the score from the newest log file:
```bash
python3 -c "
import json, glob, os
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
log = json.load(open(logs[-1]))
print(log['results']['scores'][0]['metrics']['mean']['value'])
"
```

### 5. Display results

Show a summary table once all models have run. If both main and ground truth were run, show them separately:

```
Main task — <name>
Model                      Score
──────────────────────────────────
claude-sonnet-4-6          0.72
gpt-4o                     0.85
gemini-2.0-flash           0.68
──────────────────────────────────
Average                    0.75

Ground truth — <name>
Model                      Score
──────────────────────────────────
claude-sonnet-4-6          0.91
──────────────────────────────────
Average                    0.91
```

### 6. Suggest next steps

Calculate the average score across all models for the main task.

- If average **< 0.8**: "Average score is X.XX — the task looks appropriately challenging. Run `/final-report` to generate a full evaluation report, or `/task-push` to submit it."
- If average **≥ 0.8**: "Average score is X.XX — models are solving this too easily. Run `/difficulty-calibration` to analyse what's too easy and make targeted changes before pushing."
