import hashlib
import re
from collections import deque
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
)
from inspect_ai.model._openai_responses import RESPONSES_NAMESPACE
from inspect_ai.tool import Tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._checkpoint.checkpointer import Checkpointer

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
        )
        self.port = port
        self.mcp_server_configs = mcp_server_configs or []
        self.bridged_tools = bridged_tools or {}
        self.proposal_exempt_servers = proposal_exempt_servers or set()
        self._tool_execution_grants: deque[_ToolExecutionGrant] = deque(
            maxlen=_MAX_TOOL_EXECUTION_GRANTS
        )
        self._failure_requested = anyio.Event()
        self._failure: Exception | None = None

    port: int
    """Model proxy server port."""

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""

    proposal_exempt_servers: set[str]
    """Bridged servers registered with `BridgedToolsSpec(require_proposal=False)`.

    Their tools execute without an execution grant, so for them the bridge does
    not guarantee that a host tool runs only for a call the model proposed.
    """

    grants_tool_execution = True
    """Host tools run only against a grant minted here from a response."""

    def register_tool_execution_grants(
        self, calls: Sequence[ToolCall], tools: Sequence[ToolInfo | Tool]
    ) -> None:
        """Add one-shot host-tool grants for the calls in a response handed to the scaffold.

        A host tool executes only for a call the model proposed in a bridged
        generation, once per proposal: `call_tool` consumes a matching grant
        before running the tool and denies a call without one, whether or not an
        approval policy is active. Each grant binds the exact bridged (server,
        tool) the call denotes plus the arguments handed to the scaffold (as
        approved or approver-modified; JSON-normalized, since the scaffold
        re-sends them as parsed JSON). The call is resolved against `tools`, the
        declarations the scaffold made to the model in this request
        (`_proposed_call`): a call the scaffold declared no tool for denotes
        nothing, a Responses API namespace on the declaration pins the server,
        a tool the scaffold unmistakably declared under another name (a
        namespaced declaration, or a candidate name carrying the tool's own
        description) is not matched under this one, and Antigravity's
        `call_mcp_tool` dispatcher is recognized by its declared parameters
        outside any namespace. A call that still denotes more than one
        bridged tool is ambiguous — no grant is registered (fail closed, with a
        warning). No grant is stored for a server in `proposal_exempt_servers`,
        since none is needed to execute its tools.

        A grant is not scoped to the turn it was proposed in: it persists until
        consumed (or evicted, with a warning, once `_MAX_TOOL_EXECUTION_GRANTS`
        unconsumed grants accumulate) — including when the response never
        reached the scaffold (serialization or transport failure) — but only ever
        authorizes the exact proposed action.
        """
        declared = {tool.name: tool for tool in tools if isinstance(tool, ToolInfo)}
        for call in calls:
            targets, arguments = _proposed_call(self.bridged_tools, call, declared)
            if not targets:
                continue
            if len(targets) > 1:
                warn_once(
                    logger,
                    f"Tool call '{call.function}' denotes more than one "
                    "bridged tool as the agent declared them; no execution "
                    "grant registered (the call will be denied). Use tool "
                    "names that are unique across bridged servers.",
                )
                continue
            target = targets[0]
            if target.server in self.proposal_exempt_servers:
                continue
            if len(self._tool_execution_grants) == self._tool_execution_grants.maxlen:
                warn_once(
                    logger,
                    "Bridged tool execution grants exceeded "
                    f"{_MAX_TOOL_EXECUTION_GRANTS}; evicting the oldest "
                    "unconsumed grant. A proposed-but-never-executed call "
                    "that old can no longer be executed.",
                )
            self._tool_execution_grants.append(
                _ToolExecutionGrant(
                    server=target.server,
                    tool=target.tool,
                    arguments=to_jsonable_python(arguments, fallback=str),
                )
            )

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> bool:
        """Consume one grant binding this exact (server, tool), if present.

        Arguments match by JSON semantics (`_json_equal`): key order and
        int/float numeric equality (`5 == 5.0`) don't matter, so a scaffold's
        JSON round-trip cannot turn a proposed call into a denial; any other
        difference (including bool vs number) is denied.
        """
        for index, grant in enumerate(self._tool_execution_grants):
            if (
                grant.server == server
                and grant.tool == tool
                and _json_equal(grant.arguments, arguments)
            ):
                del self._tool_execution_grants[index]
                return True
        return False

    def request_fail(self, error: Exception) -> None:
        """Fail the sample with `error` from a bridged generation.

        A sandbox bridge's generations run in the sandbox service task, where
        `_handle_request` turns exceptions into RPC error responses rather than
        letting them propagate (only `LimitExceededError` is special-cased). So
        raising from a generation would never reach the sample runner.

        Instead, store the error and signal the monitor task in
        `sandbox_agent_bridge`'s task group, which raises it on the agent's side
        and tears the sample down. This does not raise itself: the caller decides
        how the current RPC unwinds (`request_terminate` raises, and the model
        service returns a provider error payload so the sandboxed agent gets a
        reply rather than blocking on one that will never come). The first error
        requested wins; later requests are ignored.
        """
        if self._failure is None:
            self._failure = error
        self._failure_requested.set()

    def request_terminate(self, reason: str) -> NoReturn:
        """Terminate the sample from a bridged generation.

        Signals the sample failure via `request_fail` (see there for why a plain
        raise would not reach the sample runner) and raises so the current RPC
        unwinds with an error response.
        """
        error = TerminateSampleError(reason)
        self.request_fail(error)
        raise error


