---
name: difficulty-calibration
description: Analyse the latest main task run, diagnose why models scored too high, suggest targeted changes to make the task harder, then re-run and loop until the average score drops below 0.8.
user-invocable: true
disable-model-invocation: false
---

# Difficulty Calibration

Helps bring a task's average LLM score below 0.8 by analysing passing criteria and proposing targeted changes to the task, prompt, or rubric.

## Steps

### 1. Identify the task

If a task was just worked on in this conversation, use that. Otherwise list available tasks:
```bash
ls tasks/
```
If more than one exists and context is unclear, ask which task to calibrate.

### 2. Load the latest main task results

Find the most recent log for the main task (not `_ground_truth`):

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
            model = log.get('eval', {}).get('model', 'unknown')
            score = log['results']['scores'][0]['metrics']['mean']['value']
            samples = log.get('samples', [])
            explanation = ''
            if samples:
                explanation = list(samples[0]['scores'].values())[0].get('explanation', '')
            print(f'FILE:{path}')
            print(f'MODEL:{model}')
            print(f'SCORE:{score}')
            print('EXPLANATION:')
            print(explanation)
            break
    except Exception:
        pass
"
```

If no main task log exists: "No main task run found. Run `/task-run` first."

If the score is already below 0.8: "Latest score is X.XX — the task is already at the right difficulty level. Run `/task-run` for a full multi-model evaluation, or `/final-report` for a summary."

### 3. Gather all recent model results

Collect scores and per-criterion results across all models that have run this task:

```bash
python3 -c "
import json, glob, os
task_name = '<name>'
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
seen = {}
for path in logs:
    try:
        log = json.load(open(path))
        task = log.get('eval', {}).get('task', '')
        if task_name not in task or task.endswith('_ground_truth'):
            continue
        model = log.get('eval', {}).get('model', 'unknown')
        score = log['results']['scores'][0]['metrics']['mean']['value']
        samples = log.get('samples', [])
        explanation = ''
        if samples:
            explanation = list(samples[0]['scores'].values())[0].get('explanation', '')
        seen[model] = {'score': score, 'explanation': explanation}
    except Exception:
        pass
for model, data in seen.items():
    print(f'--- {model} (score={data[\"score\"]:.3f}) ---')
    print(data['explanation'])
"
```

### 4. Diagnose what models are passing

Read `tasks/<name>/task.py` to understand the current prompt and rubric.

For each criterion marked `[✓ ...]` across ALL models (universally passing), note it as a candidate for hardening. Group the diagnosis:

**Universally passing criteria** (all models pass — easiest targets for hardening):
- List each criterion text and point value

**Partially passing criteria** (some models pass, some fail — may already be well-calibrated):
- List each with which models pass/fail

**Prompt characteristics that reduce difficulty**:
- Is the task scope too narrow? (e.g., "write a one-page summary" vs. a complex multi-section deliverable)
- Are formatting requirements underspecified? (e.g., no required structure, no length constraints)
- Does the rubric reward easily guessable defaults? (e.g., "includes an introduction" — every document has one)
- Is the task domain too generic? (models likely have extensive training data for it)

### 5. Propose specific changes

Present a numbered list of concrete, targeted suggestions. For each:
- State **what to change** (prompt wording, rubric criterion, or both)
- State **why it raises difficulty** (what model behaviour it would need to exhibit that it currently doesn't)
- Rate the expected impact: **High / Medium / Low**

Lean toward changes that are **verifiable** (can still be checked by the rubric) rather than open-ended quality upgrades (which are hard to score consistently). Good levers:

**Prompt changes that raise difficulty:**
- Add domain-specific constraints (e.g., specific methodology, terminology, regulatory framework the model must correctly apply)
- Require synthesising or reconciling conflicting information from reference files
- Add structural requirements with precise specifications (e.g., "exactly 3 sections", "table with 5 columns containing X, Y, Z, W, V")
- Require calculations or numerical reasoning (e.g., derive a specific figure from provided data)
- Introduce an adversarial element: one reference file contains an error the model must identify
- Increase ambiguity in inputs so the model must make a defensible judgment call and justify it

**Rubric changes that raise difficulty:**
- Replace broad pass/fail criteria with specific verifiable details already present in ground truth
- Add criteria for elements models commonly skip (e.g., executive summary, risk register, specific appendix)
- Increase point weight on the hardest criteria to shift the scoring distribution

Ask the user: "Here are my suggestions — which would you like to apply? You can pick one or more, make your own changes, or describe a different direction."

### 6. Apply changes

**If the user wants you to apply the changes directly:**
Edit `tasks/<name>/task.py` — update `PROMPT` and/or `RUBRIC_JSON` as agreed.

Also update `task_ground_truth.py` if it exists (keep `PROMPT` and `RUBRIC_JSON` in sync):
```bash
ls tasks/<name>/task_ground_truth.py
```

Show a diff summary of what changed.

**If the user will make changes themselves:**
Wait for confirmation that they're done before proceeding.

### 7. Re-run the task

Ask: "Which model should I use to check the updated difficulty? I'll use the same model as the last run (`<model>`) by default — press enter to accept or name another."

Run:
```bash
inspect eval tasks/<name>/task.py --model <provider/model> --log-format json --log-dir ./logs
```

Extract the new score:
```bash
python3 -c "
import json, glob, os
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
log = json.load(open(logs[-1]))
print(log['results']['scores'][0]['metrics']['mean']['value'])
"
```

Report: "Score after changes: **X.XX** (was Y.YY, Δ = ±Z.ZZ)."

### 8. Evaluate the result and loop

**If new score < 0.8:**
If a ground truth file exists (`tasks/<name>/task_ground_truth.py`), tell the user:
"The task is now at the right difficulty level. Since the prompt and/or rubric changed, run `/ground-truth-check` first to confirm the human baseline still scores ≥ 0.8 with the updated criteria — then run `/task-run` for a full multi-model evaluation."

If no ground truth file exists, tell the user:
"The task is now at the right difficulty level. Would you like to:
- Run `/task-run` for a full multi-model evaluation
- Do another round of adjustments to push the score lower"

**If new score ≥ 0.8:**
"Score is still X.XX — still too easy. Let me analyse what models are still passing and suggest another round of changes."

Go back to Step 4 and repeat the diagnosis+proposal cycle with the updated task and fresh log.

**If score didn't change at all after changes:**
Note this to the user — it may indicate the change was too minor, or that the judge model is not sensitive to it. Suggest a more structural change (e.g., completely new constraint, additional rubric criterion) or offer to check the judge prompt for issues.
