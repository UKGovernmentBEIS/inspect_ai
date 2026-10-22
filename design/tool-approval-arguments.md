# Tool Approval Arguments

## Overview

For native tool calls, an approver or sentinel monitor decides on the call the
tool will run. While approval or a sentinel is active, the approver sees the
call's arguments as converted for the tool, serialized as JSON. The tool runs
what is rebuilt from the JSON the approver approved, and that JSON must
serialize back to itself. The shown JSON must also rebuild to the same value
as the model's arguments. An invalid call is a parsing error and never reaches
an approver. Approvers of a bridged agent's calls get the arguments the
scaffold supplies, without this preparation.

The code is `validated_tool_call()` and `modified_tool_call()` in
[`_call_tools.py`](../src/inspect_ai/model/_call_tools.py).

## Flow under oversight

"Oversight" means an approval policy is active or a sentinel checks tool
calls. Names used below: A is the model's JSON, B what is shown, C what is
approved.

The rebuild check on JSON X: convert X to the tool's parameter types and
serialize the result as in step 4; it must equal X by JSON equality
(`5 == 5.0`, but `True != 1`).

The value check on B: B converted to the tool's parameter types must equal
the converted values B was serialized from (step 3), by Python `==`, for each
argument in B. Serialization can hide or mask a value, and then B passes the
rebuild check while the tool would get something else: a `SecretStr`
serializes as `**********`, and a field with `exclude=True` or a private
attribute is left out. Omitted parameters and curried handoff values are not
in B, so they are not compared. A comparison that raises is a parsing error.

1. Parse the tool call, as without oversight. For a tool that declares
   canonical arguments (the memory tool resolves `..` in paths), A is the
   canonical form, with or without oversight.
2. Validate A against the tool's schema. A failure is a parsing error to the
   model.
3. Convert A to the tool's parameter types (`tool_params()`). A conversion
   error (a bad ISO date or enum value, a failing constructor) is a parsing
   error.
4. Serialize each converted argument the call gives to JSON, using one
   serializer for every type: Pydantic's, in JSON mode, by alias and without
   computed fields. This is B. A serializer error is a parsing error, and
   so is an argument of B nested deeper than the bound on the model's
   arguments (`MAX_TOOL_CALL_ARGUMENTS_DEPTH`, 100), since conversion can
   add nesting and the log's writer, readers and condensation handle only
   bounded depth.
   B must also survive the event writer unchanged: each argument is written
   in the call as events write it (`to_json_str_safe()`) and reloaded, and
   the reloaded argument must equal B's by JSON equality. Otherwise, or if
   writing or reloading it fails, the argument is a parsing error. This
   refuses any value the log cannot hold: `inf`, `-inf` and `NaN` are
   written as null, an unpaired surrogate in a string as escaped text, and
   an integer over Python's 4,300-digit limit cannot be read back.
5. Apply the rebuild check and the value check to B. If either fails, the
   call is a parsing error and is not shown.
6. Approvers and sentinel monitors see B, rendered by the tool's viewer. An
   approval makes C = B, if the call is unchanged (see below). A modify makes
   C the selected JSON in canonical form (as in step 1), validated against
   the schema. Each ApprovalEvent records copies of the call and view as
   presented to its approver and of the modified call, so later edits do not
   reach it.
7. For a modify, apply the rebuild check to C. A failure is an approval
   error, reported to the model and recorded with the tool event, saying a
   modify must give the full call as shown. An approval needs no second
   check: C = B, which passed step 5.
8. Run the tool with C converted: for an approval, B as converted for the
   value check; for a modify, a fresh conversion. The ToolEvent records a
   copy of C, so a later callback cannot change what the log says ran, and
   its view is rendered from a copy of C without converting again.

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
  C. A selection must keep the function and id in S, or the sample fails: the
  tool message and ToolEvent carry the model's id. An edit to the call the
  callback was given does not matter.
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
reach the agent as given. Neither curried values nor a handoff's omitted
defaults are formatted for the tool-call trace.

| Case | Model sends | Approver sees | Outcome |
|---|---|---|---|
| Plain values | `{"x": 1}` | `{"x": 1}` | runs with 1 |
| Model field default | `{"step": {"name": "a"}}` | `{"step": {"name": "a", "status": "pending"}}` | runs |
| Normalizing validator (lowercase) | `{"name": "A"}` | `{"name": "a"}` | runs with `"a"` |
| Validator that doubles | `{"n": 2}` | nothing | parsing error: 4 rebuilds as 8 |
| Modify that leaves out a default | approver selects `{"name": "a"}` | | approval error: rebuilds with `status` added |
| Lazy iterable field | `{"values": [1, 2]}` | nothing | parsing error: lazy iterables compare by identity, so the value check fails; a modify that adds one runs with its values, since the tool gets a fresh build |
| Validator that returns a different value each run, or a serializer that changes the model | `{"n": 2}` | varies | unsupported: the checks and the tool may see different values |
| `SecretStr` field | `{"key": "k"}` | nothing | parsing error: shown as `**********`, which rebuilds to another secret |
| Field with `exclude=True` | `{"sudo": true}` | nothing | parsing error: left out of B, so it rebuilds as its default |
| Set or frozenset, also as a model or dataclass field | `{"tags": ["a", "b"]}` | `{"tags": [...]}` in iteration order, or nothing | parsing error when that order does not rebuild identically, which can depend on hash order between runs |
| Serializer that rounds a float | `{"price": {"amount": 1.234}}` | nothing | parsing error: shown as `1.23`, which rebuilds to a different value |
| Validator that turns a finite number into infinity | `{"capped": {"x": 101}}` | nothing | parsing error: B holds `inf`, which the log would write as null |
| Validator that produces an unpaired surrogate | `{"text": "a"}` | nothing | parsing error: the log would write it as the text `\ud800`; valid Unicode and literal `\u` text are shown |
| Validator that turns a number into nested lists | `{"value": 99}` | nothing | parsing error: B nests deeper than 100 levels; 98 lists (100 levels with the argument and model) are shown and logged |
| Validator that produces an integer over 4,300 digits | `{"n": 4301}` | nothing | parsing error: the log cannot read it back; 4,300 digits are shown |
| Dataclass field with `compare=False` and `exclude=True` | `{"dry_run": true}` | `{}` | unsupported: rebuilds as its default and still compares equal, so the tool gets the default |
| Validation alias differs from serialization alias | `{"in": 1}` | nothing | parsing error: `{"out": 1}` does not convert back |
| Field serializer that changes the type (`int` as text) | `{"item": {"count": 5}}` | `{"item": {"count": "5"}}` | runs with 5; a modify that copies the shown JSON fails the schema |