class _ToolExecutionGrant(NamedTuple):
    """Identity of one host tool execution the model proposed."""

    server: str
    """Bridged server the grant is bound to."""

    tool: str
    """Tool name within the bridged server."""

    arguments: dict[str, Any]
    """The arguments handed to the scaffold, JSON-normalized and matched via `_json_equal`."""


_CLAUDE_CODE_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_CODEX_CLI_INVALID = re.compile(r"[^a-zA-Z0-9_]")
_CODEX_CLI_MAX_LENGTHS = (64, 128)
_CODEX_CLI_SEPARATOR = "__"
_CODEX_CLI_HASH_LENGTH = 12
_GEMINI_CLI_INVALID = re.compile(r"[^a-zA-Z0-9_.:-]")
_GEMINI_CLI_MAX_LENGTH = 63
_OPENCODE_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_KIMI_CODE_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_KIMI_CODE_UNDERSCORES = re.compile(r"_+")
_KIMI_CODE_MAX_LENGTH = 64
_ANTIGRAVITY_DISPATCHER = "call_mcp_tool"


def _candidate_functions(server: str, tool: str) -> set[str]:
    """The names a scaffold could have declared this bridged tool as to its model.

    Each scaffold names MCP tools under its own scheme and rewrites characters its
    model API rejects; the schemes are reproduced here from the scaffolds' source
    so a proposal is recognized even when the scaffold rewrote the name:

    - Claude Code: ``mcp__<server>__<tool>``, characters outside ``[A-Za-z0-9_-]``
      in either part replaced with ``_``.
    - Codex CLI: the tool name inside a ``mcp__<server>`` Responses API namespace,
      so the call carries the bare name (older releases sent the flat
      ``mcp__<server>__<tool>``); characters outside ``[A-Za-z0-9_]`` replaced
      with ``_``, and when namespace, separator and name exceed the cap (64
      bytes before rust-v0.150, 128 from it) the name is cut and given a hash
      suffix (see `_codex_cli_parts`).
    - Gemini CLI: ``mcp_<server>_<tool>`` (the prefix is not doubled when the
      server name already starts with ``mcp_``), characters outside
      ``[A-Za-z0-9_.:-]`` replaced with ``_``, and a name over 63 characters
      collapsed to its first and last 30 around ``...``. Older releases used
      ``<server>__<tool>`` for conflicting names.
    - OpenCode: ``<server>_<tool>``, characters outside ``[A-Za-z0-9_-]`` in
      either part replaced with ``_``.
    - Kimi Code: ``mcp__<server>__<tool>``, characters outside ``[A-Za-z0-9_-]``
      in either part replaced with ``_`` and runs of ``_`` collapsed; a name over
      64 characters is cut and given an FNV-1a hash (see `_kimi_code_function`).

    Antigravity declares no per-tool functions; its ``call_mcp_tool`` dispatcher
    is recognized in `_proposed_call` instead.

    The bare tool name (`_bare_function`) is kept for a scaffold that passes
    names straight through. Every candidate is computed from the known (server,
    tool), never parsed out of a call name, so an unrecognized scheme matches
    nothing (deny-safe) rather than the wrong tool. Which scheme is active is
    settled against the tools the scaffold actually declared in the request
    (`_resolve_bridged_tools`).
    """
    claude_code = _CLAUDE_CODE_INVALID.sub
    opencode = _OPENCODE_INVALID.sub
    return {
        _bare_function(server, tool),
        f"mcp__{claude_code('_', server)}__{claude_code('_', tool)}",
        *_codex_cli_functions(server, tool),
        f"{server}__{tool}",
        _gemini_cli_function(server, tool),
        f"{opencode('_', server)}_{opencode('_', tool)}",
        _kimi_code_function(server, tool),
    }


def _bare_function(server: str, tool: str) -> str:
    """The tool's own name, as a pass-through scaffold declares it."""
    return tool


