"""ACP test helpers shared across test directories."""

from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._transcript import Transcript
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer


def acp_test_active_sample(transcript: Transcript) -> ActiveSample:
    """Bare ``ActiveSample`` for tests that drive ``react()`` directly.

    ``react()`` opens ``checkpointer()``, which reads the active sample.
    Tests that use it exercise react() or tool execution outside the real eval
    harness, so they publish this bare ``ActiveSample`` (carrying a
    ``_NoopCheckpointer`` and the test's own transcript) on the
    ``_sample_active`` ContextVar.

    Manually constructs a :class:`LiveAcpTransport` and wires it onto the
    sample (``acp_session`` for ``current_acp_transport()`` fallback;
    ``execution_observer`` for in-flight tool/model tracking) so tests
    that don't go through the real ``active_sample()`` context still
    see the same producer surface as production.
    """
    sample = ActiveSample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(id=1, input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=transcript,
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_id="eval-1",
        sample_uuid="sample-uuid-1",
    )
    # Wire a bare LiveAcpTransport onto the sample. We deliberately skip
    # __aenter__ ceremony (router attach, pubsub setup) — tests that
    # need those exercise the full path; this fixture provides just the
    # producer surface needed by react() and the in-flight tracking
    # path.
    session = LiveAcpTransport()
    session._attachable_override = True
    session._transcript_capture.captured = transcript
    sample.acp_transport = session
    sample.execution_observer = session
    return sample
