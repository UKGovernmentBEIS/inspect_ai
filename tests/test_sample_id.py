from inspect_ai import Task, eval
from inspect_ai.dataset import Sample


def test_sample_id():
    task = Task(dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 10)])
    log = eval(task, sample_id=5, model="mockllm/model")[0]
    assert len(log.samples) == 1
    assert log.samples[0].id == 5

    log = eval(task, sample_id=[5, 9], model="mockllm/model")[0]
    assert len(log.samples) == 2
    assert log.samples[0].id == 5
    assert log.samples[1].id == 9

    task = Task(
        dataset=[
            Sample(id=f"sample-{id}", input=f"Input for {id}") for id in range(0, 10)
        ]
    )
    log = eval(task, sample_id="sample-5", model="mockllm/model")[0]
    assert len(log.samples) == 1
    assert log.samples[0].id == "sample-5"

    log = eval(task, sample_id=["sample-5", "sample-6"], model="mockllm/model")[0]
    assert len(log.samples) == 2
    assert log.samples[0].id == "sample-5"
    assert log.samples[1].id == "sample-6"
