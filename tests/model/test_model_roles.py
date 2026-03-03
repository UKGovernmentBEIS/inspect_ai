import tempfile

from test_helpers.utils import failing_solver, skip_if_no_google, skip_if_no_openai

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._eval.evalset import eval_set
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import EvalLog
from inspect_ai.model import Model, get_model
from inspect_ai.solver import solver

RED_TEAM = "red_team"
RED_TEAM_DEFAULT = "openai/gpt-4o"
GEMINI_FLASH_20 = "google/gemini-2.0-flash"


@solver
def role_solver(red_team_model: Model | None = None):
    async def solve(state, generate):
        model = red_team_model or get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT)
        state.output = await model.generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return solve


@task
def role_task():
    return Task(solver=role_solver())


# skip_if_no_openai is needed on the below tests because of RED_TEAM_DEFAULT
# which is "openai/gpt-4o"


@skip_if_no_google
@skip_if_no_openai
def test_model_role() -> None:
    log = eval(role_task(), model_roles={RED_TEAM: GEMINI_FLASH_20})[0]
    assert log.eval.model_roles
    assert log.eval.model_roles[RED_TEAM].model == GEMINI_FLASH_20
    check_model_role(log, RED_TEAM, GEMINI_FLASH_20)


@skip_if_no_openai
def test_model_role_default() -> None:
    log = eval(role_task())[0]
    check_model_role(log, RED_TEAM, RED_TEAM_DEFAULT)


@skip_if_no_google
@skip_if_no_openai
def test_model_role_retry() -> None:
    log = eval(role_task(), model_roles={RED_TEAM: GEMINI_FLASH_20})[0]
    log.status = "cancelled"
    log.samples = []
    log = eval_retry(log)[0]
    assert log.eval.model_roles
    assert log.eval.model_roles[RED_TEAM].model == GEMINI_FLASH_20
    check_model_role(log, RED_TEAM, GEMINI_FLASH_20)


@task
def role_task_init():
    red_team = get_model(role=RED_TEAM, default="mockllm/model")
    return Task(solver=role_solver(red_team))


@skip_if_no_google
@skip_if_no_openai
def test_model_role_task_init():
    log = eval(role_task_init, model_roles={RED_TEAM: GEMINI_FLASH_20})[0]
    assert log.eval.model_roles
    assert log.eval.model_roles[RED_TEAM].model == GEMINI_FLASH_20
    check_model_role(log, RED_TEAM, GEMINI_FLASH_20)


@skip_if_no_google
@skip_if_no_openai
def test_model_role_eval_set() -> None:
    dataset: list[Sample] = []
    for _ in range(0, 10):
        dataset.append(Sample(input="Say hello", target="hello"))

    eval_set_task = Task(dataset=dataset, solver=[role_solver(), failing_solver()])

    with tempfile.TemporaryDirectory() as log_dir:
        _, logs = eval_set(
            eval_set_task,
            log_dir=log_dir,
            retry_wait=0.001,
            retry_attempts=5,
            model_roles={RED_TEAM: GEMINI_FLASH_20},
        )
        check_model_role(read_eval_log(logs[0].location), RED_TEAM, GEMINI_FLASH_20)


def check_model_role(log: EvalLog, role: str, model: str) -> None:
    assert log.samples
    model_event = next(
        (event for event in log.samples[0].events if event.event == "model")
    )
    assert model_event.role == role
    assert model_event.model == model


def test_role_usage_tracking_mockllm() -> None:
    @task
    def mock_role_task():
        return Task(solver=role_solver())

    log = eval(mock_role_task(), model_roles={RED_TEAM: MOCK_A})[0]

    assert log.stats.role_usage is not None
    assert RED_TEAM in log.stats.role_usage
    assert log.stats.role_usage[RED_TEAM].total_tokens > 0

    assert log.samples is not None
    assert len(log.samples) > 0
    sample = log.samples[0]
    assert sample.role_usage is not None
    assert RED_TEAM in sample.role_usage
    assert sample.role_usage[RED_TEAM].total_tokens > 0


