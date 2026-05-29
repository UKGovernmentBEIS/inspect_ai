"""Deepagent demo for exercising BACKGROUND subagent dispatch and viewer rendering.

This is the background-dispatch sibling of ``deepagent_demo.py``. Here the
parent fans three competitor investigations out *in the background* (each
returns an ``AGENT-N`` handle immediately), does independent work while they
run, inspects them with the lifecycle tools (``agent_list`` / ``agent_status``),
cancels one that's out of scope (``agent_cancel``), and finally blocks on the
rest (``agent_wait``) before synthesizing.

Each subagent has its own mockllm instance so its scripted trajectory is
self-contained and deterministic regardless of the (now concurrent) dispatch
order. The parent has a fourth mockllm that orchestrates dispatch and the
lifecycle calls. A ``slow_work`` tool uses ``anyio.sleep`` so the background
subagents take real wall-clock time — that's what makes the dispatch genuinely
concurrent and makes the in-flight agents show up as overlapping open spans in
the viewer (and gives ``agent_status`` something live to peek at).

Run:
    inspect eval examples/deepagent_background_demo.py

Then open the resulting log in Inspect View. Things to look for:
  * Three ``agent: research_*`` spans that *overlap* in the timeline (they run
    concurrently rather than one-after-another), alongside the parent's own
    continuing activity.
  * Lifecycle tool calls on the parent: ``agent_list``, ``agent_status: AGENT-1``,
    ``agent_cancel: AGENT-3``, ``agent_wait: AGENT-1, AGENT-2 (all)``.
  * AGENT-3 (Gamma) rendered as **cancelled**; AGENT-1/AGENT-2 as **completed**.
  * Each subagent's interior ``slow_work`` / ``think`` trajectory.
"""

import uuid
from typing import Any

import anyio

from inspect_ai import Task, task
from inspect_ai._util.content import ContentText
from inspect_ai.agent import deepagent, subagent
from inspect_ai.dataset import Sample
from inspect_ai.model import Model, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool import Tool, ToolCall, think, tool


def _output(narration: str, *tool_calls: ToolCall) -> ModelOutput:
    """Build a ModelOutput with rich text content + zero-or-more tool calls.

    Uses a typed ``[ContentText(...)]`` content list so the message shape
    matches what a real frontier model would emit.
    """
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[ContentText(text=narration)],
                    model="mockllm/model",
                    source="generate",
                    tool_calls=list(tool_calls) if tool_calls else None,
                ),
                stop_reason="tool_calls" if tool_calls else "stop",
            )
        ],
    )


def _call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(
        id=f"call_{uuid.uuid4().hex[:8]}",
        function=name,
        arguments=arguments,
    )


@tool
def slow_work() -> Tool:
    """A unit of work that actually takes time (so background runs overlap)."""

    async def execute(step: str, seconds: float = 3.0) -> str:
        """Simulate a slow unit of work.

        Args:
            step: Short description of the work being performed.
            seconds: How long the work takes (wall-clock seconds).
        """
        await anyio.sleep(seconds)
        return f"Completed: {step}"

    return execute


# ---------------------------------------------------------------------------
# Background subagents — one mockllm each, each parks in slow_work so the three
# investigations genuinely run in parallel under the sample.
# ---------------------------------------------------------------------------


def _alpha_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Pulling Alpha's public pricing pages and recent launch notes.",
                _call("slow_work", step="scrape Alpha pricing", seconds=3),
            ),
            _output(
                "Cross-checking Alpha against analyst coverage and reviews.",
                _call("think", thought="Alpha skews premium; thin SMB story."),
            ),
            _output(
                "Alpha picture is clear — reporting back.",
                _call(
                    "submit",
                    answer=(
                        "Alpha: premium pricing, strong enterprise positioning, "
                        "weak SMB/self-serve offering."
                    ),
                ),
            ),
        ],
    )


def _beta_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Gathering Beta's pricing tiers and packaging.",
                _call("slow_work", step="scrape Beta pricing", seconds=4),
            ),
            _output(
                "Comparing Beta's positioning to Alpha's.",
                _call(
                    "slow_work", step="analyze Beta positioning", seconds=2
                ),
            ),
            _output(
                "Beta synthesis done — reporting back.",
                _call(
                    "submit",
                    answer=(
                        "Beta: aggressive mid-market pricing, fast-moving, but "
                        "shallow enterprise security/compliance story."
                    ),
                ),
            ),
        ],
    )


def _gamma_model() -> Model:
    # Gamma takes a long time and will be cancelled mid-flight by the parent,
    # so it never reaches submit — it shows up as 'cancelled' in the viewer.
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Starting the deep Gamma teardown (this one is slow).",
                _call("slow_work", step="full Gamma teardown", seconds=30),
            ),
            _output(
                "Should not reach here — Gamma is expected to be cancelled.",
                _call("submit", answer="Gamma: (unreached)"),
            ),
        ],
    )