## What is refused, and why

Under oversight, a call is refused when:

- its arguments fail the schema or cannot be converted (parsing error);
- a converted argument cannot be serialized (parsing error);
- a serialized argument nests deeper than the model's arguments may
  (parsing error);
- the serialized arguments change when the event writer stores them and
  they are reloaded (parsing error), since the approval record would not
  hold what the approver saw: a non-finite number, an unpaired surrogate,
  or any other value the log cannot hold; writing or reloading that fails
  (an integer too long to read back) is refused the same way;
- the serialized arguments do not rebuild to the same JSON, or to the same
  value in Python (parsing error), since the approver would otherwise approve
  a value the tool never gets;
- a modify does not rebuild to exactly the selected JSON (approval error).
  A modify must give every argument and field in full, as shown.

These shapes are refused rather than supported because they are not used by
real tools. The shapes in use (plain values, models, lists of models, and
model-or-dict unions) round-trip.

Two consequences of these checks are kept as unsupported (decision: Ransom,
2026-10-21). A set or frozenset, including as a model or dataclass field, is
shown as a list in iteration order; when that order does not rebuild
identically the call is a parsing error, which can depend on hash order
between runs. No order-insensitive comparison is added. A serializer that
reduces a value to a stable but different form (rounding, `NaN` in an
`Any`-typed value shown as null) fails the value check, as a `SecretStr` mask
or an excluded field does.

The shown JSON is not checked against the tool's schema. Where a parameter's
serialized form does not match the schema (a model field whose validation and
serialization aliases differ, alternative input aliases, a field serializer
that changes the type), a call can be approved, but a modify built from the
shown JSON fails schema validation. A schema check on the shown JSON would
refuse every call to such a tool under oversight, with a parsing error the
model cannot fix; without it, only modify is affected. This applies only to
shown JSON that passes the rebuild check: a split alias that does not rebuild
is refused before approval, as in the table.

Validators, constructors and serializers are assumed to be deterministic
and free of side effects, including side effects on the object being
serialized (decision: Ransom, 2026-10-22). Ones that are not are unsupported
under oversight, and this is not detected. Conversion runs more than once
during preparation and the checks (steps 3, 5 and 7), and again after a
modify (step 8; an approval runs the value check's build), so a validator
or constructor that returns a
different value each time can give the checks and the tool different
values. A serializer that changes the model it serializes (rounding a field
in place, say) changes the value the value check compares with.

Python equality on a parameter type is assumed to compare all state that
affects execution (decision: Ransom, 2026-10-22). A type whose `==` ignores
such a value (a dataclass field with `compare=False`, a custom `__eq__` that
skips state) is unsupported under oversight and is not checked, in
particular when that value is also left out of serialization: the value
check then passes although the tool gets a different value. No type or
field inspection is added to detect it.

## Without oversight

With no approval policy and no sentinel, the arguments are validated and
converted before the tool runs, as before this change, and nothing is
serialized or rebuilt. The tool gets the converted values, and the ToolEvent
records the model's arguments, before canonicalization (step 1), as on
`main`. The only differences from earlier releases
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
- 2026-10-21: the shown call must also rebuild to the same Python value as
  the model's arguments, so a value that serialization hides or masks is a
  parsing error under oversight. A `modify` may not change the call's id
  (decision: Ransom, 2026-10-21).
- 2026-10-21: the tool runs a build separate from the JSON rebuild check
  (step 8): an approval runs B as converted for the Python value check, and a
  modify runs a fresh conversion of C, so the rebuild check does not consume
  the tool's values.
  Validators and constructors that return a different value each time are
  unsupported (decision: Ransom, 2026-10-21).
- 2026-10-21: sets and frozensets whose shown order does not rebuild
  identically, and serializers that reduce a value to a stable but different
  form, stay refused under oversight. A shown call holding `inf`, `-inf` or
  `NaN` at any depth is a parsing error, since the approval record cannot
  store it (decision: Ransom, 2026-10-21).
- 2026-10-22: validators, constructors and serializers are assumed
  deterministic and free of side effects, including on the object being
  serialized; ones that are not are unsupported under oversight. This
  generalizes the 2026-10-21 decision on validators that return a different
  value each time. One check replaces the non-finite rule: B must reload
  unchanged after the event writer stores it, which also covers unpaired
  surrogates and any other value the log cannot hold (decision: Ransom,
  2026-10-22).
- 2026-10-22: Python equality on a parameter type must compare all
  execution-relevant state. A type whose `==` ignores such state (a
  `compare=False` dataclass field, a custom `__eq__`), in particular state
  also excluded from serialization, is unsupported under oversight and not
  checked (decision: Ransom, 2026-10-22).
