# Multi-line string fields in elicitation forms

## Problem

An elicitation string property renders as a single-line control on every surface, so a
multi-line answer cannot be given. Pasting one loses data, silently in two of the three
cases:

| Surface | Control | Multi-line paste |
|---|---|---|
| Textual panel (`--display full`) | `_util/textual/form.py:315` `Input` | keeps line 1, **discards the rest with no error** — Textual's `Input._on_paste` does `event.text.splitlines()[0]` |
| ACP TUI / external ACP client | `agent/_acp/tui/widgets/elicitation_card.py` — same `ElicitationForm` | as above |
| console (`--display plain`) | `util/_input/console.py::_ask_string` → `Prompt.ask` → `input()` | returns line 1; lines 2..n stay in the tty buffer and are consumed by the *next* prompt, so they arrive as later answers |

The console case cannot be fixed with bracketed paste: a `uv`-managed CPython links
libedit rather than GNU readline, and libedit both fails to distinguish a pasted newline
and passes half-swallowed paste markers through as text.

This blocks any use of `ask_user` to collect command output, a file, a log excerpt or a
stack trace from the operator — which is most of what a model asks a human to fetch.

## Scope

Add an opt-in multi-line rendering for `ElicitationStringPropertySchema`. Nothing else
about the schema, validation or routing changes, and single-line remains the default.

## The switch

Use `format == "multiline"` on the string property.

- `format` is `Optional[str]` in `acp.schema.StringPropertySchema`, free-form, so a
  custom value is legal on the wire and an ACP client that does not recognise it
  degrades to its normal string control.
- It is already plumbed into `_compose_control`, and a model writing a JSON schema for
  `ask_user` will guess it.
- `field_meta` (`_meta`) is the purist alternative — ACP reserves it for extensions, and
  JSON Schema defines `format` as a semantic annotation rather than a widget hint. It is
  worse on discoverability. Either is acceptable; `format` is the recommendation.

`format` is currently passed through as the `Input` placeholder, so the multiline value
must not also become placeholder text.

## Changes

### `_util/textual/form.py` (the substance)

1. `FieldRow._compose_control`: for a string property with no enum/`one_of` and
   `format == "multiline"`, yield a `TextArea` instead of `Input`. Plain
   `TextArea(...)` defaults to `tab_behavior="focus"`, so Tab still leaves the field —
   do **not** use `TextArea.code_editor()`, which defaults to `"indent"`.
2. `FieldRow._collect_string`: read `TextArea.text` for that case. `Input.value` is
   unchanged for every other case. Do not strip — leading whitespace is meaningful in
   pasted output; the existing string path does not strip either.
3. `FieldRow.focus_control`: add `TextArea` to the `isinstance` tuple, or it silently
   focuses nothing.
4. CSS: add a `TextArea` rule beside `ElicitationForm FieldRow Input`. Needs an explicit
   height (a `TextArea` does not size to content) and its own border/tint dropped to
   match the form — `agent/_acp/tui/session_screen.py:226` does exactly this for the
   composer and is the pattern to copy.

Enter inside a `TextArea` inserts a newline and emits no `Input.Submitted`, so the
"advance to the next empty required field" handling in
`ElicitationForm.focus_next_empty_required` and `elicitation_card.py:177` is untouched.
That is the wanted behaviour — the form is submitted from its Submit button. Do not port
`ComposerTextArea`'s Enter-submits binding (`session_screen.py:63`); that widget is a
chat composer, not a form field.

### `util/_input/console.py`

`_ask_string` needs a multi-line read for the same condition: prompt for lines until EOF
(Ctrl-D) or a line containing only `.`, and join with newlines. Keep `:decline`
recognised on the first line only, so it cannot be triggered by pasted content.

### `tool/_tools/_ask_user.py`

The docstring is the model's only documentation of what a schema may contain. Its
"Constraints per property type" list already names `format` for strings; add that
`format: "multiline"` requests a multi-line field, and an example, so a model asking for
command output requests the right control.

## Not in scope

`validate_string` uses `re.fullmatch` without `DOTALL`, so a `pattern` on a multi-line
value needs `(?s)` from whoever writes the schema. Leave as is.

## Verification

- Unit: `TextArea` chosen only for the multiline case; `collect()` round-trips a value
  containing newlines; a paste-shaped multi-line insert survives whole; `focus_first()`
  lands on the `TextArea`; single-line and enum string fields unchanged.
- Existing suites that must stay green: `tests/input/test_input_panel.py`,
  `tests/agent/test_acp/test_tui/test_elicitation_card.py`, `tests/tools/test_ask_user.py`.
- Console: multi-line read terminates on both sentinels, and `:decline` on line 1 still
  declines.
- Manual, in the ACP TUI: the session screen carries bare-letter bindings and disables
  them for its own composer (`session_screen.py:480`). Confirm a focused `TextArea`
  inside an elicitation card receives plain letters rather than triggering shortcuts.

## Changelog

One line under `## Unreleased` in `docs/CHANGELOG.md`, e.g. "Elicitation: string
properties with `format: \"multiline\"` now render as a multi-line field, so `ask_user`
can collect pasted output."
