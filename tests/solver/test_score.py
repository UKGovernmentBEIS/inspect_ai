from inspect_ai import Task, eval, task
from inspect_ai._eval.task.task import task_with
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.scorer import Score, includes
from inspect_ai.solver import Generate, TaskState, solver
import pytest
from inspect_ai.scorer._score import score
from inspect_ai.solver import TaskState
from inspect_ai.scorer._score import init_scoring_context
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._target import Target
from inspect_ai.scorer._score import score, init_scoring_context

@solver
def solver_with_score(score_name: str, score_value: float):
    async def solve(state: TaskState, _generate: Generate):
        state.scores = {score_name: Score(value=score_value)}
        return state
    return solve
@task
def scoring_task():
    return Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=solver_with_score("foo", 0.6),
    )
def check_scoring_log(log: EvalLog, scores: dict[str, float]):
    assert log.status == "success"
    assert log.results
    for scorer, value in scores.items():
        eval_score = next(
            (es for es in log.results.scores if es.scorer == scorer), None
        )
        assert eval_score
        assert eval_score.metrics["accuracy"].value == value
def test_solver_scoring():
    log = eval(scoring_task(), model="mockllm/model")[0]
    check_scoring_log(log, {"foo": 0.6})
def test_solver_scoring_ammend():
    task = task_with(scoring_task(), scorer=includes())
    log = eval(task, model="mockllm/model")[0]
    check_scoring_log(log, {"foo": 0.6, "includes": 0})
@pytest.mark.asyncio
async def test_score_without_scoring_context():
    """
    Tests that calling score() outside of a scoring context
    raises a RuntimeError.
    """
    state = TaskState()  # Create a dummy TaskState instance
    with pytest.raises(RuntimeError) as excinfo:
        await score(state)
    assert "The score() function can only be called while executing a task with a scorer." in str(excinfo.value)
@pytest.mark.asyncio
async def test_score_without_scoring_context():
    """
    Tests that calling score() outside of a scoring context raises a RuntimeError.
    The TaskState instance is created with dummy arguments to satisfy its initializer.
    """
    state = TaskState(model="dummy", sample_id="dummy", epoch=0, input="dummy", messages=[])
    with pytest.raises(RuntimeError) as excinfo:
        await score(state)
    assert "The score() function can only be called while executing a task with a scorer." in str(excinfo.value)
@pytest.mark.asyncio
async def test_score_with_valid_scoring_context():
    """
    Test that score() returns the expected score when executed within a valid scoring context.
    It sets up a dummy scorer that returns a fixed Score and uses a dummy target.
    """
    # Define a dummy scorer that returns a Score with a fixed value.
    async def dummy_scorer(state, target):
        return Score(value=42)
    # Define a dummy target by subclassing Target with the required attribute.
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("dummy_target")
    # Initialize the scoring context with the dummy scorer and dummy target.
    init_scoring_context([dummy_scorer], dummy_target)
    # Create a dummy TaskState instance with required dummy arguments.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=1, input="dummy", messages=[])
    # Call score() and validate that the returned list contains the expected score.
    scores = await score(state)
    assert isinstance(scores, list)
    assert len(scores) == 1
    assert scores[0].value == 42
@pytest.mark.asyncio
async def test_score_multiple_scorers_logs(monkeypatch):
    """
    Test that score() correctly executes multiple scorers and logs an event for each scorer.
    This test sets up a dummy scoring context with two scorers returning distinct Score values,
    patches the transcript() function to record events, and then validates that the returned scores 
    and logged transcript events are as expected.
    """
    # Create a dummy transcript object that collects events.
    class DummyTranscript:
        def __init__(self):
            self.events = []
        def _event(self, event):
            self.events.append(event)
    
    dummy_transcript = DummyTranscript()
    # Monkey-patch the transcript() function in the inspect_ai.log._transcript module.
    import inspect_ai.log._transcript as log_transcript
    monkeypatch.setattr(log_transcript, "transcript", lambda: dummy_transcript)
    # Define two dummy scorers that return distinct Score values.
    async def scorer1(state, target):
        return Score(value=11)
    
    async def scorer2(state, target):
        return Score(value=22)
    # Define a dummy target by subclassing Target with a necessary 'target' attribute.
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("dummy_target_value")
    # Initialize the scoring context with the two dummy scorers and the dummy target.
    init_scoring_context([scorer1, scorer2], dummy_target)
    # Create a dummy TaskState instance with required dummy arguments.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=1, input="dummy", messages=[])
    # Call score() and get the scores.
    scores = await score(state)
    # Validate that the returned scores list contains two Score objects with the expected values.
    assert isinstance(scores, list)
    assert len(scores) == 2
    scorer_values = {score.value for score in scores}
    assert scorer_values == {11, 22}
    # Validate that two transcript events were logged.
    assert len(dummy_transcript.events) == 2
    # Check each event to ensure it logs the expected target and that intermediate is True.
    for event in dummy_transcript.events:
        assert hasattr(event, "target")
        assert event.target == "dummy_target_value"
        assert hasattr(event, "score")
        assert hasattr(event, "intermediate")
        assert event.intermediate is True
    # Optionally, check that each event is an instance of ScoreEvent.
    from inspect_ai.log._transcript import ScoreEvent
    for event in dummy_transcript.events:
        assert isinstance(event, ScoreEvent)
