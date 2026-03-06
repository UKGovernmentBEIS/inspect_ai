from test_helpers.tasks import popularity

from inspect_ai import eval, score
from inspect_ai._util.dateutil import iso_now
from inspect_ai.log import EvalSample, read_eval_log, write_eval_log
from inspect_ai.model import ChatMessageUser, ModelOutput

TEST_MODEL = "mockllm/model"


def test_eval_no_samples():
    # run with no samples
    log = eval(popularity(), model=TEST_MODEL, run_samples=False)[0]
    assert log.status == "started"
    assert len(log.samples) == 0


def test_eval_log_no_samples_ammend_and_score():
    # load task
    task = popularity()

    # eval w/o running to create log
    log = eval(task, model=TEST_MODEL, run_samples=False)[0]

    # 'run' samples and provide output/messages
    log.samples = []
    for epoch in range(0, task.epochs or 1):
        for sample in task.dataset:
            input = (
                [ChatMessageUser(content=sample.input)]
                if isinstance(sample.input, str)
                else sample.input
            )
            output = ModelOutput.from_content(TEST_MODEL, "Yes")
            messages = input + [output.message]
            log.samples.append(
                EvalSample(
                    id=sample.id,
                    epoch=epoch,
                    input=sample.input,
                    target=sample.target,
                    choices=sample.choices,
                    metadata=sample.metadata,
                    sandbox=sample.sandbox,
                    files=list(sample.files.keys()) if sample.files else None,
                    setup=sample.setup,
                    # the above are just relayed from the sample, these are
                    # a result of 'running' the sample
                    messages=messages,
                    output=output,
                )
            )
    # mark completed
    log.status = "success"
    log.stats.completed_at = iso_now()

    # score the log and write it
    if task.scorer:
        log = score(log, task.scorer)
        write_eval_log(log)

    # re-read and verify all is well
    log = read_eval_log(log.location)
    assert log.status == "success"
    assert len(log.samples) == (task.epochs or 1) * len(task.dataset)
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value > 0
