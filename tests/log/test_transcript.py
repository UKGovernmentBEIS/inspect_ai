import json
import math
import pathlib
import zipfile
from datetime import datetime

from inspect_ai.log import read_eval_log_async, write_eval_log_async
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSample, EvalSpec
from inspect_ai.log._transcript import ScoreEvent, transcript
from inspect_ai.scorer import Score


async def test_transcript(tmp_path: pathlib.Path):
    score_event = ScoreEvent(
        score=Score(value=math.nan, target="Hello, world!"),
        target="Hello, world!",
        intermediate=True,
    )
    transcript_obj = transcript()
    transcript_obj._event(score_event)
    eval_log = EvalLog(
        samples=[
            EvalSample(
                id="1",
                epoch=1,
                input="Hello, world!",
                target="Hello, world!",
                events=list(transcript_obj.events),
            )
        ],
        eval=EvalSpec(
            dataset=EvalDataset(
                name="test",
                samples=1,
            ),
            solver="test",
            model="mockllm/model",
            created=datetime.now().isoformat(),
            task="test",
            config=EvalConfig(),
        ),
    )
    output_path = tmp_path / "test.eval"
    await write_eval_log_async(eval_log, output_path)

    assert isinstance(score_event.score.value, float)
    assert math.isnan(score_event.score.value)

    eval_log_read = await read_eval_log_async(output_path)

    assert eval_log_read.samples is not None
    score_event_read = next(
        event
        for event in eval_log_read.samples[0].transcript.events
        if event.event == "score"
    )
    score_value = score_event_read.score.value
    assert isinstance(score_value, float)
    assert math.isnan(score_value)

    with zipfile.ZipFile(output_path, "r") as zip_file:
        with zip_file.open("samples/1_epoch_1.json") as file:
            sample_json = file.read()

    assert b"NaN" in sample_json
    sample_read_raw = json.loads(sample_json)

    score_events = [
        event for event in sample_read_raw["events"] if event.get("event") == "score"
    ]
    score_read_raw = score_events[0]["score"]["value"]
    assert score_read_raw == "NaN"