def _codex_cli_parts(server: str, tool: str) -> set[tuple[str, str]]:
    """Codex CLI's (namespace, name) pairs for a bridged tool (its `normalize_tools_for_model`).

    The sanitized tool name sits in a ``mcp__<server>`` namespace, so a call
    carries the bare name and the declaration carries the namespace. When
    namespace, separator and name exceed the cap, the name is cut to fit and
    given a ``_<12 hex>`` suffix, the SHA-1 of the tool's identity (server,
    namespace, connector id, name, name; the middle three are the raw server
    name, empty, and the raw tool name for an MCP server), and a namespace that
    leaves no room for the suffix is cut instead. The cap was 64 bytes up to
    rust-v0.149 (still embedded in codex-acp) and is 128 from rust-v0.150, so
    both are produced. Codex disambiguates names that still collide with another
    server's tools by hashing again; those are not reproducible from one bridged
    tool and are denied.
    """
    parts: set[tuple[str, str]] = set()
    for max_length in _CODEX_CLI_MAX_LENGTHS:
        namespace = _CODEX_CLI_INVALID.sub("_", server)
        if not namespace.startswith("mcp__"):
            namespace = f"mcp__{namespace}"
        name = _CODEX_CLI_INVALID.sub("_", tool)
        reserved = len(_CODEX_CLI_SEPARATOR)
        if len(namespace) + len(name) + reserved > max_length:
            identity = f"{server}\0{server}\0\0{tool}\0{tool}".encode()
            digest = hashlib.sha1(identity, usedforsecurity=False).hexdigest()
            suffix = f"_{digest[:_CODEX_CLI_HASH_LENGTH]}"
            max_name = max(max_length - len(namespace) - reserved, 0)
            if max_name >= len(suffix):
                name = name[: max_name - len(suffix)] + suffix
            else:
                namespace = namespace[: max_length - len(suffix) - reserved]
                name = suffix
        parts.add((namespace, name))
    return parts


def _codex_cli_functions(server: str, tool: str) -> set[str]:
    """Codex CLI's model-facing names: the namespaced bare name and the older flat form."""
    names: set[str] = set()
    for namespace, name in _codex_cli_parts(server, tool):
        names.add(name)
        names.add(f"{namespace.rstrip('_')}{_CODEX_CLI_SEPARATOR}{name.lstrip('_')}")
    return names


def _gemini_cli_function(server: str, tool: str) -> str:
    """Gemini CLI's model-facing name for a bridged tool (its `generateValidName`)."""
    name = f"{server}_{tool}"
    if not name.startswith("mcp_"):
        name = f"mcp_{name}"
    name = _GEMINI_CLI_INVALID.sub("_", name)
    if len(name) > _GEMINI_CLI_MAX_LENGTH:
        name = f"{name[:30]}...{name[-30:]}"
    return name


def _kimi_code_function(server: str, tool: str) -> str:
    """Kimi Code's model-facing name for a bridged tool (its `qualifyMcpToolName`)."""

    def part(value: str) -> str:
        return _KIMI_CODE_UNDERSCORES.sub("_", _KIMI_CODE_INVALID.sub("_", value))

    name = f"mcp__{part(server)}__{part(tool)}"
    if len(name) <= _KIMI_CODE_MAX_LENGTH:
        return name
    digest = _kimi_code_hash(name)
    return f"{name[: _KIMI_CODE_MAX_LENGTH - len(digest) - 1]}_{digest}"


def _kimi_code_hash(value: str) -> str:
    """Kimi Code's `stableHash8`: 32-bit FNV-1a in JavaScript integer arithmetic.

    `Math.imul` yields a signed 32-bit product and `toString(16)` renders a
    negative one with a leading ``-``, so the digest is 8 hex digits, or ``-``
    and 8; the name is ASCII by then, so code points are single code units.
    """
    digest = 0x811C9DC5
    for char in value:
        digest = ((digest ^ ord(char)) * 0x01000193) & 0xFFFFFFFF
    if digest & 0x80000000:
        return f"-{(1 << 32) - digest:x}".rjust(8, "0")
    return f"{digest:x}".rjust(8, "0")


class _BridgedToolId(NamedTuple):
    """Identity of one bridged tool within the registry."""

    server: str
    tool: str


def _declaration_namespace(declaration: ToolInfo) -> str | None:
    """The Responses API namespace a declaration was made in, if any (Codex)."""
    namespace = (declaration.options or {}).get(RESPONSES_NAMESPACE)
    if isinstance(namespace, tuple | list) and namespace:
        return str(namespace[0])
    return None


def _denotes(declaration: ToolInfo, server: str, tool: str) -> bool:
    """Whether a declared tool could be how the scaffold presented this bridged tool.

    A declaration made inside a namespace denotes the tool only through Codex's
    (namespace, name) pairs, which are definitive. Otherwise its name must be one
    of the tool's candidate names under some scheme.
    """
    namespace = _declaration_namespace(declaration)
    if namespace is not None:
        return (namespace, declaration.name) in _codex_cli_parts(server, tool)
    return declaration.name in _candidate_functions(server, tool)


