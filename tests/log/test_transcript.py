import datetime
import json
import math
import pathlib
import zipfile

import inspect_ai.log
import inspect_ai.log._log
import inspect_ai.log._transcript


async def test_transcript(tmp_path: pathlib.Path):
    score_event = inspect_ai.log._transcript.ScoreEvent(
        score=inspect_ai.log._log.Score(value=math.nan, target="Hello, world!"),
        target="Hello, world!",
        intermediate=True,
    )
    transcript = inspect_ai.log._transcript.transcript()
    transcript._event(score_event)
    eval_log = inspect_ai.log._log.EvalLog(
        samples=[
            inspect_ai.log._log.EvalSample(
                id="1",
                epoch=1,
                input="Hello, world!",
                target="Hello, world!",
                events=list(transcript.events),
            )
        ],
        eval=inspect_ai.log._log.EvalSpec(
            dataset=inspect_ai.log._log.EvalDataset(
                name="test",
                samples=1,
            ),
            solver="test",
            model="mockllm/model",
            created=datetime.datetime.now().isoformat(),
            task="test",
            config=inspect_ai.log._log.EvalConfig(),
        ),
    )
    output_path = tmp_path / "test.eval"
    await inspect_ai.log.write_eval_log_async(eval_log, output_path)

    assert isinstance(score_event.score.value, float)
    assert math.isnan(score_event.score.value)

    eval_log_read = await inspect_ai.log.read_eval_log_async(output_path)

    assert eval_log_read.samples is not None
    score_event_read = eval_log_read.samples[0].transcript.events[0]
    assert score_event_read.event == "score"
    score_value = score_event_read.score.value
    assert isinstance(score_value, float)
    assert math.isnan(score_value)

    with zipfile.ZipFile(output_path, "r") as zip_file:
        with zip_file.open("samples/1_epoch_1.json") as file:
            sample_json = file.read()

    assert b"NaN" in sample_json
    sample_read_raw = json.loads(sample_json)

    score_read_raw = sample_read_raw["events"][0]["score"]["value"]
    assert score_read_raw == "NaN"
