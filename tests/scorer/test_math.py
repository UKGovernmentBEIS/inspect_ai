import importlib.metadata
import json
import math as stdlib_math
from pathlib import Path
from typing import Any

import anyio
import pytest
from test_helpers.utils import simple_task_state

import inspect_ai.scorer._math as math_module
from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import CORRECT, INCORRECT, Target, math
from inspect_ai.scorer._math import (
    _answer_candidates,
    _MathLimitError,
    _parse_candidate,
    _score_answer_worker,
)
from inspect_ai.solver import generate

CASES = json.loads(
    (Path(__file__).parent / "math_cases.json").read_text(encoding="utf-8")
)


async def test_math_scorer_compatibility_cases() -> None:
    scorer = math()
    for case in CASES:
        state = simple_task_state(model_output=case["output"])
        result = await scorer(state, Target([case["target"]]))
        assert result is not None
        assert result.value == case["expected"], case


async def test_math_scorer_uses_last_boxed_answer() -> None:
    scorer = math()
    state = simple_task_state(model_output=r"\boxed{10} and then \boxed{42}")

    result = await scorer(state, Target(["42"]))
    assert result is not None
    assert result.value == CORRECT

    result = await scorer(state, Target([r"\{10,42\}"]))
    assert result is not None
    assert result.value == INCORRECT


async def test_math_scorer_uses_valid_target_alternative() -> None:
    scorer = math()
    state = simple_task_state(model_output=r"\boxed{42}")
    result = await scorer(
        state,
        Target([r"__import__('os').system('false')", "42"]),
    )
    assert result is not None
    assert result.value == CORRECT


async def test_invalid_target_is_unscored() -> None:
    scorer = math()
    state = simple_task_state(model_output=r"\boxed{42}")
    result = await scorer(
        state,
        Target([r"__import__('os').system('false')"]),
    )

    assert result is not None
    assert isinstance(result.value, float)
    assert stdlib_math.isnan(result.value)
    assert result.metadata == {"math_scorer_status": "target_parse_error"}


async def test_model_complexity_rejection_is_incorrect() -> None:
    scorer = math()
    state = simple_task_state(model_output=r"\boxed{2^{2^{2^{49}}}}")
    result = await scorer(state, Target(["1"]))

    assert result is not None
    assert result.value == INCORRECT
    assert result.metadata == {"math_scorer_status": "answer_limit"}


