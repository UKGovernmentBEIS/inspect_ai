
# Inspect AI Evaluation Tasks

This directory contains LLM evaluation tasks built on [Inspect AI](https://inspect.ai-safety-institute.org.uk/). Each task presents a real-world scenario to a model, scores its response against a rubric using a judge LLM, and compares the model's performance against a human-created ground truth.

---

## Prerequisites

### 1. Install dependencies

```bash
uv sync
```

The `inspect` CLI will be available at `.venv/bin/inspect`. Add it to your path or invoke it directly.

### 2. Install document parsing library

Required to read `.docx` reference and ground truth files:

```bash
.venv/bin/pip install python-docx
```

### 3. Install Claude Code CLI

The `/task-init`, `/task-run`, and other workflow commands are Claude Code skills. Install the CLI:

```bash
npm install -g @anthropic-ai/claude-code
```

Then launch it from the project root:

```bash
claude
```

### 4. Configure API keys

Create a `.env` file in the project root with your provider key(s):

```bash
# Use OpenRouter to access any supported model via one key:
OPENROUTER_API_KEY=sk-or-v1-...

# Or use provider keys directly:
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
```

The evaluation scripts load this file automatically via `source .env` before running `inspect eval`.

### 5. Docker (for sandboxed tasks)

Tasks created with the latest `/task-init` version run the evaluated model inside a Docker sandbox so it can produce real output files (`.docx`, `.pdf`, etc.). Make sure Docker Desktop is running before executing those tasks.

---

## Workflow

### Step 1 — Create a task: `/task-init`

Run `/task-init` in Claude Code and provide:

| Input | Description |
|---|---|
| **Task description** | The full scenario + instructions the model will receive |
| **Reference files** | Local paths to input documents the model needs to read (e.g. case files, templates) |
| **Ground truth files** | Local paths to human-created example outputs, used as a scoring baseline |
| **Rubric criteria** | List of evaluation criteria with point values |
| **Metadata** (optional) | `sector` and `occupation` strings |

The skill creates `tasks/<name>/` with:

```
tasks/<name>/
├── task.py                  ← main evaluation task
├── task_ground_truth.py     ← ground truth scoring task (if GT files provided)
├── reference/               ← input files injected into the model's context
├── ground_truth/            ← human-created deliverable(s) for baseline scoring
├── Dockerfile               ← sandbox image (latest task-init version)
└── compose.yaml             ← Docker Compose config for the sandbox
```

---

### Step 2 — Validate ground truth: `/ground-truth-check`

Before running the full evaluation, verify that the human-created ground truth scores ≥ 0.8 against the rubric. This catches mismatches between the rubric wording and the actual deliverable.

```
/ground-truth-check
```

The skill runs `task_ground_truth.py`, inspects failures, and iteratively proposes fixes to either the rubric criteria or the ground truth file until the score is acceptable. Type **"skip"** to bypass and go straight to evaluation.

---

### Step 3 — Run the evaluation: `/task-run`

```
/task-run
```

The skill asks which task to run (main, ground truth, or both) and which models to evaluate against. Defaults:

- `anthropic/claude-sonnet-4-6`
- `openai/gpt-4o`
- `google/gemini-2.0-flash`

When using OpenRouter, prefix models with `openrouter/`, e.g.:

```bash
openrouter/anthropic/claude-sonnet-4-6
openrouter/openai/gpt-4o
```

Logs are saved to `logs/` as JSON.

---

### Step 4 — Calibrate difficulty (if needed): `/difficulty-calibration`

If the average score across models is ≥ 0.8, models are solving the task too easily. Run:

```
/difficulty-calibration
```

The skill analyses which criteria are passing, suggests targeted changes to the prompt or rubric to raise difficulty, then re-runs until the average drops below 0.8.

---

### Step 5 — Generate a report: `/final-report`

```
/final-report
```

Composes a structured markdown report from ground truth and main task results. Saved to `tasks/<name>/final-report/report.md`.

---

### Step 6 — Push to GitHub: `/task-push`

```
/task-push
```

Commits the task directory to a dedicated branch and opens a pull request. Never pushes to `main`.

---

## Running evaluations manually

```bash
# Load API keys
source .env

# Run main task
.venv/bin/inspect eval tasks/<name>/task.py \
  --model openrouter/anthropic/claude-sonnet-4-6 \
  --log-format json \
  --log-dir ./logs

# Run ground truth task
.venv/bin/inspect eval tasks/<name>/task_ground_truth.py \
  --model openrouter/anthropic/claude-sonnet-4-6 \
  --log-format json \
  --log-dir ./logs

# Extract score from latest log
python3 -c "
import json, glob, os
logs = sorted(glob.glob('logs/*.json'), key=os.path.getmtime)
log = json.load(open(logs[-1]))
print(log['results']['scores'][0]['metrics']['mean']['value'])
"
```

---

## Task directory structure

```
tasks/
└── <task_name>/
    ├── task.py                  # Main task: injects reference files, gives model write_output_file tool
    ├── task_ground_truth.py     # GT task: reads ground truth .docx directly, no model call
    ├── reference/               # Input files (e.g. Case One.docx, Case Two.docx)
    ├── ground_truth/            # Human deliverable (e.g. Case Feedback.docx)
    ├── output/                  # Created at runtime; holds files the model writes
    ├── logs/                    # Per-task logs (if using --log-dir here)
    ├── final-report/
    │   └── report.md
    ├── Dockerfile
    └── compose.yaml
```

### How scoring works

1. **Reference injection** — `inject_reference_files()` reads all files in `reference/` and appends their text to the model's context before generation.
2. **Tool-based file delivery** — the model calls `write_output_file(filename, content)` to create deliverables; these are saved to `output/`.
3. **Scorer** — `rubric_grader()` collects the model's inline response plus any files in `output/`, formats them as `[DELIVERED FILE: ...]` blocks, and sends everything to a judge LLM that scores each rubric criterion.
4. **Ground truth baseline** — `ground_truth_loader()` reads the human deliverable from `ground_truth/`, sets `state.output` directly (no model call), and runs the same scorer. This gives the expected upper-bound score.

---

## Score interpretation

| Average score | Meaning |
|---|---|
| < 0.8 | Task is appropriately challenging — ready to push |
| ≥ 0.8 | Models solving too easily — run `/difficulty-calibration` |
| Ground truth < 0.8 | Rubric/GT mismatch — run `/ground-truth-check` to fix |
