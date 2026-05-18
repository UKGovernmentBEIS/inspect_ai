---
name: task-init
description: Create a new inspect_ai evaluation task with Docker sandbox. Gathers task description, local reference files, local ground truth files, and rubric from the user, then writes task files, Dockerfile, compose.yaml, and copies assets into a task subdirectory under tasks/.
user-invocable: true
disable-model-invocation: false
---

# Create Inspect AI Evaluation Task

Creates a task subdirectory under `tasks/<name>/` with everything needed to run an LLM in a sandboxed environment where it can execute code and produce real files (DOCX, PDF, etc.).

## Steps

### 1. Gather inputs from the user

Ask for all of the following. You may ask in one message or several.

**Task description** (required)
The full scenario + instructions the model will receive. Becomes the `PROMPT` constant. If the user gives a rough description, help refine it into a clear, self-contained scenario first.

**Task name** (required)
A short `snake_case` identifier (e.g. `bank_chat_support`). Used as the directory name and `@task` function name. Derive it from the task description if not specified.

**Reference files** (optional)
Local file paths the agent needs to read while completing the task (input documents, case files, templates). Ask: "Are there reference files the agent needs to work with? Provide local paths, or say no."

**Ground truth files** (optional)
Local file paths of human-created example outputs. Used to score human performance against the same rubric. Ask: "Do you have ground truth files — human-created reference outputs? Provide local paths, or say no."

**Rubric criteria** (required)
A list of evaluation criteria. For each item:
- The criterion text (what to check)
- The point value (integer)

Accept any format. Parse into `{"score": int, "criterion": str}` pairs. Suggest 1–2 pts for binary pass/fail, 3–10 pts for nuanced criteria.

**Rubric vagueness review** — after parsing criteria, before proceeding, flag any criterion that:
- Uses vague quality words: "good", "proper", "appropriate", "professional", "high quality", "well-written", "clear"
- Is a catch-all: "overall X", "general quality", "formatting"
- Cannot be answered YES/NO from the delivered files alone

For each flagged criterion, suggest a specific verifiable rewrite:
- "Professional tone" → "Contains no slang, filler words (e.g. 'hmmm', 'lol'), or emoticons"
- "Proper formatting" → "Uses heading styles for section titles" / "Each section contains at least one list"
- "Overall quality" → break into specific content checks

Present flags and suggestions to the user; confirm or adjust before writing the file. Do not block — if the user wants to keep a criterion as-is, proceed.

**Metadata** (optional)
`sector` and `occupation` strings. Skip if not mentioned.

### 2. Set up the task directory

```bash
mkdir -p tasks/<name>/reference
mkdir -p tasks/<name>/ground_truth
```

Copy reference files:
```bash
cp "<local_path>" tasks/<name>/reference/
```

Copy ground truth files:
```bash
cp "<local_path>" tasks/<name>/ground_truth/
```

Skip creating a directory if no files of that type were provided.

### 3. Write the task files

1. Run `python3 -c "import uuid; print(uuid.uuid4())"` to generate `TASK_ID`
2. Run the same command once per rubric item to generate each `rubric_item_id`
3. Write `tasks/<name>/Dockerfile` using the Dockerfile template below
4. Write `tasks/<name>/compose.yaml` using the compose template below
5. Write `tasks/<name>/task.py` using the main task template below
6. Customize `_JUDGE_PROMPT` with 1–2 sentences about what the task required
7. If ground truth files were provided, write `tasks/<name>/task_ground_truth.py` using the ground truth template — same `TASK_ID`, no sandbox

### 4. Confirm

Tell the user which files were created. Then:
- If ground truth files were provided: "Run `/ground-truth-check` to validate the ground truth scores ≥ 0.8 before running the full eval."
- Otherwise: "Run `/task-run` to evaluate this task against LLMs."

---

## Dockerfile (`tasks/<name>/Dockerfile`)

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir \
    python-docx \
    reportlab \
    fpdf2 \
    openpyxl \
    pandas \
    markdown \
    weasyprint
WORKDIR /task
RUN mkdir -p /task/reference /task/output
```

---

## compose.yaml (`tasks/<name>/compose.yaml`)

```yaml
services:
  default:
    build: .
    working_dir: /task
    command: tail -f /dev/null
    volumes:
      - ./output:/task/output
```

---

## Main task template (`tasks/<name>/task.py`)

```python
import json
import re
import tempfile
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ContentDocument, ContentText, get_model
from inspect_ai.scorer import Score, Scorer, mean, scorer, stderr
from inspect_ai.solver import TaskState, Generate, generate, solver, use_tools
from inspect_ai.scorer._target import Target
from inspect_ai.tool import bash
from inspect_ai.util import sandbox

TASK_ID = "<TASK_ID>"
TASK_DIR = Path(__file__).parent

PROMPT = """\
<task description>\
"""

RUBRIC_JSON = [
    {"score": <pts>, "criterion": "<criterion>", "rubric_item_id": "<uuid>"},
    # ... one entry per criterion
]