@pytest.mark.asyncio
async def test_score_with_empty_scorers_list():
    """
    Test that score() returns an empty list when the scoring context is initialized with an empty scorers list.
    This ensures that even with a valid target, if no scorer is provided, score() does not perform any logging
    or scoring and simply returns an empty list.
    """
    # Define a dummy target by subclassing Target with a required attribute.
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("dummy_value")
    # Initialize the scoring context with an empty list of scorers.
    init_scoring_context([], dummy_target)
    # Create a dummy TaskState instance with required dummy arguments.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=0, input="dummy", messages=[])
    # Call score() and check it returns an empty list.
    scores = await score(state)
    assert isinstance(scores, list)
    assert len(scores) == 0
@pytest.mark.asyncio
async def test_score_scorer_exception_propagates():
    """
    Test that if a scorer raises an exception, the exception is propagated.
    This ensures that score() does not catch errors thrown by scorer functions.
    """
    # Define a dummy scorer that always raises an exception.
    async def failing_scorer(state, target):
        raise ValueError("Dummy scorer error")
    # Define a dummy target by subclassing Target with a required 'target' attribute.
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("dummy_target")
    # Initialize the scoring context with the failing scorer.
    init_scoring_context([failing_scorer], dummy_target)
    state = TaskState(model="dummy_model", sample_id="dummy_id", epoch=0, input="dummy", messages=[])
    # Calling score() should propagate the ValueError raised by failing_scorer.
    with pytest.raises(ValueError, match="Dummy scorer error"):
        await score(state)
@pytest.mark.asyncio
async def test_reinitialize_scoring_context():
    """
    Test that reinitializing the scoring context overrides the previous scorers.
    This test first sets a dummy scorer that returns Score(value=100) and then
    reinitializes the scoring context with another dummy scorer that returns Score(value=200).
    It verifies that score() uses the most recently set scorer.
    """
    # Define a dummy target by subclassing Target.
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("test_target")
    
    # Define two dummy scorers that return different Score values.
    async def dummy_scorer1(state, target):
        return Score(value=100)
    
    async def dummy_scorer2(state, target):
        return Score(value=200)
    
    # Create a dummy TaskState instance with the minimal required parameters.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=1, input="dummy", messages=[])
    # Initialize the scoring context with dummy_scorer1 and validate the returned score.
    init_scoring_context([dummy_scorer1], dummy_target)
    scores1 = await score(state)
    assert isinstance(scores1, list)
    assert len(scores1) == 1
    assert scores1[0].value == 100
    # Reinitialize the scoring context with dummy_scorer2 and validate that the new scorer is used.
    init_scoring_context([dummy_scorer2], dummy_target)
    scores2 = await score(state)
    assert isinstance(scores2, list)
    assert len(scores2) == 1
    assert scores2[0].value == 200from contextvars import ContextVar
import pytest
from inspect_ai.scorer._score import score, _scorers, _target
from inspect_ai.scorer._metric import Score
from inspect_ai.solver import TaskState


@pytest.mark.asyncio
async def test_score_incomplete_context(monkeypatch):
    """
    Test that score() raises a RuntimeError when either the '_scorers' or the 'target'
    context variable is missing. This covers scenarios where only one of the context
    variables is initialized.
    """
    # Define a dummy scorer that would normally return a valid score.
    async def dummy_scorer(state, target):
        return Score(value=1)

    # Define a dummy target with the required 'target' attribute.
    class DummyTarget:
        def __init__(self, target_value: str):
            self.target = target_value
    dummy_target = DummyTarget("dummy_target")

    # Create a dummy TaskState instance with the minimal required parameters.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=0, input="dummy", messages=[])

    # Scenario 1: _scorers is set, but _target is missing.
    # Monkey-patch _target.get to always return None even if a value was set.
    monkeypatch.setattr(_target, "get", lambda default: None)
    # Set _scorers properly
    _scorers.set([dummy_scorer])
    with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
        await score(state)

    # Scenario 2: _target is set, but _scorers is missing.
    # Monkey-patch _scorers.get to always return None.
    monkeypatch.setattr(_scorers, "get", lambda default: None)
    # Ensure _target.get returns our dummy target.
    monkeypatch.setattr(_target, "get", lambda default: dummy_target)
    with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
        await score(state)
