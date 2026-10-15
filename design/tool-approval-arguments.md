# Tool Approval Arguments

## Overview

An approver or sentinel monitor decides on the call the tool will run. While
approval or a sentinel is active, the approver sees the call's arguments as
converted for the tool, serialized as JSON. The tool runs what is rebuilt from
the JSON the approver approved, and that JSON must serialize back to itself.
An invalid call is a parsing error and never reaches an approver.

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
6. Approvers, sentinel monitors and the tool's viewer see B. An approval
   makes C = B. A modify makes C the selected JSON, validated against the
   schema.
7. Check: convert C again and serialize it (D). D must equal C by JSON
   equality (`5 == 5.0`, but `True != 1`). For a modify, a difference is an
   approval error that asks for the full call as shown.
8. Convert C once more and run the tool with the result. This fresh build
   means a lazy iterable consumed by the check still reaches the tool with
   its values. The ToolEvent records C, and its view is rendered from C
   without converting again.

Conversion always works on a copy of the call's arguments, so a constructor
that changes its input in place cannot change the call. Viewers are given a
copy of the call. Approvers, sentinel monitors and result reviewers must not
change the call or its view in place; they change a call with a `modify`
decision. An in-place edit is refused: after the approval chain or the
before-tool sentinel, a call whose id, function, arguments or view differ
from what was shown is an approval error and does not run. For a bridged agent
the response is rejected and the model generates again; since every approver
sees the whole response in its history, all of its calls (and dispatcher
calls' envelopes) are checked again before it is handed over, and so is the
list of calls itself (no call added, removed, replaced or reordered). After the tool runs, a
reviewer or monitor that changed the call or its view fails the sample.

Parameters the call leaves out are not shown. They get their Python defaults
when the arguments are rebuilt, as without oversight. Curried handoff
arguments are Python values from the developer: they are not shown, not
converted, and reach the agent as given.

| Case | Model sends | Approver sees | Outcome |
|---|---|---|---|
| Plain values | `{"x": 1}` | `{"x": 1}` | runs with 1 |
| Model field default | `{"step": {"name": "a"}}` | `{"step": {"name": "a", "status": "pending"}}` | runs |
| Normalizing validator (lowercase) | `{"name": "A"}` | `{"name": "a"}` | runs with `"a"` |
| Validator that doubles | `{"n": 2}` | nothing | parsing error: 4 rebuilds as 8 |
| Modify that leaves out a default | approver selects `{"name": "a"}` | | approval error: rebuilds with `status` added |
| Lazy iterable field | `{"values": [1, 2]}` | `{"values": [1, 2]}` | runs with 1, 2 |
| Validation alias differs from serialization alias | `{"in": 1}` | nothing | parsing error: `{"out": 1}` does not convert back |

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

## Without oversight

With no approval policy and no sentinel, the arguments are validated and
converted before the tool runs, as before this change, and nothing is
serialized or rebuilt. The tool gets the converted values, and the ToolEvent
records the model's arguments. The only differences from earlier releases
are that validation and conversion happen before the approval step, a
conversion error is a parsing error to the model, and curried handoff
arguments are not converted.

## Decisions

- 2026-10-02: approvers see a constructed model's serialized values, not the
  raw input (decision: Ransom, 2026-10-02).
- 2026-10-14: curried handoff arguments are passed to the agent as given
  (decision: Ransom, 2026-10-14).
- 2026-10-15: strict scalar conversion is dropped in favour of the existing
  conversion, since the approver now sees the converted value. A modify must
  include every field. The tool runs what is rebuilt from the approved JSON
  (decision: Ransom, 2026-10-15).
- 2026-10-15: approvers, sentinel monitors and reviewers that change a call
  or its view in place are refused with one check, instead of each being
  given a copy. `modify` is the supported way to change a call
  (decision: Ransom, 2026-10-15).
