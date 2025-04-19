import tempfile

from test_helpers.utils import failing_solver, skip_if_no_google, skip_if_no_openai

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._eval.evalset import eval_set
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.solver import solver

RED_TEAM = "red_team"
RED_TEAM_DEFAULT = "openai/gpt-4o"
GEMINI_FLASH_20 = "google/gemini-2.0-flash"


@solver
def role_solver():
    async def solve(state, generate):
        model = get_model(role=RED_TEAM, default=RED_TEAM_DEFAULT)
        state.output = await model.generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return solve


@task
def role_task():
    return Task(solver=role_solver())


@skip_if_no_google
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
def test_model_role_retry() -> None:
    log = eval(role_task(), model_roles={RED_TEAM: GEMINI_FLASH_20})[0]
    log.status = "cancelled"
    log.samples = []
    log = eval_retry(log)[0]
    assert log.eval.model_roles
    assert log.eval.model_roles[RED_TEAM].model == GEMINI_FLASH_20
    check_model_role(log, RED_TEAM, GEMINI_FLASH_20)


@skip_if_no_google
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
        check_model_role(logs[0], RED_TEAM, GEMINI_FLASH_20)


def check_model_role(log: EvalLog, role: str, model: str) -> None:
    assert log.samples
    model_event = next(
        (event for event in log.samples[0].events if event.event == "model")
    )
    assert model_event.role == role
    assert model_event.model == model


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
