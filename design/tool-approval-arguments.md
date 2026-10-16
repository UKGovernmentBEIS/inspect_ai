# Tool Approval Arguments

## Overview

For native tool calls, an approver or sentinel monitor decides on the call the
tool will run. While approval or a sentinel is active, the approver sees the
call's arguments as converted for the tool, serialized as JSON. The tool runs
what is rebuilt from the JSON the approver approved, and that JSON must
serialize back to itself. An invalid call is a parsing error and never reaches
an approver. Approvers of a bridged agent's calls get the arguments the
scaffold supplies, without this preparation.

The code is `validated_tool_call()` and `modified_tool_call()` in
[`_call_tools.py`](../src/inspect_ai/model/_call_tools.py).

## Flow under oversight

"Oversight" means an approval policy is active or a sentinel checks tool
calls. Names used below: A is the model's JSON, B what is shown, C what is
approved, D the check.

1. Parse the tool call, as without oversight.
2. Validate A against the tool's schema. A failure is a parsing error to the
   model.
3. Convert A to the tool's parameter types (`tool_params()`). A conversion
   error (a bad ISO date or enum value, a failing constructor) is a parsing
   error.
4. Serialize each converted argument the call gives to JSON, using one
   serializer for every type: Pydantic's, in JSON mode, by alias and without
   computed fields. This is B. A serializer error is a parsing error.
5. Check that B rebuilds to itself (step 7). If not, the call is a parsing
   error and is not shown.
6. Approvers and sentinel monitors see B, rendered by the tool's viewer. An
   approval makes C = B, if the call is unchanged (see below). A modify makes
   C the selected JSON, validated against the schema.
7. Check: convert C again and serialize it (D). D must equal C by JSON
   equality (`5 == 5.0`, but `True != 1`). For a modify, a difference is an
   approval error, reported to the model and recorded with the tool event,
   saying a modify must give the full call as shown.
8. Convert C once more and run the tool with the result. This fresh build
   means a lazy iterable consumed by the check still reaches the tool with
   its values. The ToolEvent records a copy of C, so a later callback cannot
   change what the log says ran, and its view is rendered from a copy of C
   without converting again.

Conversion always works on a copy of the call's arguments, so a constructor
that changes its input in place cannot change the call.

## Changing a call

Approvers and sentinel monitors change a call only by returning a `modify`
decision. Before the approval chain, and again before the before-tool
sentinel, a copy of the call is taken (S = B, or the call a modify selected).
After each:

