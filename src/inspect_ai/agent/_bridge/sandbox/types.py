import inspect
from collections import deque
from dataclasses import dataclass, field, replace
from logging import getLogger
from os.path import commonprefix
from typing import TYPE_CHECKING, Any, Callable, Mapping, NamedTuple, Sequence

import anyio
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import json_equal
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.bridge import resolve_forward_client_headers
from inspect_ai.agent._bridge.types import (
    AgentBridge,
    DispatchedCall,
    ReviewedCalls,
    _HandedCall,
    _unchanged,
)
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._message_ids import canonical_tool_arguments
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
    ModelResponseFilter,
)
from inspect_ai.tool import Tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._checkpoint.checkpointer import Checkpointer
from inspect_ai.util._limit import LimitExceededError

if TYPE_CHECKING:
    # deferred: importing `inspect_ai.approval` at module scope here cycles
    # through approval -> event -> scorer while `inspect_ai.agent` is still
    # initializing. Same reason `model/_call_tools.py` defers it.
    from inspect_ai.approval._policy import ApprovalPolicy


logger = getLogger(__name__)

_MAX_TOOL_EXECUTION_GRANTS = 1024


class SandboxAgentBridge(AgentBridge):
    """Sandbox agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None,
        retry_refusals: int | None,
        compaction: CompactionStrategy | None,
        port: int,
        model: str | None,
        model_aliases: dict[str, str | Model] | None = None,
        mcp_server_configs: list[MCPServerConfigHTTP] | None = None,
        bridged_tools: dict[str, dict[str, Tool]] | None = None,
        proposal_exempt_servers: set[str] | None = None,
        model_event_sink: ModelEventSink | None = None,
        forward_generation_config: bool = False,
        approval: list["ApprovalPolicy"] | None = None,
        checkpointer: Checkpointer | None = None,
        allow_remote_mcp: bool = False,
        allow_remote_media: bool = False,
        model_resolver: ModelResolver | None = None,
        forward_client_headers: Mapping[str, Sequence[str]] | None = None,
        response_filter: ModelResponseFilter | None = None,
    ) -> None:
        super().__init__(
            state,
            filter,
            retry_refusals,
            compaction,
            model=model,
            model_aliases=model_aliases,
            model_event_sink=model_event_sink,
            forward_generation_config=forward_generation_config,
            approval=approval,
            checkpointer=checkpointer,
            allow_remote_mcp=allow_remote_mcp,
            allow_remote_media=allow_remote_media,
            model_resolver=model_resolver,
            response_filter=response_filter,
        )
        self.port = port
        self.mcp_server_configs = mcp_server_configs or []
        self.bridged_tools = {}
        self.served_tools = {}
        self.proposal_exempt_servers = proposal_exempt_servers or set()
        self.forward_client_headers = resolve_forward_client_headers(
            forward_client_headers
        )
        for server, tools in (bridged_tools or {}).items():
            self.register_bridged_tools(server, tools)
        self._tool_execution_grants: deque[_ToolExecutionGrant] = deque(
            maxlen=_MAX_TOOL_EXECUTION_GRANTS
        )
        self._executed_calls: dict[tuple[str, str], dict[str, list[_HandedCall]]] = {}
        """Per (server, tool), then argument key, the calls an execution consumed a grant of, unless settled since (`_record_execution`). A (server, tool) with no keys left is removed."""
        self._executed_tools: dict[tuple[str, str], _ExecutedTool] = {}
        """Per (server, tool), the calls an execution consumed a grant of, settled ones pruned (`_record_execution`)."""
        self._failure_requested = anyio.Event()
        self._failure: Exception | None = None
        self.generation_limit: LimitExceededError | None = None
        """The limit reached in a bridged generation that `sandbox_agent_bridge` raises: the first, unless a later one encloses it."""

    port: int
    """Model proxy server port."""

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""

    served_tools: dict["_BridgedToolId", ToolInfo]
    """What `list_tools` serves the scaffold for each bridged tool.

    The same `get_tools_info` view the service returns, so a scaffold's
    declaration can be matched to the tool by the description it was given.
    """

    proposal_exempt_servers: set[str]
    """Bridged servers registered with `BridgedToolsSpec(require_proposal=False)`.

    Their tools execute without an execution grant, so for them the bridge does
    not guarantee that a host tool runs only for a call the model proposed.
    """

    forward_client_headers: dict[str, frozenset[str]]
    """Client headers (lowercase name) and values the sandboxed client may send.

    Other client headers and values, except `Accept-Encoding`, are dropped
    before the host request.
    """

    grants_tool_execution = True
    """Host tools run only against a grant minted here from a response."""

    def register_bridged_tools(
        self, server: str, tools: dict[str, Tool], require_proposal: bool = True
    ) -> None:
        """Register `tools` (by name) as bridged server `server`."""
        self.bridged_tools[server] = tools
        for info in get_tools_info(list(tools.values())):
            self.served_tools[_BridgedToolId(server=server, tool=info.name)] = info
        if not require_proposal:
            self.proposal_exempt_servers.add(server)

    def register_tool_execution_grants(
        self,
        calls: Sequence[ToolCall],
        tools: Sequence[ToolInfo | Tool],
        *,
        span_id: str | None = None,
    ) -> None:
        """Add one-shot host-tool grants for the calls in a response handed to the scaffold.

        `call_tool` consumes a matching grant before running a host tool and
        denies a call without one, with or without an approval policy. A grant
        binds the bridged (server, tool) the call denotes (`_proposed_call`,
        resolved against `tools`, the declarations the scaffold made to the model)
        and the arguments handed to the scaffold, JSON-normalized since the
        scaffold re-sends them as parsed JSON. A call denoting several bridged
        tools (a shared description; `warn_indistinct_tools` names them at setup)
        gets one grant for each.

        Each grant also carries the proposing call (`_Proposal`), so the host
        tool's `ToolEvent` can pair with it. `span_id` is the span to record
        executions under when the proposing `ModelEvent` was placed in a span
        other than the current one (a `ModelEventSink` re-attributed it). Grants
        are stored for servers in `proposal_exempt_servers` too, only so that a
        proposed call on them pairs; they execute without one.

        A grant persists until consumed or evicted (with a warning,
        `_warn_eviction`, once `_MAX_TOOL_EXECUTION_GRANTS` unconsumed grants
        accumulate, counting those for exempt servers), including when
        the response never reached the scaffold, but only ever authorizes the
        exact proposed action. An evicted grant's reply is unlinked
        (`_unlink`): on an exempt server its call still executes, untracked,
        and another grant of the call may then execute it again.
        """
        declared = _declarations_by_name(tools)
        handed = (
            self._handed_calls(self._proposing_reply_id, calls)
            if self._proposing_reply_id is not None
            else None
        )
        for index, call in enumerate(calls):
            verified = self._proposing_call_verified
            retained = verified is None or verified[index]
            targets, arguments, _ = _proposed_call(
                self.bridged_tools, self.served_tools, call, declared
            )
            if len(targets) > 1:
                warn_once(
                    logger,
                    f"Tool call '{call.function}' denotes several bridged tools "
                    "sharing a description ("
                    + ", ".join(f"{t.server}/{t.tool}" for t in targets)
                    + "); an execution grant was registered for each of them.",
                )
            proposal = _Proposal(
                call,
                span_id if retained else None,
                self._proposing_message_ids.get(call.id) if retained else None,
                handed[index] if handed is not None else None,
            )
            for target in targets:
                if (
                    len(self._tool_execution_grants)
                    == self._tool_execution_grants.maxlen
                ):
                    evicted = self._tool_execution_grants[0]
                    self._warn_eviction(evicted)
                    if evicted.proposal.reply is not None:
                        self._unlink(evicted.proposal.reply.reply.id)
                self._tool_execution_grants.append(
                    _ToolExecutionGrant(
                        server=target.server,
                        tool=target.tool,
                        arguments=to_jsonable_python(arguments, fallback=str),
                        proposal=proposal,
                    )
                )

    def _warn_eviction(self, evicted: "_ToolExecutionGrant") -> None:
        """Warn, once per kind, that the store is full and its oldest grant goes.

        Grants for servers registered with `require_proposal=False` share the
        store, so they can push out a grant a server requiring proposals needs.
        """
        if evicted.server in self.proposal_exempt_servers:
            consequence = (
                f"The evicted grant is for server '{evicted.server}', registered "
                "with require_proposal=False: that call still executes, but its "
                "tool event no longer pairs with the model's proposal."
            )
        else:
            consequence = (
                f"The evicted grant is for server '{evicted.server}', which "
                "requires proposals: a proposed-but-never-executed call that "
                "old can no longer be executed."
            )
        warn_once(
            logger,
            f"Bridged tool execution grants exceeded {_MAX_TOOL_EXECUTION_GRANTS} "
            "(grants for require_proposal=False servers count too); evicting the "
            f"oldest unconsumed grant. {consequence}",
        )

    def warn_indistinct_tools(self) -> None:
        """Warn the eval author about bridged tools a proposal cannot single out.

        Run once, after every `BridgedToolsSpec` is registered and before the
        service starts, so the collision is visible at setup rather than at the
        first call. Two or more bridged tools with the same served description
        (whitespace-trimmed, so empty descriptions collide too) are each granted
        by a proposal for any of them (`register_tool_execution_grants`).
        """
        by_description: dict[str, list[_BridgedToolId]] = {}
        for tool_id, info in self.served_tools.items():
            by_description.setdefault(info.description.strip(), []).append(tool_id)
        for tool_ids in by_description.values():
            if len(tool_ids) > 1:
                names = ", ".join(f"{t.server}/{t.tool}" for t in tool_ids)
                logger.warning(
                    f"Bridged tools sharing a description ({names}): a proposal "
                    "for one of them grants each of them one execution. Give "
                    "them distinct docstrings to restore one-to-one matching."
                )

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> "_ToolExecutionGrant | None":
        """Consume and return the oldest grant binding this exact (server, tool), if any.

        When grants of more than one proposal match, the execution may belong
        to any of them, so each of those proposals is marked `ambiguous` and
        its reply unlinked (`_unlink`): no execution under them links its
        result message, including one that completed before this one. A grant
        that matches
        only once undeclared keys are dropped (below) counts as matching here
        even when another grant matches exactly: exact matching decides which
        grant is consumed, not which proposal made the call.

        Arguments match by JSON semantics (`json_equal`): key order and
        int/float numeric equality (`5 == 5.0`) don't matter, so a scaffold's
        JSON round-trip cannot turn a proposed call into a denial; any other
        difference (including bool vs number) is denied -- except that, when
        no pending grant for this (server, tool) matches exactly and the
        served tool's schema forbids additional properties, each is compared
        again with the granted keys that schema does not declare dropped
        from the granted side.

        A scaffold may propose bookkeeping fields alongside a tool's real
        arguments that it never forwards when it actually dispatches the
        call (Antigravity's `toolSummary` is the one observed in the wild).
        Those fields are captured verbatim in the grant by
        `register_tool_execution_grants`, so an executed call that
        legitimately omits them would otherwise always be denied. On a
        closed schema such a key could never be a valid argument, so
        dropping it does not change the approved action: every declared key
        must still be equal and present on both sides, and an executed
        argument that is absent or changed still denies. A schema that
        admits additional properties (`True`, a value schema, or `None`)
        keeps exact matching, since an undeclared key there can be a real
        argument.
        """
        declared_properties = self._declared_properties(server, tool)
        pending = [
            (index, grant.arguments)
            for index, grant in enumerate(self._tool_execution_grants)
            if grant.server == server and grant.tool == tool
        ]
        exact = [index for index, granted in pending if json_equal(granted, arguments)]
        projected = (
            [
                index
                for index, granted in pending
                if isinstance(granted, dict)
                and json_equal(
                    {
                        key: value
                        for key, value in granted.items()
                        if key in declared_properties
                    },
                    arguments,
                )
            ]
            if declared_properties is not None
            else []
        )
        matches = exact or projected
        if not matches:
            return None
        proposals = [
            self._tool_execution_grants[index].proposal
            for index in sorted(set(exact) | set(projected))
        ]
        if any(proposal is not proposals[0] for proposal in proposals):
            for proposal in proposals:
                proposal.ambiguous = True
                if proposal.reply is not None:
                    self._unlink(proposal.reply.reply.id)
        grant = self._tool_execution_grants[matches[0]]
        del self._tool_execution_grants[matches[0]]
        self._record_execution(grant)
        return grant

    def unlink_denied_call(
        self, server: str, tool: str, arguments: dict[str, Any] | None
    ) -> None:
        """Unlink every reply whose call a denied or unreadable host call may retry.

        A grant is one-shot, so a client sending a call again (after losing
        the first response, say) is denied, and the scaffold may send that
        denial as the call's answer: the reply of each call it may repeat is
        unlinked (`_unlink`) while that call's execution awaits its answer
        or still runs (`_unsettled`; one already settled is final, so its
        reply, and any pending sibling call in it, keeps its link), and so is
        the reply of each pending grant it may repeat.
        Calls are compared as `consume_tool_execution_grant` compares them,
        on the argument keys of `_call_keys` (both sides also projected onto
        a closed schema's declared keys, so this errs towards unlinking).
        With `arguments` `None` (not an object, or nested too deep to read),
        the call may repeat any call of the tool. A request naming no bridged
        tool repeats no proposal, since none can denote it.

        The argument keys are computed only when a recorded call or pending
        grant of the tool exists: hashing serializes the whole arguments, and
        a large denied call that can repeat nothing shouldn't pay for that.
        """
        if not self._has_recorded_calls(server, tool):
            return
        keys = (
            self._call_keys(server, tool, arguments) if arguments is not None else None
        )
        # unlinked for good, so each recorded call is unlinked here once
        executed = (
            self._executed_tools.pop((server, tool), _ExecutedTool()).calls
            if keys is None
            else [
                handed
                for key in keys
                for handed in self._pop_executed_calls(server, tool, key)
            ]
        )
        for handed in executed:
            if self._unsettled(handed):
                self._unlink(handed.reply.id)
        for grant in self._tool_execution_grants:
            if (
                grant.server == server
                and grant.tool == tool
                and grant.proposal.reply is not None
                and (
                    keys is None
                    or not keys.isdisjoint(
                        self._call_keys(server, tool, grant.arguments)
                    )
                )
            ):
                self._unlink(grant.proposal.reply.reply.id)

    def _has_recorded_calls(self, server: str, tool: str) -> bool:
        """Whether any executed call or pending grant of (server, tool) is recorded for `unlink_denied_call`."""
        return (
            (server, tool) in self._executed_tools
            or (server, tool) in self._executed_calls
            or any(
                grant.server == server
                and grant.tool == tool
                and grant.proposal.reply is not None
                for grant in self._tool_execution_grants
            )
        )

    def _pop_executed_calls(
        self, server: str, tool: str, key: str
    ) -> list[_HandedCall]:
        """Remove and return the executed calls of (server, tool) recorded under argument `key`."""
        by_key = self._executed_calls.get((server, tool))
        if by_key is None:
            return []
        calls = by_key.pop(key, [])
        if not by_key:
            del self._executed_calls[(server, tool)]
        return calls

    def _record_execution(self, grant: "_ToolExecutionGrant") -> None:
        """Check and record the evidence an execution consuming `grant` gives.

        Run as the grant is consumed, before the execution starts, so a
        request arriving while it runs already sees it.

        - A proposal's second execution (one call granted for several tools)
          unlinks its reply (`_unlink`): an answer may hold either result.
        - An earlier execution of the same (server, tool) and arguments
          (`_call_keys`) whose answer hasn't been settled, still queued or
          running, unlinks its reply and this one's: this execution may be
          a client's retry of that call (after losing its response), taking
          a later proposal's identical grant, so either answer may hold
          either result. An earlier execution already settled (its answer
          linked, or left unlinked) is final and is dropped from the record.
        - The call is recorded for `unlink_denied_call`.

        Each recorded call is dropped once scanned or unlinked, and the
        per-tool record drops settled calls each time it doubles, so it stays
        within twice the calls of the tool still running or awaiting answers
        and the work is amortized constant per execution. Reply ids,
        positions and argument hashes only, like the message pool.
        """
        reply = grant.proposal.reply
        if reply is None:
            return
        if grant.proposal.executions > 0:
            self._unlink(reply.reply.id)
        keys = self._call_keys(grant.server, grant.tool, grant.arguments)
        doubt = False
        for key in keys:
            for earlier in self._pop_executed_calls(grant.server, grant.tool, key):
                if self._unsettled(earlier):
                    self._unlink(earlier.reply.id)
                    doubt = True
        if doubt:
            self._unlink(reply.reply.id)
        by_key = self._executed_calls.setdefault((grant.server, grant.tool), {})
        for key in keys:
            by_key[key] = [reply]
        executed = self._executed_tools.setdefault(
            (grant.server, grant.tool), _ExecutedTool()
        )
        executed.calls.append(reply)
        if len(executed.calls) >= 2 * executed.floor:
            executed.calls = [h for h in executed.calls if self._unsettled(h)]
            executed.floor = max(len(executed.calls), _MIN_EXECUTED_TOOL_FLOOR)

    def _unsettled(self, handed: _HandedCall) -> bool:
        """Whether an execution of `handed` may still link: running, or awaiting its answer."""
        if self._edit_root(handed.reply.id) in self._unlinked_replies:
            return False
        awaited = self._awaited_results.get(handed.reply.id)
        return (
            awaited is None
            or handed.position not in awaited.events
            or awaited.events[handed.position] is not None
        )

    def _call_keys(self, server: str, tool: str, arguments: dict[str, Any]) -> set[str]:
        """Hashes of `arguments` as `json_equal` compares them, also projected onto a closed schema's declared keys."""
        forms = [arguments]
        declared = self._declared_properties(server, tool)
        if declared is not None:
            forms.append({k: v for k, v in arguments.items() if k in declared})
        return {mm3_hash(canonical_tool_arguments(form)) for form in forms}

    def _declared_properties(self, server: str, tool: str) -> Mapping[str, Any] | None:
        """The properties a served tool's closed schema declares, or `None` if it admits others."""
        schema = self.served_tools.get(_BridgedToolId(server=server, tool=tool))
        return (
            schema.parameters.properties
            if schema is not None and schema.parameters.additionalProperties is False
            else None
        )

    def dispatched_call(self, call: ToolCall) -> DispatchedCall | None:
        """The bridged tool call `call` makes through a dispatcher (`_dispatched_call`)."""
        return _dispatched_call(self.bridged_tools, call)

    def reviewed_calls(
        self, call: ToolCall, tools: Sequence[ToolInfo | Tool]
    ) -> ReviewedCalls:
        """The calls approval reviews `call` as: one per bridged tool it would run.

        Resolved by `_proposed_call`, as `register_tool_execution_grants`
        resolves the grants, so approval and grants agree on what a call runs.
        Scaffolds rename bridged tools, so a call is reviewed under the bridged
        tool's own name whatever the scaffold declared it as; a call that
        denotes several bridged tools (a shared description) is reviewed as
        each of them. A call that denotes none is reviewed as `AgentBridge`
        reviews it.
        """
        proposed = _proposed_call(
            self.bridged_tools,
            self.served_tools,
            call,
            _declarations_by_name(tools),
        )
        if not proposed.targets:
            return super().reviewed_calls(call, tools)
        return ReviewedCalls(
            [
                replace(call, function=target.tool, arguments=proposed.arguments)
                for target in proposed.targets
            ],
            proposed.dispatch,
        )

    def request_fail(self, error: Exception) -> None:
        """Fail the sample with `error` from a bridged generation or tool call.

        A sandbox bridge's generations and host tool calls run in the sandbox
        service task, where `_handle_request` turns exceptions into RPC error
        responses rather than letting them propagate. Only a `LimitExceededError`
        (routed to the active sample) and a termination (answered, then
        propagated out of the service task) are special-cased, so a termination
        is raised rather than requested here (see `request_terminate`). Raising
        any other error would never reach the sample runner.

        Instead, store the error and signal the monitor task in
        `sandbox_agent_bridge`'s task group, which raises it on the agent's side
        and tears the sample down. This does not raise itself: the caller decides
        how the current RPC unwinds (a host tool call re-raises, and the model
        service returns a provider error payload so the sandboxed agent gets a
        reply rather than blocking on one that will never come). The first error
        requested wins; later requests are ignored.
        """
        if self._failure is None:
            self._failure = error
        self._failure_requested.set()


class _Proposal:
    """One model tool call that minted grants; shared by every grant it minted.

    Referenced only from those grants, so it is dropped with the last of them
    and no pairing state outlives the bounded grant store.
    """

    __slots__ = ("call", "span_id", "message_id", "reply", "executions", "ambiguous")

    def __init__(
        self,
        call: ToolCall,
        span_id: str | None,
        message_id: str | None,
        reply: _HandedCall | None,
    ) -> None:
        self.call = call
        """The proposing call, with the function name as the model saw it."""

        self.span_id = span_id
        """Span to record executions under, or `None` for the span current then."""

        self.message_id = message_id
        """Id of the assistant message the call is in, or `None` if unknown."""

        self.reply = reply
        """The call in the reply handed to the scaffold, or `None` if unknown."""

        self.executions = 0
        """How many executions have consumed one of the proposal's grants (`take_id`)."""

        self.ambiguous = False
        """Whether an execution matched this proposal's grants and another proposal's alike, so which call it ran is unknown."""

    def take_id(self) -> str:
        """The `ToolEvent` id for the next execution of this proposal.

        The proposing call's id the first time; a fresh id after, since a call
        granted for several indistinguishable tools can execute more than once
        and consumers key on the event id.
        """
        self.executions += 1
        return self.call.id if self.executions == 1 else uuid()

    @property
    def linkable(self) -> bool:
        """Whether an execution of this proposal may link its result message.

        Only while the proposal has executed once and matched no other
        proposal's grants. Kept here rather than read from the bridge's
        result tracking, which drops old replies: the proposal lives as long
        as any of its grants can still execute.
        """
        return self.executions == 1 and not self.ambiguous


_MIN_EXECUTED_TOOL_FLOOR = 8


@dataclass
class _ExecutedTool:
    """The calls of one bridged tool an execution consumed a grant of."""

    calls: list[_HandedCall] = field(default_factory=list)
    """The calls, oldest first; settled ones are pruned (`_record_execution`)."""

    floor: int = _MIN_EXECUTED_TOOL_FLOOR
    """`calls` are pruned when they reach twice this: their count after the last prune, at least `_MIN_EXECUTED_TOOL_FLOOR`."""


class _ToolExecutionGrant(NamedTuple):
    """Identity of one host tool execution the model proposed."""

    server: str
    """Bridged server the grant is bound to."""

    tool: str
    """Tool name within the bridged server."""

    arguments: dict[str, Any]
    """The arguments handed to the scaffold, JSON-normalized and matched via `json_equal`."""

    proposal: _Proposal
    """The proposing call, shared with the other grants it minted."""


class _BridgedToolId(NamedTuple):
    """Identity of one bridged tool within the registry."""

    server: str
    tool: str


class _ProposedCall(NamedTuple):
    """What a proposed call would execute: the bridged tools it could denote, with what."""

    targets: list[_BridgedToolId]
    arguments: dict[str, Any]
    dispatch: Callable[[dict[str, Any]], dict[str, Any]]
    """Arguments for the proposed call that run the targets with the given ones."""


_NO_PROPOSAL = _ProposedCall([], {}, _unchanged)


def _declarations_by_name(
    tools: Sequence[ToolInfo | Tool],
) -> dict[str, list[ToolInfo]]:
    """The declarations the scaffold made to the model, by name."""
    declared: dict[str, list[ToolInfo]] = {}
    for tool in tools:
        if isinstance(tool, ToolInfo):
            declared.setdefault(tool.name, []).append(tool)
    return declared


def _proposed_call(
    bridged_tools: dict[str, dict[str, Tool]],
    served: dict[_BridgedToolId, ToolInfo],
    call: ToolCall,
    declared: dict[str, list[ToolInfo]],
) -> _ProposedCall:
    """Resolve a proposed call to the bridged tools it denotes and its arguments.

    Scaffolds rename MCP tools to their models under their own schemes, so the
    called name is ignored. `declared` are the tools the scaffold declared to the
    model in this request, by name; a call to a name the scaffold never declared
    denotes nothing. The call's declaration is matched to a bridged tool by the
    content the bridge served for it in `tools/list`
    (`_resolve_by_served_content`); when nothing matches, the call may be a
    dispatcher call, recognised by its function name and argument shape
    (`_dispatched_call`), denoting the bridged tool its arguments name.
    """
    declarations = declared.get(call.function)
    if not declarations:
        return _NO_PROPOSAL
    targets = _resolve_by_served_content(served, declarations)
    if targets:
        return _ProposedCall(targets, dict(call.arguments), _unchanged)
    dispatched = _dispatched_call(bridged_tools, call)
    if dispatched is None:
        return _NO_PROPOSAL
    return _ProposedCall(
        [_BridgedToolId(server=dispatched.server, tool=dispatched.target.function)],
        dispatched.target.arguments,
        dispatched.dispatch,
    )


def _resolve_by_served_content(
    served: dict[_BridgedToolId, ToolInfo], declarations: Sequence[ToolInfo]
) -> list[_BridgedToolId]:
    """The bridged tools a declaration denotes by what the bridge served for them.

    The description is the key: scaffolds forward the MCP description to their
    models, so equality after trimming whitespace identifies the tool whatever
    name it was given; an empty description is matched like any other, so it
    identifies every bridged tool served without one. Failing an exact match, a
    declaration that is a truncation of a served description identifies it too
    (`_is_truncation_of`), since a scaffold may cut a long description before
    the model sees it, and so does one that is a served description with a
    short scaffold preamble in front (`_prefixed_copies`): Antigravity declares
    every MCP tool as the sentence "This is a tool from the <server> MCP
    server.", a blank line, then the description. Schemas are not consulted:
    scaffolds rewrite them. Tools that cannot be told apart are all returned,
    and the caller grants each. An exact match wins even when that description
    is a prefix of another bridged tool's; a truncated declaration which could
    refer to both denotes both; a prefixed declaration denotes only the tools
    whose whole served description it ends with at the longest such length,
    since a copy of a longer description is not also the shorter one it
    happens to end with.
    """
    targets: list[_BridgedToolId] = []
    for declaration in declarations:
        description = declaration.description.strip()
        matched = (
            [
                tool_id
                for tool_id, info in served.items()
                if info.description.strip() == description
            ]
            or [
                tool_id
                for tool_id, info in served.items()
                if _is_truncation_of(description, info.description.strip())
            ]
            or _prefixed_copies(description, served)
        )
        targets.extend(tool_id for tool_id in matched if tool_id not in targets)
    return targets


_MIN_TRUNCATED_PREFIX = 64
"""Shortest declared text accepted as a truncation of a served description.

Longer than inspect's shortest built-in tool descriptions (`bash`, 43
characters; `text_editor`, 51) and far below any scaffold's truncation limit
(the one known, Claude Code's, is 2048), so a genuine truncation always
qualifies while a short description can never match another tool's as an
accidental prefix.
"""

_MAX_TRUNCATION_MARKER = 24
"""Longest tail a truncating scaffold is assumed to append (``… [truncated]``)."""


def _is_truncation_of(declared: str, served: str) -> bool:
    """Whether a declared description is a served description cut short.

    Scaffold-agnostic: no scaffold's marker is looked for. The two texts must
    agree for at least `_MIN_TRUNCATED_PREFIX` characters, and whatever the
    declared text carries beyond that common prefix (an ellipsis, ``[...]``,
    ``… [truncated]``) must be at most `_MAX_TRUNCATION_MARKER` characters. A
    scaffold that rewrites the leading text is not tolerated.
    """
    common = len(commonprefix([declared, served]))
    return (
        common >= _MIN_TRUNCATED_PREFIX
        and len(declared) - common <= _MAX_TRUNCATION_MARKER
    )


_MAX_SCAFFOLD_PREAMBLE = 96
"""Longest text a scaffold is assumed to put in front of a served description.

Antigravity's is the one known: the sentence "This is a tool from the <server>
MCP server." and a blank line, 38 characters plus the server name, so 96
allows a server name of up to 58 characters while keeping an accidental
suffix match (a declaration that merely ends with another tool's description)
bounded.
"""


def _prefixed_copies(
    declared: str, served: dict[_BridgedToolId, ToolInfo]
) -> list[_BridgedToolId]:
    """The served tools whose whole description `declared` ends with, after a preamble.

    Scaffold-agnostic: no scaffold's wording is looked for. A served description
    qualifies when it is at least `_MIN_TRUNCATED_PREFIX` characters (so a short
    description can never match as another tool's accidental suffix), `declared`
    ends with all of it, and what stands in front is at most
    `_MAX_SCAFFOLD_PREAMBLE` characters. The served description is tried as
    served and as `inspect.cleandoc` leaves it: Antigravity dedents what it
    declares, and on Python before 3.13 a raw docstring keeps its source
    indentation. Of the qualifying descriptions only the longest are returned:
    a declaration carrying the whole of a longer served description names that
    tool, not a shorter one whose description is the longer one's tail. Two
    tools served the same description are both returned. A scaffold that
    otherwise rewrites the description is not tolerated.
    """
    candidates = [
        (len(form), tool_id)
        for tool_id, info in served.items()
        for form in _served_forms(info.description)
        if _is_prefixed_copy_of(declared, form)
    ]
    if not candidates:
        return []
    longest = max(length for length, _ in candidates)
    return [tool_id for length, tool_id in candidates if length == longest]


def _served_forms(description: str) -> list[str]:
    """`description` stripped, and its `inspect.cleandoc` form when that differs."""
    stripped = description.strip()
    dedented = inspect.cleandoc(stripped)
    return [stripped] if dedented == stripped else [stripped, dedented]


def _is_prefixed_copy_of(declared: str, served: str) -> bool:
    """Whether `declared` is `served` with at most a scaffold preamble in front."""
    return (
        len(served) >= _MIN_TRUNCATED_PREFIX
        and declared.endswith(served)
        and 0 < len(declared) - len(served) <= _MAX_SCAFFOLD_PREAMBLE
    )


def _dispatched_call(
    bridged_tools: dict[str, dict[str, Tool]], call: ToolCall
) -> DispatchedCall | None:
    """The bridged tool call a dispatcher call stands for, if it is one.

    Some scaffolds expose every MCP tool through one function whose arguments
    name the target. The one such shape in the wild is Antigravity's
    ``call_mcp_tool(ServerName, ToolName, Arguments)``: string ``ServerName`` and
    ``ToolName`` naming a registered bridged tool and an object ``Arguments``
    denote that tool with those arguments. Anything else is not a dispatched call
    and is reviewed as the call it is: a dispatcher with another name or other
    parameter names, a target that is not a bridged tool, and in particular an
    ordinary call whose own arguments happen to carry these fields (the function
    name is checked first, so no other tool's call can borrow a bridged tool's
    policy, or mint an execution grant for it, by naming it in its arguments).
    Both approval (`SandboxAgentBridge.reviewed_calls`) and grant resolution
    (`_proposed_call`) recognise a dispatcher call through this one function, so
    they cannot disagree about what is one.
    """
    if call.function != "call_mcp_tool":
        return None
    server = call.arguments.get("ServerName")
    tool = call.arguments.get("ToolName")
    arguments = call.arguments.get("Arguments")
    if (
        isinstance(server, str)
        and isinstance(tool, str)
        and isinstance(arguments, dict)
        and tool in bridged_tools.get(server, {})
    ):
        return DispatchedCall(
            server=server,
            target=replace(call, function=tool, arguments=arguments),
            dispatch=lambda modified: {**call.arguments, "Arguments": modified},
        )
    return None