import pytest
from contextvars import ContextVar
from inspect_ai.scorer._score import score, _scorers, _target
from inspect_ai.scorer._metric import Score
from inspect_ai.solver import TaskState


@pytest.mark.asyncio
async def test_score_incomplete_context():
    """
    Test that score() raises a RuntimeError when either the '_scorers'
    or the 'target' context variable is missing.
    
    Scenario 1: Only _scorers is set (with a dummy scorer) so _target.get(None) returns None.
    Scenario 2: Only _target is set (with a dummy target) so _scorers.get(None) returns None.
    In both cases, score() should raise a RuntimeError.
    """
    # Define a dummy scorer that would normally return a valid score.
    async def dummy_scorer(state, target):
        return Score(value=1)

    # Define a dummy target with the required 'target' attribute.
    class DummyTarget:
        def __init__(self, target_value: str):
            self.target = target_value

    dummy_target = DummyTarget("dummy_target")

    # Create an example TaskState instance.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=0, input="dummy", messages=[])

    # Scenario 1: _scorers is set, but _target is not set.
    token_scorers = _scorers.set([dummy_scorer])
    try:
        with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
            await score(state)
    finally:
        _scorers.reset(token_scorers)

    # Scenario 2: _target is set, but _scorers is not set.
    token_target = _target.set(dummy_target)
    try:
        with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
            await score(state)
    finally:
        _target.reset(token_target)
import pytest
from inspect_ai.scorer._score import score, init_scoring_context, _scorers, _target
from inspect_ai.scorer._metric import Score
from inspect_ai.solver import TaskState


@pytest.mark.asyncio
async def test_reinitialize_scoring_context():
    """
    Test that reinitializing the scoring context overrides the previous scorers.
    
    This test first sets a dummy scorer that returns Score(value=100) and then reinitializes 
    the scoring context with another dummy scorer that returns Score(value=200). 
    It verifies that score() uses the most recently set scorer.
    """
    # Import the Target base class from the original source.
    from inspect_ai.scorer._target import Target
    class DummyTarget(Target):
        def __init__(self, target_value: str):
            self.target = target_value

    dummy_target = DummyTarget("test_target")
    
    # Define two dummy scorers that return different Score values.
    async def dummy_scorer1(state, target):
        return Score(value=100)
    
    async def dummy_scorer2(state, target):
        return Score(value=200)
    
    # Create a dummy TaskState instance with the minimal required parameters.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=1, input="dummy", messages=[])
    
    # Initialize the scoring context with dummy_scorer1 and validate the returned score.
    init_scoring_context([dummy_scorer1], dummy_target)
    scores1 = await score(state)
    assert isinstance(scores1, list)
    assert len(scores1) == 1
    assert scores1[0].value == 100
    
    # Reinitialize the scoring context with dummy_scorer2 and validate that the new scorer is used.
    init_scoring_context([dummy_scorer2], dummy_target)
    scores2 = await score(state)
    assert isinstance(scores2, list)
    assert len(scores2) == 1
    assert scores2[0].value == 200  # Fixed: removed the accidental appended text


@pytest.mark.asyncio
async def test_score_incomplete_context():
    """
    Test that score() raises a RuntimeError when either the '_scorers'
    or the 'target' context variable is missing.
    
    Scenario 1: Only _scorers is set, so _target.get(None) returns None.
    Scenario 2: Only _target is set, so _scorers.get(None) returns None.
    In both cases, score() should raise a RuntimeError.
    """
    # Define a dummy scorer that would normally return a valid score.
    async def dummy_scorer(state, target):
        return Score(value=1)

    # Define a dummy target with the required 'target' attribute.
    class DummyTarget:
        def __init__(self, target_value: str):
            self.target = target_value

    dummy_target = DummyTarget("dummy_target")
    
    # Create an example TaskState instance.
    state = TaskState(model="dummy_model", sample_id="dummy", epoch=0, input="dummy", messages=[])
    
    # Scenario 1: _scorers is set, but _target is not set.
    token_scorers = _scorers.set([dummy_scorer])
    try:
        with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
            await score(state)
    finally:
        _scorers.reset(token_scorers)
    
    # Scenario 2: _target is set, but _scorers is not set.
    token_target = _target.set(dummy_target)
    try:
        with pytest.raises(RuntimeError, match="The score\\(\\) function can only be called while executing a task with a scorer."):
            await score(state)
    finally:
        _target.reset(token_target)