def _research_subagent(name: str, competitor: str, model: Model):
    return subagent(
        name=name,
        description=f"Researches competitor {competitor}.",
        prompt=(
            f"You research competitor {competitor}. Use slow_work to do the "
            "investigation, then submit a concise findings summary."
        ),
        model=model,
        tools=[slow_work(), think()],
    )


# ---------------------------------------------------------------------------
# Parent orchestrator — dispatches all three in the background, works while
# they run, inspects/cancels/waits, then synthesizes.
# ---------------------------------------------------------------------------


def _parent_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Recording the goal so the report has shared context to refer to.",
                _call(
                    "memory",
                    command="create",
                    path="/memories/goal.md",
                    file_text=(
                        "Goal: competitive analysis of Alpha, Beta, Gamma; "
                        "then synthesize a recommendation."
                    ),
                ),
            ),
            _output(
                "Laying out the plan as todos before I fan out the research.",
                _call(
                    "todo_write",
                    todos=[
                        {"content": "Research Alpha", "status": "in_progress"},
                        {"content": "Research Beta", "status": "in_progress"},
                        {"content": "Research Gamma", "status": "in_progress"},
                        {"content": "Draft report outline", "status": "pending"},
                        {"content": "Synthesize findings", "status": "pending"},
                    ],
                ),
            ),
            # --- fan out three background dispatches (each returns immediately) ---
            _output(
                "Kicking off Alpha's investigation in the background so it runs "
                "while I set up the others.",
                _call(
                    "agent",
                    subagent_type="research_alpha",
                    prompt="Research competitor Alpha's pricing and positioning.",
                    task_description="Research Alpha",
                    background=True,
                ),
            ),
            _output(
                "Beta next — also in the background.",
                _call(
                    "agent",
                    subagent_type="research_beta",
                    prompt="Research competitor Beta's pricing and positioning.",
                    task_description="Research Beta",
                    background=True,
                ),
            ),
            _output(
                "And Gamma — background as well. All three now run in parallel.",
                _call(
                    "agent",
                    subagent_type="research_gamma",
                    prompt="Research competitor Gamma's pricing and positioning.",
                    task_description="Research Gamma",
                    background=True,
                ),
            ),
            # --- independent work while they run ---
            _output(
                "While the three investigations run, I'll sketch the report "
                "outline so I'm ready to synthesize.",
                _call(
                    "think",
                    thought=(
                        "Outline: 1) pricing 2) positioning 3) gaps "
                        "4) recommendation."
                    ),
                ),
            ),
            # --- inspect what's in flight ---
            _output(
                "Let me see what's still in flight before going further.",
                _call("agent_list"),
            ),
            _output(
                "Peeking at Alpha's progress specifically.",
                _call("agent_status", agent_id="AGENT-1"),
            ),
            # --- cancel the one that's out of scope ---
            _output(
                "On reflection, Gamma is out of scope for this report — "
                "cancelling it to stop wasting work and free the slot.",
                _call("agent_cancel", agent_id="AGENT-3"),
            ),
            # --- block on the two we actually need ---
            _output(
                "Now I genuinely need Alpha and Beta before I can synthesize. "
                "Waiting for both to finish.",
                _call(
                    "agent_wait",
                    agent_ids=["AGENT-1", "AGENT-2"],
                    mode="all",
                ),
            ),
            # --- wrap up ---
            _output(
                "Both are in. Marking research complete and writing the synthesis.",
                _call(
                    "todo_write",
                    todos=[
                        {"content": "Research Alpha", "status": "completed"},
                        {"content": "Research Beta", "status": "completed"},
                        {
                            "content": "Research Gamma (cancelled — out of scope)",
                            "status": "completed",
                        },
                        {"content": "Draft report outline", "status": "completed"},
                        {"content": "Synthesize findings", "status": "in_progress"},
                    ],
                ),
            ),
            _output(
                "Report is ready. Submitting the competitive analysis.",
                _call(
                    "submit",
                    answer=(
                        "Competitive analysis (Gamma cut as out of scope):\n"
                        "- Alpha: premium, enterprise-strong, weak SMB.\n"
                        "- Beta: aggressive mid-market, weak enterprise compliance.\n"
                        "Recommendation: position between them — mid-market pricing "
                        "with a credible enterprise security story."
                    ),
                ),
            ),
        ],
    )


@task
def deepagent_background_demo() -> Task:
    subagents = [
        _research_subagent("research_alpha", "Alpha", _alpha_model()),
        _research_subagent("research_beta", "Beta", _beta_model()),
        _research_subagent("research_gamma", "Gamma", _gamma_model()),
    ]

    agent = deepagent(
        model=_parent_model(),
        subagents=subagents,
        background=True,
        submit=True,
    )

    return Task(
        dataset=[
            Sample(
                input=(
                    "Produce a competitive analysis of Alpha, Beta, and Gamma. "
                    "Research them in parallel, then synthesize a recommendation."
                )
            )
        ],
        solver=agent,
        message_limit=80,
    )
