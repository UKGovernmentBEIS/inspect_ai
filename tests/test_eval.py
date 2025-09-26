import functools
from copy import deepcopy

import pytest

from inspect_ai import Epochs, Task, eval, eval_async
from inspect_ai._util._async import tg_collect
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


@pytest.mark.anyio
async def test_no_concurrent_eval_async():
    tasks = [
        Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
        for i in range(0, 2)
    ]

    with pytest.raises(RuntimeError):
        await tg_collect(
            [
                functools.partial(eval_async, task, model="mockllm/model")
                for task in tasks
            ]
        )


def test_eval_config_override():
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        message_limit=10,
        epochs=Epochs(2, "at_least_1"),
        fail_on_error=True,
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model")[0]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["at_least_1"]
    assert log.eval.config.fail_on_error is True

    log = eval(
        deepcopy(task),
        message_limit=5,
        epochs=Epochs(5, "at_least_3"),
        fail_on_error=0.5,
        model="mockllm/model",
    )[0]
    assert log.eval.config.message_limit == 5
    assert log.eval.config.epochs == 5
    assert log.eval.config.epochs_reducer == ["at_least_3"]
    assert log.eval.config.fail_on_error == 0.5


def test_message_count_with_multiple_epochs():
    """Test that message counts work correctly with multi-epoch evaluations."""
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        epochs=2,
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.stats.sample_message_counts is not None

    key_epoch_1 = "1_1"
    key_epoch_2 = "1_2"

    assert key_epoch_1 in log.stats.sample_message_counts
    assert key_epoch_2 in log.stats.sample_message_counts

    assert log.stats.sample_message_counts[key_epoch_1] > 0
    assert log.stats.sample_message_counts[key_epoch_2] > 0