_JUDGE_PROMPT = """\
You are evaluating a response to a task. The model was asked to <1-2 sentence summary>.

The model had access to a bash environment and was expected to produce real files. \
Delivered files are listed as [DELIVERED FILE: ...] blocks. If document pages are \
attached, use them as the primary source for formatting and structural checks \
(bold text, line spacing, list structure, page count, visual layout).

MODEL RESPONSE:
{response}

RUBRIC CRITERIA (numbered, with point values):
{criteria}

For each criterion number, respond YES if the response meets it, NO if not.
Return ONLY a JSON object mapping criterion number (as string) to boolean, e.g.:
{{"1": true, "2": false, ...}}
"""


def _get_file_info(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    type_map = {".pdf": "PDF", ".docx": "Word Document", ".txt": "Text", ".md": "Markdown"}
    file_type = type_map.get(suffix, suffix.lstrip(".").upper())
    pages = "unknown"
    if suffix == ".pdf":
        import pypdf
        pages = str(len(pypdf.PdfReader(path).pages))
    elif suffix == ".docx":
        import docx
        words = sum(len(p.text.split()) for p in docx.Document(path).paragraphs)
        pages = str(max(1, words // 250))
    return {"type": file_type, "pages": pages}


def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        import docx
        doc = docx.Document(path)
        meta: list[str] = []
        try:
            pf = doc.styles["Normal"].paragraph_format
            if pf.line_spacing is not None:
                val = pf.line_spacing
                multiplier = float(val) if isinstance(val, float) else float(val) / 240
                meta.append(f"[Document line spacing: {multiplier:.2f}x]")
        except Exception:
            pass
        lines: list[str] = list(meta) + ([""] if meta else [])
        for para in doc.paragraphs:
            if not para.text.strip():
                lines.append("")
                continue
            style_name = (para.style.name or "").lower()
            is_list = any(kw in style_name for kw in ("list", "bullet", "number"))
            rich_parts: list[str] = []
            for run in para.runs:
                if run.text:
                    rich_parts.append(f"**{run.text}**" if run.bold else run.text)
            rich_text = "".join(rich_parts) if rich_parts else para.text
            lines.append(("• " if is_list else "") + rich_text)
        return "\n".join(lines)
    elif suffix == ".pdf":
        import pypdf
        reader = pypdf.PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        return path.read_text(encoding="utf-8", errors="replace")


def _to_document_content(path: Path) -> ContentDocument | None:
    """Base64-encode a PDF or DOCX (converted to PDF) as a ContentDocument."""
    import base64
    suffix = path.suffix.lower()
    pdf_path = path
    if suffix == ".docx":
        pdf_path = path.with_suffix(".pdf")
        if not pdf_path.exists():
            try:
                import subprocess
                subprocess.run(
                    ["libreoffice", "--headless", "--convert-to", "pdf",
                     str(path), "--outdir", str(path.parent)],
                    check=True, capture_output=True, timeout=60,
                )
            except Exception:
                return None
    if suffix not in (".pdf", ".docx") or not pdf_path.exists():
        return None
    data = base64.b64encode(pdf_path.read_bytes()).decode()
    return ContentDocument(document=f"data:application/pdf;base64,{data}")


@solver
def setup_sandbox():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()

        # Copy reference files into the sandbox
        ref_dir = TASK_DIR / "reference"
        ref_note = ""
        if ref_dir.exists() and any(ref_dir.iterdir()):
            for f in sorted(ref_dir.iterdir()):
                await sb.write_file(f"/task/reference/{f.name}", f.read_bytes())
            filenames = sorted(f.name for f in ref_dir.iterdir())
            ref_note = (
                f"\n\nReference files are available at /task/reference/: "
                + ", ".join(filenames)
            )

        state.messages.append(ChatMessageUser(content=(
            "You have access to a bash environment with Python and the following "
            "libraries pre-installed: python-docx, reportlab, fpdf2, openpyxl, "
            f"pandas, weasyprint. Write all output files to /task/output/.{ref_note}"
        )))
        return state
    return solve


@scorer(metrics=[mean(), stderr()])
def rubric_grader(model: str | None = None, source: str = "sandbox") -> Scorer:
    """Score delivered files against the rubric.

    Args:
        model: Judge model. Defaults to the task model.
        source: "sandbox" — reads output files from the Docker sandbox at
                /task/output/ (main task).
                "ground_truth" — reads files from TASK_DIR/ground_truth/
                on the local filesystem (ground truth task).
    """

    async def score(state: TaskState, target: Target) -> Score:
        rubric_items: list[dict] = state.metadata["rubric_json"]
        response_parts: list[str] = []
        doc_content: list[ContentDocument] = []

        if source == "sandbox":
            sb = sandbox()
            result = await sb.exec(["find", "/task/output", "-type", "f"])
            remote_files = sorted(
                p.strip() for p in result.stdout.splitlines() if p.strip()
            )
            if not remote_files and state.output.completion.strip():
                response_parts.append(state.output.completion)
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    for remote_path in remote_files:
                        filename = Path(remote_path).name
                        local_path = Path(tmpdir) / filename
                        file_bytes = await sb.read_file(remote_path, text=False)
                        local_path.write_bytes(file_bytes)
                        info = _get_file_info(local_path)
                        response_parts.append(
                            f"[DELIVERED FILE: {filename} | Type: {info['type']} "
                            f"| Pages: {info['pages']}]\n\n{_read_file(local_path)}"
                        )
                        doc = _to_document_content(local_path)
                        if doc:
                            doc_content.append(doc)
        else:
            gt_dir = TASK_DIR / "ground_truth"
            if gt_dir.exists():
                for f in sorted(gt_dir.iterdir()):
                    info = _get_file_info(f)
                    response_parts.append(
                        f"[DELIVERED FILE: {f.name} | Type: {info['type']} "
                        f"| Pages: {info['pages']}]\n\n{_read_file(f)}"
                    )
                    doc = _to_document_content(f)
                    if doc:
                        doc_content.append(doc)

        response = "\n\n---\n\n".join(response_parts) if response_parts else ""

        judge = get_model(model) if model else get_model()
        criteria_text = "\n".join(
            f"{i + 1}. [{item['score']} pts] {item['criterion']}"
            for i, item in enumerate(rubric_items)
        )
        prompt = _JUDGE_PROMPT.format(response=response, criteria=criteria_text)

        if doc_content:
            message_content: str | list = [ContentText(text=prompt)] + doc_content
        else:
            message_content = prompt
        output = await judge.generate([ChatMessageUser(content=message_content)])

        raw = output.completion
        match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        try:
            results: dict[str, bool] = json.loads(match.group()) if match else {}
        except json.JSONDecodeError:
            results = {}

        max_points = sum(item["score"] for item in rubric_items)
        points_earned = 0
        lines: list[str] = []
        for i, item in enumerate(rubric_items):
            met = bool(results.get(str(i + 1), False))
            pts = item["score"] if met else 0
            points_earned += pts
            mark = "✓" if met else "✗"
            lines.append(f"[{mark} {pts}/{item['score']}] {item['criterion']}")

        normalized = points_earned / max_points if max_points > 0 else 0.0

        return Score(
            value=normalized,
            explanation="\n".join(lines),
            metadata={
                "points_earned": points_earned,
                "points_possible": max_points,
                "task_id": TASK_ID,
            },
        )

    return score


@task
def <task_name>() -> Task:
    metadata = {
        "rubric_json": RUBRIC_JSON,
        "task_id": TASK_ID,
        # include only if provided:
        "sector": "<sector>",
        "occupation": "<occupation>",
    }
    return Task(
        dataset=[
            Sample(
                input=PROMPT,
                target="See rubric in metadata.",
                metadata=metadata,
            )
        ],
        solver=[
            setup_sandbox(),
            use_tools([bash()]),
            generate(),
        ],
        scorer=rubric_grader(),
        sandbox=("docker", str(TASK_DIR / "compose.yaml")),
    )
```

---

## Ground truth task template (`tasks/<name>/task_ground_truth.py`)

Only write this file if ground truth files were provided. Copy `RUBRIC_JSON`, `_JUDGE_PROMPT`, `_get_file_info`, `_read_file`, `_to_document_content`, and `rubric_grader` verbatim from `task.py`. No sandbox — the ground truth scorer reads local files directly.

```python
import json
import re
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ContentDocument, ContentText, ModelOutput, get_model
from inspect_ai.scorer import Score, Scorer, mean, scorer, stderr
from inspect_ai.solver import TaskState, Generate, solver
from inspect_ai.scorer._target import Target

TASK_ID = "<same TASK_ID as task.py>"
TASK_DIR = Path(__file__).parent

PROMPT = """\
<same task description as task.py>\
"""

RUBRIC_JSON = [
    # copy from task.py
]

_JUDGE_PROMPT = """\
<copy from task.py>
"""


def _get_file_info(path: Path) -> dict[str, str]:
    # copy verbatim from task.py


def _read_file(path: Path) -> str:
    # copy verbatim from task.py


def _to_document_content(path: Path) -> ContentDocument | None:
    # copy verbatim from task.py


@solver
def ground_truth_loader():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        gt_dir = TASK_DIR / "ground_truth"
        sections = []
        for f in sorted(gt_dir.iterdir()):
            info = _get_file_info(f)
            content = _read_file(f)
            sections.append(
                f"[DELIVERED FILE: {f.name} | Type: {info['type']} | Pages: {info['pages']}]\n\n{content}"
            )
        state.output = ModelOutput.from_content(
            model="ground_truth",
            content="\n\n---\n\n".join(sections),
        )
        return state
    return solve


@scorer(metrics=[mean(), stderr()])
def rubric_grader(model: str | None = None, source: str = "sandbox") -> Scorer:
    # copy verbatim from task.py


@task
def <task_name>_ground_truth() -> Task:
    return Task(
        dataset=[
            Sample(
                input=PROMPT,
                target="See rubric in metadata.",
                metadata={
                    "rubric_json": RUBRIC_JSON,
                    "task_id": TASK_ID,
                },
            )
        ],
        solver=[ground_truth_loader()],
        scorer=rubric_grader(source="ground_truth"),
        # no sandbox — ground truth reads local files directly
    )
```