def test_role_usage_shared_model() -> None:
    log = eval(
        Task(solver=multi_role_solver()),
        model_roles={GRADER: MOCK_A, REVIEWER: MOCK_A},
    )[0]

    # Both roles used the same model
    assert log.stats.model_usage is not None
    assert MOCK_A in log.stats.model_usage

    # Role usage should separate them
    assert log.stats.role_usage is not None
    assert GRADER in log.stats.role_usage
    assert REVIEWER in log.stats.role_usage

    grader_tokens = log.stats.role_usage[GRADER].total_tokens
    reviewer_tokens = log.stats.role_usage[REVIEWER].total_tokens
    total_tokens = log.stats.model_usage[MOCK_A].total_tokens

    # Both roles have usage
    assert grader_tokens > 0
    assert reviewer_tokens > 0
    assert total_tokens == grader_tokens + reviewer_tokens


def test_role_usage_eval_retry() -> None:
    @task
    def mock_role_task_retry():
        return Task(solver=role_solver())

    log = eval(mock_role_task_retry(), model_roles={RED_TEAM: MOCK_A})[0]
    original_tokens = log.stats.role_usage[RED_TEAM].total_tokens
    log.status = "cancelled"
    log.samples = []
    log_retry = eval_retry(log)[0]

    assert log_retry.stats.role_usage is not None
    assert RED_TEAM in log_retry.stats.role_usage
    retry_tokens = log_retry.stats.role_usage[RED_TEAM].total_tokens
    assert retry_tokens >= original_tokens


@skip_if_no_google
@skip_if_no_openai
def test_role_usage_tracking() -> None:
    log = eval(role_task(), model_roles={RED_TEAM: GEMINI_FLASH_20})[0]

    assert log.stats.role_usage is not None
    assert RED_TEAM in log.stats.role_usage
    assert log.stats.role_usage[RED_TEAM].total_tokens > 0

    assert log.samples is not None
    assert len(log.samples) > 0
    sample = log.samples[0]
    assert sample.role_usage is not None
    assert RED_TEAM in sample.role_usage
    assert sample.role_usage[RED_TEAM].total_tokens > 0


@solver
def check_memoize_solver():
    def validate(condition: bool, description: str):
        if not condition:
            raise ValueError(f"Condition not satified: {description}")

    async def solve(state, generate):
        validate(
            get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT)
            == get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT),
            "get_model by role is memoized",
        )

        validate(
            get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT)
            != get_model(RED_TEAM_DEFAULT),
            "get_model by role memoization is partioned from normal get_model",
        )

        validate(
            get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT).role == RED_TEAM,
            "role is assigned correctly event for default",
        )

        return state

    return solve


@skip_if_no_google
@skip_if_no_openai
def test_model_role_memoize() -> None:
    # check with role specified
    log = eval(
        Task(solver=check_memoize_solver()), model_roles={RED_TEAM: GEMINI_FLASH_20}
    )[0]
    assert log.status == "success"

    # check with default role
    log = eval(Task(solver=check_memoize_solver()))[0]
    assert log.status == "success"


# -- Merge tests (mockllm, no API keys needed) --

GRADER = "grader"
REVIEWER = "reviewer"
MOCK_A = "mockllm/model_a"
MOCK_B = "mockllm/model_b"
MOCK_C = "mockllm/model_c"


@solver
def grader_role_solver():
    async def solve(state, generate):
        model = get_model(role=GRADER)
        state.output = await model.generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return solve


@solver
def multi_role_solver():
    async def solve(state, generate):
        grader = get_model(role=GRADER)
        reviewer = get_model(role=REVIEWER)
        state.output = await grader.generate(state.messages)
        state.messages.append(state.output.message)
        state.output = await reviewer.generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return solve


def test_model_role_merge_eval_overrides_task() -> None:
    """Eval-level model_roles should override task-level for the same role."""
    t = Task(
        solver=grader_role_solver(),
        model_roles={GRADER: MOCK_A},
    )
    log = eval(t, model_roles={GRADER: MOCK_B})[0]
    assert log.status == "success"
    check_model_role(log, GRADER, MOCK_B)


def test_model_role_merge_preserves_unspecified() -> None:
    """Eval-level override for one role preserves task-level defaults for others."""
    t = Task(
        solver=multi_role_solver(),
        model_roles={GRADER: MOCK_A, REVIEWER: MOCK_B},
    )
    log = eval(t, model_roles={GRADER: MOCK_C})[0]
    assert log.status == "success"
    # grader should be overridden to MOCK_C
    check_model_role(log, GRADER, MOCK_C)
    # reviewer should be preserved as MOCK_B from the task
    assert log.samples
    model_events = [e for e in log.samples[0].events if e.event == "model"]
    reviewer_event = next(e for e in model_events if e.role == REVIEWER)
    assert reviewer_event.model == MOCK_B
