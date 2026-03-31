# Princeton PLI Team Inspect Crossover

See [this paper (PDF)](https://arxiv.org/pdf/2602.16666), page 6. Log-derived reliability metrics (consistency, robustness, predictability) live under `scripts/pli/`. Some metrics require runs with confidence or paraphrasing attached first (e.g. robustness, predictability).


# Setup and initial run

This workflow uses Python and `uv`; there is no separate compile step.

## 1) Create and activate a virtual environment

```bash
uv venv
source .venv/bin/activate
```

## 2) Install dependencies

```bash
uv sync
```

This repository (`inspect_ai`) does not include GPQA tasks directly.
Use `uv run --with ...` below to fetch the GPQA task package at runtime.

## 3) Configure environment variables

Create a `.env` file in the project root with your model and API key.

Example:

```env
INSPECT_EVAL_MODEL=openai/gpt-5-nano
OPENAI_API_KEY=your_api_key_here
```

## 4) Run a small GPQA example

Run only a few samples first to generate a log:

```bash
uv run --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond -T epochs=2 --limit 2 --max-connections 5
```

## 5) View results

```bash
uv run inspect view
```


# Consistency (`scripts/pli`)

## Running to generate consistency logs (agent-agnostic)

Writes `.eval` logs under `logs/baseline` (same layout as the prompt-robustness baseline run).

```bash
uv run --with . --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond -T epochs=2 --limit 2 --max-connections 5 --log-dir logs/baseline
```


## Outcome consistency

```bash
uv run python scripts/pli/outcome_consistency.py --latest --log-dir logs/baseline
```

## Resource consistency

```bash
uv run python scripts/pli/resource_consistency.py --latest --log-dir logs/baseline
```

# Predictability (`scripts/pli`)

## Running to generate record confidence (agent-agnostic)

Use `scripts/helper_scripts/confidence_solver.py@confidence_generate` to write `sample.metadata["confidence"]` during eval. It supports:
- `method=logprobs`
- `method=top_logprobs`
- `method=scored_confidence` (fallback for models that don't expose logprobs)

For multiple-choice tasks (e.g. GPQA), the solver runs `multiple_choice()` internally so answers are parsed and the `choice` scorer works; the scored-confidence prompt uses the same full user message (question + options). Override `-S choice_template=...` if your task uses a custom or CoT MC template.

```bash
# baseline run with confidence annotation in sample metadata
uv run --with . --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond \
  --solver scripts/helper_scripts/confidence_solver.py@confidence_generate \
  -S method=scored_confidence \
  -S scored_max_tokens=1024 \
  -T epochs=2 --limit 2 --max-connections 5 --log-dir logs/confidence
```

## Discrimination predictability (P_AUROC)

Needs per-sample **confidence** in metadata (e.g. from a custom scorer), plus binary outcomes from the chosen scorer. **P_AUROC is only defined if the log has both successes and failures** (at least one incorrect sample); otherwise the script reports `P_AUROC=undefined` with counts.

```bash
uv run python scripts/pli/discrimination_predictability.py \
  --latest --log-dir logs/confidence --confidence-key confidence --confidence-source sample
```

## Brier predictability (P_brier)

Same confidence and outcome inputs as above, with
`P_brier = 1 - (1/T) Σ_i (c_i - y_i)²` (one minus mean squared error; higher is better). Defined even when all samples are correct or all incorrect.

```bash
uv run python scripts/pli/brier_predictability.py \
  --latest --log-dir logs/confidence --confidence-key confidence --confidence-source sample
```

# Robustness (`scripts/pli`)

## Prompt robustness (R_prompt)

`R_prompt = min(Acc_para / Acc_0, 1)` where the **paraphrase** run uses `apply_prompt_paraphrase` (via `scripts/helper_scripts/prompt_paraphrase_solver.py`) to rewrite the user prompt with a **different model** before the main eval model sees it. Uses an extra model call for paraphrasing. For datasets with `choices` (e.g. GPQA), the text sent to the paraphrase model includes the same multiple-choice options and newlines as the `multiple_choice` formatter (override with `-S choice_template=...` if your task uses a custom or CoT MC template).

```bash
uv run --with . --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond -T epochs=2 --limit 2 --max-connections 5 --log-dir logs/baseline

uv run --with . --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond --solver scripts/helper_scripts/prompt_paraphrase_solver.py@paraphrased_generate -S model=openai/gpt-4o-mini -S temperature=0.7 -T epochs=2 --limit 2 --max-connections 5 --log-dir logs/paraphrase

uv run python scripts/pli/prompt_robustness.py --baseline-latest --baseline-log-dir logs/baseline --paraphrase-latest --paraphrase-log-dir logs/paraphrase
```



## TODO:
- Explanation is not preserved in the log outputs for confidence/paraphrase
- Determine if some of these outputs (e.g. consistency) can end up in the epoch_reducer built-in tool
- Expand to non-mulitple choice
- Expand to agentic
- Dive deeper into confidence methods