def _claims(declaration: ToolInfo, server: str, tool: str, description: str) -> bool:
    """Whether a declared tool is unmistakably this bridged tool, declared elsewhere.

    Used to rule out a candidate: if the scaffold declared the bridged tool under
    another name, this call is not a proposal for it. A namespaced (Codex)
    declaration claims it through the (namespace, name) pair alone. A flat
    declaration claims it only under one of the tool's candidate names, the bare
    name included, and with the description the bridge served for the tool in
    `tools/list`: the description is what tells the scaffold's declaration of the
    tool from an unrelated local tool whose name merely reads as one of the
    tool's names under some scheme, in either direction.
    """
    namespace = _declaration_namespace(declaration)
    if namespace is not None:
        return (namespace, declaration.name) in _codex_cli_parts(server, tool)
    return (
        declaration.name in _candidate_functions(server, tool)
        and declaration.description.strip() == description.strip()
    )


def _resolve_bridged_tools(
    bridged_tools: dict[str, dict[str, Tool]],
    declaration: ToolInfo,
    declared: dict[str, ToolInfo],
) -> list[_BridgedToolId]:
    """Every bridged (server, tool) a declared tool denotes, given all declarations.

    A bridged tool that another declaration in the request claims (`_claims`) is
    not denoted by this one, however its name reads under some other scheme: that
    settles which scheme is active and keeps a scaffold-local tool from standing
    in for a bridged one. The description compared is the one `list_tools` served
    (`ToolDef(tool).description`), read once per tool.
    """
    others = [other for other in declared.values() if other is not declaration]
    targets: list[_BridgedToolId] = []
    for server, tools in bridged_tools.items():
        for tool, tool_fn in tools.items():
            if not _denotes(declaration, server, tool):
                continue
            if others:
                description = ToolDef(tool_fn).description
                if any(_claims(other, server, tool, description) for other in others):
                    continue
            targets.append(_BridgedToolId(server=server, tool=tool))
    return targets


_ANTIGRAVITY_DISPATCHER_PARAMETERS = frozenset({"ServerName", "ToolName", "Arguments"})


def _is_antigravity_dispatcher(declaration: ToolInfo) -> bool:
    """Whether a declaration is Antigravity's `call_mcp_tool` dispatcher.

    Recognized by name and declared parameters, and never for a declaration made
    inside a Responses API namespace: that is a Codex tool of the same name and
    shape, and the namespace is definitive.
    """
    return (
        declaration.name == _ANTIGRAVITY_DISPATCHER
        and _declaration_namespace(declaration) is None
        and set(declaration.parameters.properties) == _ANTIGRAVITY_DISPATCHER_PARAMETERS
    )


class _ProposedCall(NamedTuple):
    """What a proposed call would execute: the bridged tools it could denote, with what."""

    targets: list[_BridgedToolId]
    arguments: dict[str, Any]


def _proposed_call(
    bridged_tools: dict[str, dict[str, Tool]],
    call: ToolCall,
    declared: dict[str, ToolInfo],
) -> _ProposedCall:
    """Resolve a proposed call to the bridged tools it denotes and its arguments.

    `declared` are the tools the scaffold declared to the model in this request,
    by name. A call to a name the scaffold never declared denotes nothing. Most
    scaffolds declare each bridged tool as its own function, so the declaration
    denotes the tool (`_resolve_bridged_tools`) and the call's arguments are the
    tool's. Antigravity instead declares one dispatcher,
    ``call_mcp_tool(ServerName, ToolName, Arguments)`` (`_is_antigravity_dispatcher`):
    the target and the arguments then come from the call's arguments; the server
    is named explicitly, so there is nothing ambiguous to resolve, and a target
    that is not a bridged tool denotes nothing.
    """
    declaration = declared.get(call.function)
    if declaration is None:
        return _ProposedCall([], {})
    if _is_antigravity_dispatcher(declaration):
        server = call.arguments.get("ServerName")
        tool = call.arguments.get("ToolName")
        arguments = call.arguments.get("Arguments")
        if (
            isinstance(server, str)
            and isinstance(tool, str)
            and isinstance(arguments, dict)
            and tool in bridged_tools.get(server, {})
        ):
            return _ProposedCall([_BridgedToolId(server=server, tool=tool)], arguments)
        return _ProposedCall([], {})
    return _ProposedCall(
        _resolve_bridged_tools(bridged_tools, declaration, declared),
        dict(call.arguments),
    )


def _json_equal(a: Any, b: Any) -> bool:
    """Equality by JSON semantics: 5 == 5.0, but True != 1 (unlike Python `==`)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(v, b[k]) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and bool(a == b)