- approve: after an approval, and after the before-tool sentinel unless it
  selects a modify, the call's id, function and arguments must still equal S
  (JSON equality). The sentinel check also applies when no monitor returns a
  decision. Otherwise it is an approval error ("changed in place; return a
  modify") and the call does not run. An approver that edits the call and
  escalates fails at the end of the chain. An approve runs the call as shown
  even if its `Approval` carries a `modified` call (on `main` that call ran).
  With no approval policy and no sentinel nothing is compared.
- modify: the selected call is validated as in step 7, and it becomes S and
  C. A selection must keep the function in S, or the sample fails. An edit
  to the call the callback was given does not matter.
- reject, terminate: as before.

Not supported and not checked (decision: Ransom, 2026-10-16):

- edits to the `ToolCallView`, which is display only;
- edits by callbacks that run after the tool (result reviewers, after-tool
  sentinel monitors): the tool has run and the log holds a copy;
- edits to the model's call in the conversation, or to the other calls in the
  same assistant turn: callbacks are given the prepared call, so these cannot
  change what runs;
- bridged agents, whose approval is as before this change.

Top-level parameters the call leaves out are not shown. They get their Python
defaults when the arguments are rebuilt, as without oversight. Defaults filled
in when a Pydantic model is constructed are shown. Dataclass fields keep
`main`'s conversion, which does not apply the default of a field the call
leaves out: the field is converted from a missing value instead (a parsing
error for an `int`, the text `"None"` for a `str`). Curried handoff arguments
are Python values from the developer: they are not shown, not converted, and
reach the agent as given.

| Case | Model sends | Approver sees | Outcome |
|---|---|---|---|
| Plain values | `{"x": 1}` | `{"x": 1}` | runs with 1 |
| Model field default | `{"step": {"name": "a"}}` | `{"step": {"name": "a", "status": "pending"}}` | runs |
| Normalizing validator (lowercase) | `{"name": "A"}` | `{"name": "a"}` | runs with `"a"` |
| Validator that doubles | `{"n": 2}` | nothing | parsing error: 4 rebuilds as 8 |
| Modify that leaves out a default | approver selects `{"name": "a"}` | | approval error: rebuilds with `status` added |
| Lazy iterable field | `{"values": [1, 2]}` | `{"values": [1, 2]}` | runs with 1, 2 |
| Validation alias differs from serialization alias | `{"in": 1}` | nothing | parsing error: `{"out": 1}` does not convert back |
| Field serializer that changes the type (`int` as text) | `{"item": {"count": 5}}` | `{"item": {"count": "5"}}` | runs with 5; a modify that copies the shown JSON fails the schema |

## What is refused, and why

Under oversight, a call is refused when:

- its arguments fail the schema or cannot be converted (parsing error);
- a converted argument cannot be serialized (parsing error);
- the serialized arguments do not rebuild to the same JSON (parsing error),
  since the approver would otherwise approve a value the tool never gets;
- a modify does not rebuild to exactly the selected JSON (approval error).
  A modify must give every argument and field in full, as shown.

These shapes are refused rather than supported because they are not used by
real tools. The shapes in use (plain values, models, lists of models, and
model-or-dict unions) round-trip.

The shown JSON is not checked against the tool's schema. Where a parameter's
serialized form does not match the schema (a model field whose validation and
serialization aliases differ, alternative input aliases, a field serializer
that changes the type), a call can be approved, but a modify built from the
shown JSON fails schema validation. A schema check on the shown JSON would
refuse every call to such a tool under oversight, with a parsing error the
model cannot fix; without it, only modify is affected. This applies only to
shown JSON that passes the rebuild check: a split alias that does not rebuild
is refused before approval, as in the table.

## Without oversight

With no approval policy and no sentinel, the arguments are validated and
converted before the tool runs, as before this change, and nothing is
serialized or rebuilt. The tool gets the converted values, and the ToolEvent
records the model's arguments. The only differences from earlier releases
are that validation and conversion happen before the approval step, a
conversion error is a parsing error to the model, curried handoff arguments
are not converted, and conversion works on a copy of the arguments, so a
constructor that changes its input cannot change the call or the log. The
ToolEvent's own copy of the arguments, taken before any callback, changes
nothing here: on `main` a later edit to the call did not reach the log either.

## Decisions

- 2026-10-02: approvers see a constructed model's serialized values, not the
  raw input (decision: Ransom, 2026-10-02).
- 2026-10-14: curried handoff arguments are passed to the agent as given
  (decision: Ransom, 2026-10-14).
- 2026-10-15: strict scalar conversion is dropped in favour of the existing
  conversion, since the approver now sees the converted value. A modify must
  include every field. The tool runs what is rebuilt from the approved JSON
  (decision: Ransom, 2026-10-15).
- 2026-10-16: in-place edits are not supported; `modify` is the only way to
  change a call. One check runs after the approval chain and after the
  before-tool sentinel; the cases under "Changing a call" are not checked.
  This replaces the 2026-10-15 plan to check every callback boundary, which
  kept finding new ones (decision: Ransom, 2026-10-16).
- 2026-10-16: the shown JSON is not checked against the schema, so a call
  whose serialized form does not match it can be approved but not modified
  (decision: Ransom, 2026-10-16).
- 2026-10-16: top-level parameters the call leaves out stay unshown and get
  their Python defaults on rebuild. Showing them would refuse tools whose
  default does not round-trip, such as `x: int = None` (decision: Ransom,
  2026-10-16).