def test_plain_and_latex_parsers_do_not_call_parse_expr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import latex2sympy2_extended.latex2sympy2 as parser  # type: ignore[import-untyped]

    def fail_parse_expr(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unsafe parse_expr() called")

    monkeypatch.setattr(parser, "parse_expr", fail_parse_expr)
    for expression in (
        r"\frac{1}{2}",
        r"\sqrt{2}",
        r"\left(1,2\right)",
        r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
        "sqrt(2) + sqrt(2)",
    ):
        assert _parse_candidate(expression)


@pytest.mark.parametrize(
    ("answer", "target"),
    [
        ("33.5%", "0.335"),
        (r"33.5\%", "0.335"),
        ("33.5 percent", "0.335"),
        ("33.5 percentage", "0.335"),
        ("33.5 pct", "0.335"),
        (r"\frac{1}{2}\%", "0.005"),
        (r"\frac{1}{2}\text{ percent}", "0.005"),
    ],
)
def test_percentage_suffixes_are_normalized(answer: str, target: str) -> None:
    result = _score_answer_worker(answer, (target,))
    assert result.status == "correct"


def test_percentage_is_removed_before_latex_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_latex = math_module._parse_latex_expression
    parsed_candidates: list[str] = []

    def recording_parser(candidate: str, sympy: Any) -> Any:
        parsed_candidates.append(candidate)
        return parse_latex(candidate, sympy)

    monkeypatch.setattr(math_module, "_parse_latex_expression", recording_parser)

    parsed = _parse_candidate(r"\frac{1}{2}\%")

    assert parsed.expression is not None
    assert parsed_candidates == [r"\frac{1}{2}"]


@pytest.mark.parametrize(
    "expression",
    [
        r"\operatorname{SVD}(\begin{pmatrix}1&2\\3&4\end{pmatrix})",
        r"\|\begin{pmatrix}1&2\\3&4\end{pmatrix}\|",
        r"1\xRightarrow{n}2",
    ],
)
def test_eager_latex_operations_are_rejected_before_parsing(
    expression: str,
) -> None:
    with pytest.raises(
        _MathLimitError, match="expression requests an eager mathematical operation"
    ):
        _parse_candidate(expression)


@pytest.mark.timeout(5)
@pytest.mark.parametrize(
    ("expression", "function_name"),
    [
        (r"\binom{1000000}{500000}", "binomial"),
        (r"\Gamma(1000000)", "gamma"),
    ],
)
def test_eager_latex_constructors_remain_unevaluated(
    expression: str, function_name: str
) -> None:
    parsed = _parse_candidate(expression)

    assert parsed.expression is not None
    assert parsed.expression.func.__name__ == function_name


@pytest.mark.parametrize(
    "version",
    ["4.9.3", "4.11.0", "4.11.1", "4.13.2"],
)
def test_supported_antlr_versions(version: str) -> None:
    assert math_module._supported_antlr_version(version)


def test_unsupported_antlr_version_has_clear_prerequisite_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_version = importlib.metadata.version

    def fake_version(package: str) -> str:
        if package == math_module._ANTLR_PACKAGE:
            return "4.12.0"
        return package_version(package)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    with pytest.raises(PrerequisiteError) as exc_info:
        math()

    assert "4.9.3, 4.11.x, or 4.13.2" in str(exc_info.value.message)
    assert "you have 4.12.0" in str(exc_info.value.message)


@pytest.mark.parametrize(
    "payload",
    [
        "__import__('os').system('touch marker')",
        "open('marker', 'w').write('x')",
        "getattr(__import__('pathlib').Path('marker'), 'touch')()",
        "(1).__class__.__mro__[1].__subclasses__()",
        "(lambda: open('marker', 'w'))()",
        "[open('marker', 'w') for _ in [0]]",
        "globals()['__builtins__']['open']('marker', 'w')",
    ],
)
def test_security_payload_is_rejected_without_fallback(payload: str) -> None:
    result = _score_answer_worker(f"{payload} or 0", ("0",))
    assert result.status == "answer_parse_error"


def test_security_payloads_do_not_execute_in_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INSPECT_TELEMETRY", raising=False)
    monkeypatch.delenv("INSPECT_API_KEY_OVERRIDE", raising=False)
    monkeypatch.delenv("INSPECT_REQUIRED_HOOKS", raising=False)
    marker = tmp_path / "math-scorer-marker"
    payloads = [
        f"__import__('pathlib').Path({str(marker)!r}).write_text('import')",
        f"open({str(marker)!r}, 'w').write('open')",
        f"getattr(__import__('pathlib').Path({str(marker)!r}), 'touch')()",
        f"(lambda: open({str(marker)!r}, 'w'))()",
        f"[open({str(marker)!r}, 'w') for _ in [0]]",
        f"(1).__class__.__mro__[1].__subclasses__() and open({str(marker)!r}, 'w')",
    ]
    outputs = [
        ModelOutput.from_content("mockllm/model", payload) for payload in payloads
    ]
    model = get_model("mockllm/model", custom_outputs=outputs)
    task = Task(
        dataset=[
            Sample(input=f"payload {index}", target="0")
            for index in range(len(payloads))
        ],
        solver=generate(),
        scorer=math(),
    )

    log = eval(
        task,
        model=model,
        display="none",
        log_dir=str(tmp_path / "logs"),
    )[0]

    assert not marker.exists()
    assert log.samples
    assert all(sample.error is None for sample in log.samples)
    assert all(
        sample.score and sample.score.value == INCORRECT for sample in log.samples
    )


def test_long_output_extraction_is_bounded() -> None:
    completion = f"{'reasoning ' * 50_000}\\boxed{{42}}"
    assert _answer_candidates(completion)[0] == "42"

    with pytest.raises(_MathLimitError, match="model output is too long"):
        _answer_candidates("x" * (math_module._MAX_COMPLETION_CHARS + 1))


async def test_target_timeout_is_unscored(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_run_sync(*_args: Any, **_kwargs: Any) -> None:
        await anyio.sleep(1)

    monkeypatch.setattr(math_module, "run_sync", slow_run_sync)
    monkeypatch.setattr(math_module, "_COLD_WORKER_TIMEOUT_SECONDS", 0.01)

    result = await math()(
        simple_task_state(model_output="42"),
        Target(["42"]),
    )

    assert result is not None
    assert isinstance(result.value, float)
    assert stdlib_math.isnan(result.value)
    assert result.metadata == {"math_scorer_status": "target_timeout"}


async def test_answer_timeout_is_incorrect(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def staged_run_sync(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        await anyio.sleep(1)

    monkeypatch.setattr(math_module, "run_sync", staged_run_sync)
    monkeypatch.setattr(math_module, "_ANSWER_TIMEOUT_SECONDS", 0.01)

    result = await math()(
        simple_task_state(model_output="42"),
        Target(["42"]),
    )

    assert result is not None
    assert result.value == INCORRECT
    assert result.metadata == {"math_scorer_status": "answer_timeout"}


async def test_target_worker_crash_is_contextual_scorer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_run_sync(*_args: Any, **_kwargs: Any) -> None:
        raise anyio.BrokenWorkerProcess

    monkeypatch.setattr(math_module, "run_sync", broken_run_sync)

    with pytest.raises(
        RuntimeError,
        match="worker process exited unexpectedly while parsing the target",
    ) as exc_info:
        await math()(
            simple_task_state(model_output="42"),
            Target(["42"]),
        )

    assert isinstance(exc_info.value.__cause__, anyio.BrokenWorkerProcess)
    assert math_module._math_worker_context().started is False


async def test_answer_worker_crash_is_contextual_scorer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def staged_run_sync(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        raise anyio.BrokenWorkerProcess

    monkeypatch.setattr(math_module, "run_sync", staged_run_sync)

    with pytest.raises(
        RuntimeError,
        match="worker process exited unexpectedly while scoring the model answer",
    ) as exc_info:
        await math()(
            simple_task_state(model_output="42"),
            Target(["42"]),
        )

    assert isinstance(exc_info.value.__cause__, anyio.BrokenWorkerProcess)
    assert math_module._math_worker_context().started is False


async def test_worker_queue_time_is_not_expression_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def short_worker_call(function: Any, *_args: Any, **_kwargs: Any) -> Any:
        await anyio.sleep(0.02)
        if function is math_module._parse_targets_worker:
            return None
        return math_module._WorkerScore("correct", "42")

    monkeypatch.setattr(math_module, "run_sync", short_worker_call)
    monkeypatch.setattr(math_module, "_MATH_WORKERS", 1)
    monkeypatch.setattr(math_module, "_COLD_WORKER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(math_module, "_TARGET_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(math_module, "_ANSWER_TIMEOUT_SECONDS", 0.05)

    scorer = math()
    results = []

    async def run_score() -> None:
        result = await scorer(
            simple_task_state(model_output="42"),
            Target(["42"]),
        )
        results.append(result)

    async with anyio.create_task_group() as task_group:
        for _ in range(8):
            task_group.start_soon(run_score)

    assert all(result is not None and result.value == CORRECT for result in results)


def test_worker_context_resets_across_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cold_worker_call(function: Any, *_args: Any, **_kwargs: Any) -> Any:
        await anyio.sleep(0.02)
        if function is math_module._parse_targets_worker:
            return None
        return math_module._WorkerScore("correct", "42")

    monkeypatch.setattr(math_module, "run_sync", cold_worker_call)
    monkeypatch.setattr(math_module, "_MATH_WORKERS", 1)
    monkeypatch.setattr(math_module, "_COLD_WORKER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(math_module, "_TARGET_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(math_module, "_ANSWER_TIMEOUT_SECONDS", 0.05)
    scorer = math()

    async def run_once() -> None:
        result = await scorer(
            simple_task_state(model_output="42"),
            Target(["42"]),
        )
        assert result is not None
        assert result.value == CORRECT

    anyio.run(run_once)
    anyio.run(run_once)
