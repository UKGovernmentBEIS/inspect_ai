"""Scorers tag a completion that produced nothing with ScoreReason no_response.

Fixes #5376. Empty and whitespace-only completions are now distinguishable from
wrong answers. No score VALUE changes, which the last test pins.
"""

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import Score, answer, exact, f1, includes, match, pattern

EMPTY = ["", "   ", "\n\t "]


def score_once(scorer, completion: str, target: str = "4") -> Score:
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", completion)],
    )
    task = Task(
        dataset=[Sample(input="What is 2+2?", target=target)],
        scorer=scorer,
    )
    log = eval(task, model=model, display="none")[0]
    assert log.samples
    assert log.samples[0].scores is not None
    return list(log.samples[0].scores.values())[0]


def string_scorers():
    return [
        ("match", match()),
        ("includes", includes()),
        ("exact", exact()),
        ("f1", f1()),
    ]


def pattern_scorers():
    return [("pattern", pattern(r"(\d+)")), ("answer", answer("line"))]


@pytest.mark.parametrize("name,scorer", string_scorers() + pattern_scorers())
@pytest.mark.parametrize("completion", EMPTY)
def test_empty_completion_is_no_response(name, scorer, completion):
    assert score_once(scorer, completion).reason == "no_response"


@pytest.mark.parametrize("name,scorer", string_scorers())
def test_wrong_answer_carries_no_reason(name, scorer):
    # A real wrong answer is a verdict, not an abnormality. Without this the
    # change could pass by tagging everything, which is the failure mode a
    # handled-path-only suite cannot see.
    assert score_once(scorer, "5").reason is None


@pytest.mark.parametrize("name,scorer", pattern_scorers())
def test_unparseable_non_empty_is_still_invalid_response_format(name, scorer):
    assert score_once(scorer, "I have no idea").reason == "invalid_response_format"


def test_refusal_is_not_claimed_by_string_scorers():
    # A string scorer cannot see a refusal: "I cannot answer" is just text, and
    # detecting one needs finish-reason or content-filter metadata the scorer
    # does not read. Out of scope here on purpose, and pinned so a later change
    # cannot quietly start guessing.
    for _, scorer in string_scorers():
        assert score_once(scorer, "I cannot answer this question.").reason is None


@pytest.mark.parametrize(
    "name,scorer,completion,expected",
    [
        ("match", match(), "4", "C"),
        ("includes", includes(), "4", "C"),
        ("exact", exact(), "4", "C"),
        ("match", match(), "5", "I"),
        ("pattern", pattern(r"(\d+)"), "4", "C"),
        ("answer", answer("line"), "ANSWER: 4", "C"),
    ],
)
def test_no_value_changed(name, scorer, completion, expected):
    assert score_once(scorer, completion).value == expected


@pytest.mark.parametrize(
    "name,scorer,completion",
    [
        # The EXTRACTED answer is empty while the RAW completion is not. The
        # maintainer's acceptance is explicit: "Empty extracted or normalized
        # answers must not be treated as empty raw completions." So this is spec.
        #
        # These cases are chosen because they DISCRIMINATE. An earlier version of
        # this test used plain non-matching prose, which passes either way: for
        # exact() and f1() with default settings the extracted answer IS the raw
        # completion, so moving the check onto the answer changed nothing and the
        # mutation stayed green.
        # match(numeric=True) yields answer="" from first_number_normalized
        # whenever the completion holds no number, so a NON-empty completion
        # produces an empty extracted answer. Without this row the forbidden
        # implementation in _common.py passes the entire suite: the f1 rows
        # below only cover _classification.py.
        (
            "match numeric, no number in real prose",
            match(numeric=True),
            "I do not know",
        ),
        ("pattern, nullable group matches empty", pattern(r"(\d*)"), "abc"),
        ("answer, ANSWER: with nothing after it", answer("line"), "ANSWER:  "),
        (
            "f1, extractor returns empty",
            f1(answer_fn=lambda c: ""),
            "some real prose here",
        ),
        (
            "f1, extractor returns whitespace",
            f1(answer_fn=lambda c: "   "),
            "some real prose here",
        ),
    ],
)
def test_empty_extracted_answer_is_not_no_response(name, scorer, completion):
    assert score_once(scorer, completion).reason != "no_response"


@pytest.mark.parametrize(
    "scoring_pattern,completion",
    [
        # A NULLABLE pattern matches at position 0 of an empty string, so these
        # take pattern()'s `if match:` path rather than the no-match path. The
        # first version of this change only touched the no-match branch, so all
        # of these returned reason=None while the non-nullable cases above were
        # tagged. One scorer, three answers, three whitespace-only completions.
        (r"(.*)", ""),
        (r"(\d*)", "   "),
        (r"(\w*)", "\n\t "),
        (r"^(.*)$", ""),
        (r"^(.*)$", "\n\t "),
        (r"([A-Z]?)", ""),
    ],
)
def test_nullable_pattern_on_empty_completion_is_no_response(
    scoring_pattern, completion
):
    assert score_once(pattern(scoring_pattern), completion).reason == "no_response"


@pytest.mark.parametrize(
    "name,scorer,target",
    [
        # THE CORRECT RETURN, not the incorrect one. str_match_scorer has two
        # exits and the first version of this change only tagged the second, so
        # an empty completion that happened to score CORRECT carried no reason.
        #
        # match() with a target of "." normalizes that target to empty under
        # ignore_punctuation, and "".endswith("") is True. includes() with an
        # empty target is contained in anything. Both grade a completion the
        # model never produced as CORRECT, which is exactly the state the tag
        # exists to make visible.
        ("match, target normalizes to empty", match(), "."),
        ("includes, empty target", includes(), ""),
    ],
)
@pytest.mark.parametrize("completion", EMPTY)
def test_empty_completion_scoring_correct_is_still_no_response(
    name, scorer, target, completion
):
    score = score_once(scorer, completion, target=target)
    # The VALUE is preserved. The accepted scope tags a raw-empty completion
    # regardless of the score it ended up with, so this stays CORRECT and only
    # gains a reason. A version that flipped it to INCORRECT would be a scoring
    # change, which this PR promises not to make.
    assert score.value == "C"
    assert score.reason == "no_response"
