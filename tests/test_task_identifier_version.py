from inspect_ai import Task, task
from inspect_ai._eval.evalset import (
    TASK_IDENTIFIER_VERSION,
    EvalSetArgsInTaskIdentifier,
    task_identifier,
)
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.task import task_with
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

# Expected task identifiers for each version. These values must NOT be changed.
# If the task_identifier computation changes, add a new version entry with the
# new expected value and bump TASK_IDENTIFIER_VERSION.
_EXPECTED_TASK_IDENTIFIERS: dict[int, str] = {
    1: "tests/test_task_identifier_version.py@version_test_task#44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a/mockllm/model/29797164a2ed3858f2e5b9a08f6594cfe398a975e2094dadb17a15f84e53613c",
}


def _create_resolved_task_with_all_fields():
    """Create a ResolvedTask that exercises all fields contributing to task_identifier.

    Every field that feeds into the task_identifier hash is set to a non-default
    value so that changes to any field's inclusion will be detected.

    Fields exercised:
      - task_file (via resolve_tasks with a file path)
      - task_name (via @task decorator name)
      - task_args (non-empty dict, SHA256 hashed)
      - model name (str(model))
      - model_generate_config (model.config with non-default temperature)
      - model_roles (non-empty, hashed)
      - eval_plan (from resolve_plan + plan_to_eval_plan, includes solver steps)
      - additional_hash_fields:
          - model_args (non-empty)
          - version (non-default)
          - message_limit
          - token_limit
          - time_limit
          - working_limit
          - cost_limit
    """
    model = get_model(
        "mockllm/model",
        config=GenerateConfig(temperature=0.5),
    )
    scorer_model = get_model("mockllm/scorer")

    @task
    def version_test_task(task_arg: str = "test_value"):
        return Task(
            dataset=[Sample(input="test input", target="test target")],
            solver=[generate()],
            scorer=exact(),
            version=2,
            message_limit=50,
            token_limit=1000,
            time_limit=120,
            working_limit=60,
            cost_limit=0.5,
        )

    t = version_test_task()
    task_with(t, model=model, model_roles={"scorer": scorer_model})
    resolved = resolve_tasks([t], {}, model, None, None, None)
    return resolved[0]


def test_task_identifier_version_stability():
    """Verify that the task_identifier output has not changed for the current version.

    If this test fails, it means the task_identifier computation has changed.
    Do NOT update the expected value. Instead:
      1. Bump TASK_IDENTIFIER_VERSION in evalset.py
      2. Add a new entry to _EXPECTED_TASK_IDENTIFIERS with the new hash
    """
    assert TASK_IDENTIFIER_VERSION in _EXPECTED_TASK_IDENTIFIERS, (
        f"No expected task identifier registered for version {TASK_IDENTIFIER_VERSION}. "
        f"Run this test to get the computed value and add it to _EXPECTED_TASK_IDENTIFIERS."
    )

    resolved_task = _create_resolved_task_with_all_fields()
    eval_set_args = EvalSetArgsInTaskIdentifier(
        config=GenerateConfig(temperature=0.7),
        message_limit=100,
        token_limit=5000,
        time_limit=300,
        working_limit=200,
        cost_limit=1.5,
    )

    identifier = task_identifier(resolved_task, eval_set_args)
    assert identifier == _EXPECTED_TASK_IDENTIFIERS[TASK_IDENTIFIER_VERSION], (
        f"Task identifier for version {TASK_IDENTIFIER_VERSION} has changed! "
        f"Expected: {_EXPECTED_TASK_IDENTIFIERS[TASK_IDENTIFIER_VERSION]}\n"
        f"Got:      {identifier}\n"
        f"If this is intentional, bump TASK_IDENTIFIER_VERSION and add a new entry."
    )
