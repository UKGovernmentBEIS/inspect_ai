from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample


def check_trace_requirement(tasks: list[Task], epochs: int = 1) -> None:
    try:
        eval(tasks, model="mockllm/model", trace=True, epochs=epochs)
        assert False
    except PrerequisiteError:
        pass
    except Exception:
        assert False


def test_trace_requires_single_task():
    check_trace_requirement(
        [Task([Sample(input="Hello")]), Task([Sample(input="World")])]
    )


def test_trace_requires_single_sample():
    check_trace_requirement([Task([Sample(input="Hello"), Sample(input="World")])])


def test_trace_requires_single_epoch():
    check_trace_requirement([Task([Sample(input="Hello")])], epochs=2)
