import io
import sys
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationOtherPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
    EnumOption,
    StringMultiSelectItems,
    TitledMultiSelectItems,
)
from rich.console import Console
from rich.prompt import Prompt
from test_helpers.utils import skip_if_trio
from textual import events
from textual.widgets import Button, Input, TextArea

from inspect_ai.util import InputRequest, InputResult
from inspect_ai.util._input import console as console_module
from inspect_ai.util._input._validate import MULTILINE_META_KEY
from inspect_ai.util._input.console import (
    DECLINE_TOKEN,
    MULTILINE_END_TOKEN,
    _ask_schema,
    console_handler,
)
from inspect_ai.util._input.inline import InlineQuestionApp


def _silent_console() -> Console:
    return Console(file=io.StringIO(), width=80, force_terminal=False)


def _patch_prompt(
    monkeypatch: pytest.MonkeyPatch, responses: list[str]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    it = iter(responses)

    def fake_ask(*args: Any, **kwargs: Any) -> str:
        calls.append({"args": args, "kwargs": kwargs})
        return next(it)

    monkeypatch.setattr(Prompt, "ask", fake_ask)
    return calls


def _patch_input_lines(
    monkeypatch: pytest.MonkeyPatch, lines: list[str | EOFError]
) -> None:
    """Feed the multi-line reader (`Console.input`) one entry per call.

    An `EOFError` entry simulates Ctrl-D; running off the end also raises
    `EOFError` so a reader that ignores the sentinel terminates the test.
    """
    it = iter(lines)

    def fake_input(self: Console, *args: Any, **kwargs: Any) -> str:
        item = next(it, EOFError())
        if isinstance(item, EOFError):
            raise item
        return item

    monkeypatch.setattr(Console, "input", fake_input)


def _multiline_schema(**kwargs: Any) -> ElicitationSchema:
    return ElicitationSchema(
        properties={
            "output": ElicitationStringPropertySchema(
                type="string", field_meta={MULTILINE_META_KEY: True}, **kwargs
            )
        },
        required=["output"],
    )


# -- string --------------------------------------------------------------


def test_string_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["alice"])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"name": "alice"}


def test_string_enum_invalid_then_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First answer isn't in the enum -> re-prompt; second is accepted.
    # We validate choices ourselves (not via Rich) so :decline keeps working.
    _patch_prompt(monkeypatch, ["purple", "green"])
    schema = ElicitationSchema(
        properties={
            "color": ElicitationStringPropertySchema(
                type="string", enum=["red", "green", "blue"]
            )
        },
        required=["color"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.content == {"color": "green"}


def test_string_one_of_returns_const(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["draft"])
    schema = ElicitationSchema(
        properties={
            "status": ElicitationStringPropertySchema(
                type="string",
                one_of=[
                    EnumOption(const="draft", title="Draft"),
                    EnumOption(const="pub", title="Published"),
                ],
            )
        },
        required=["status"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.content == {"status": "draft"}


def test_string_enum_accepts_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: :decline must work even when the property has an enum.
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={
            "color": ElicitationStringPropertySchema(
                type="string", enum=["red", "green", "blue"]
            )
        },
        required=["color"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.outcome == "declined"


def test_string_pattern_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["nope", "ab12"])  # second matches [a-z]{2}\d{2}
    schema = ElicitationSchema(
        properties={
            "code": ElicitationStringPropertySchema(
                type="string", pattern=r"[a-z]{2}\d{2}"
            )
        },
        required=["code"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"code": "ab12"}


def test_string_min_length_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["ab", "abcdef"])  # first too short, second ok
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", min_length=3)
        },
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "abcdef"}


def test_string_max_length_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["abcdef", "ab"])  # first too long, second ok
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", max_length=3)
        },
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "ab"}


# -- string: multiline -------------------------------------------------------


def test_multiline_terminates_on_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_lines(
        monkeypatch, ["Filesystem  Size", "/dev/root   40G", MULTILINE_END_TOKEN]
    )
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"output": "Filesystem  Size\n/dev/root   40G"}


def test_multiline_terminates_on_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_lines(monkeypatch, ["  indented", "", "last", EOFError()])
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    # Leading whitespace and blank interior lines survive; nothing is stripped.
    assert result.content == {"output": "  indented\n\nlast"}


def test_multiline_decline_on_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_lines(monkeypatch, [DECLINE_TOKEN])
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    assert result.outcome == "declined"


def test_multiline_decline_token_in_body_is_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_input_lines(monkeypatch, ["line 1", DECLINE_TOKEN, MULTILINE_END_TOKEN])
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"output": f"line 1\n{DECLINE_TOKEN}"}


def test_multiline_required_blank_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_lines(
        monkeypatch, [MULTILINE_END_TOKEN, "second try", MULTILINE_END_TOKEN]
    )
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    assert result.content == {"output": "second try"}


def test_multiline_blank_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_lines(monkeypatch, [MULTILINE_END_TOKEN])
    result = _ask_schema("paste", _multiline_schema(default="a\nb"), _silent_console())
    assert result.content == {"output": "a\nb"}


def test_multiline_eof_without_input_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sticky EOF (stdin is a pipe or closed) must not become an endless
    # "is required" re-prompt; it raises like the single-line Prompt.ask path.
    _patch_input_lines(monkeypatch, ["too long for max_length", EOFError()])
    with pytest.raises(EOFError):
        _ask_schema("paste", _multiline_schema(max_length=3), _silent_console())


def test_multiline_shows_default_and_sentinel_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_input_lines(monkeypatch, [MULTILINE_END_TOKEN])
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False)
    _ask_schema("paste", _multiline_schema(default="x [y]"), console)
    out = buf.getvalue()
    assert "default: x [y]" in out
    assert f"'{MULTILINE_END_TOKEN}'" in out and "Ctrl-D" in out


def test_enum_with_multiline_meta_stays_single_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_prompt(monkeypatch, ["red"])
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False)
    schema = ElicitationSchema(
        properties={
            "color": ElicitationStringPropertySchema(
                type="string",
                enum=["red", "blue"],
                field_meta={MULTILINE_META_KEY: True},
            )
        },
        required=["color"],
    )
    result = _ask_schema("pick", schema, console)
    assert result.content == {"color": "red"}
    assert len(calls) == 1
    assert "Multi-line" not in buf.getvalue()


@pytest.mark.parametrize(
    "prop_kwargs",
    [
        {},
        {"format": "multiline"},
        {"field_meta": {MULTILINE_META_KEY: "true"}},
        {"field_meta": {MULTILINE_META_KEY: False}},
        {"field_meta": {"inspect.other": True}},
    ],
)
def test_string_without_multiline_meta_stays_single_line(
    monkeypatch: pytest.MonkeyPatch, prop_kwargs: dict[str, Any]
) -> None:
    # Only JSON true under the key switches control; a `format` spelling or
    # a truthy non-bool value does not (ask_user rejects the latter upstream;
    # a direct request_input caller gets the single-line default).
    calls = _patch_prompt(monkeypatch, ["one line"])
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", **prop_kwargs)
        },
        required=["name"],
    )
    result = _ask_schema("q", schema, _silent_console())
    assert result.content == {"name": "one line"}
    assert len(calls) == 1


def test_multiline_with_format_shows_format_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The flag is a presentation hint and coexists with a semantic format.
    _patch_input_lines(monkeypatch, ["https://a.example", MULTILINE_END_TOKEN])
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False)
    result = _ask_schema("paste", _multiline_schema(format="uri"), console)
    assert result.content == {"output": "https://a.example"}
    assert "(format: uri)" in buf.getvalue()


def test_multiline_does_not_use_prompt_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_prompt(monkeypatch, [])
    _patch_input_lines(monkeypatch, ["x", MULTILINE_END_TOKEN])
    _ask_schema("paste", _multiline_schema(), _silent_console())
    assert calls == []


# -- integer / number ----------------------------------------------------


def test_integer_in_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["42"])
    schema = ElicitationSchema(
        properties={
            "age": ElicitationIntegerPropertySchema(
                type="integer", minimum=0, maximum=150
            )
        },
        required=["age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"age": 42}


def test_integer_out_of_range_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["200", "50"])  # first too big, second ok
    schema = ElicitationSchema(
        properties={
            "age": ElicitationIntegerPropertySchema(type="integer", maximum=150)
        },
        required=["age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"age": 50}


def test_integer_invalid_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["abc", "7"])
    schema = ElicitationSchema(
        properties={"n": ElicitationIntegerPropertySchema(type="integer")},
        required=["n"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"n": 7}


def test_number_accepts_float(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["1.75"])
    schema = ElicitationSchema(
        properties={"height": ElicitationNumberPropertySchema(type="number")},
        required=["height"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"height": 1.75}


# -- boolean -------------------------------------------------------------


def test_boolean_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["y"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": True}


def test_boolean_false_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["n"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": False}


def test_boolean_invalid_then_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["maybe", "yes"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": True}


def test_boolean_accepts_decline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: :decline must work on boolean prompts.
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "declined"


def test_optional_boolean_blank_omits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: optional boolean with no default should be omittable,
    # not silently coerced to False.
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=None,
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {}


# -- multi-select --------------------------------------------------------


def test_multiselect_titled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["1,3"])
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=TitledMultiSelectItems(
                    any_of=[
                        EnumOption(const="r", title="Red"),
                        EnumOption(const="g", title="Green"),
                        EnumOption(const="b", title="Blue"),
                    ]
                ),
                min_items=1,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["r", "b"]}


def test_multiselect_untitled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["2"])
    schema = ElicitationSchema(
        properties={
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                items=StringMultiSelectItems(
                    type="string", enum=["python", "rust", "go"]
                ),
            )
        },
        required=["tags"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"tags": ["rust"]}


def test_multiselect_min_items_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["1", "1,2"])  # too few, then ok
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=StringMultiSelectItems(type="string", enum=["a", "b", "c"]),
                min_items=2,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["a", "b"]}


def test_multiselect_max_items_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["1,2,3", "1"])  # too many, then ok
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=StringMultiSelectItems(type="string", enum=["a", "b", "c"]),
                max_items=1,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["a"]}


def test_required_multiselect_empty_is_valid_without_min_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: a required array with no min_items / min_items=0 should
    # accept an empty selection (the array itself is present, just empty).
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                items=StringMultiSelectItems(type="string", enum=["a", "b"]),
            )
        },
        required=["tags"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"tags": []}


# -- required / optional / decline / cancel ------------------------------


def test_optional_blank_omits(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={"nick": ElicitationStringPropertySchema(type="string")},
        required=None,
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {}


def test_required_blank_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["", "alice"])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "alice"}


def test_decline_token_returns_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "declined"
    assert result.content is None


async def test_keyboard_interrupt_returns_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def fake_ask_console() -> Iterator[Console]:
        yield _silent_console()

    monkeypatch.setattr(console_module, "_ask_console", fake_ask_console)

    def raise_kbd(*args: Any, **kwargs: Any) -> str:
        raise KeyboardInterrupt()

    monkeypatch.setattr(Prompt, "ask", raise_kbd)

    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = await console_handler(InputRequest(message="hi", schema=schema))
    assert result.outcome == "cancelled"


def test_multiple_properties_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["alice", "42"])
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string"),
            "age": ElicitationIntegerPropertySchema(type="integer"),
        },
        required=["name", "age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "alice", "age": 42}


def test_custom_property_type_rejected() -> None:
    schema = ElicitationSchema(
        properties={"custom": ElicitationOtherPropertySchema(type="_custom")},
    )
    with pytest.raises(ValueError, match="Unsupported property type"):
        _ask_schema("hi", schema, _silent_console())


# -- inline Textual app (interactive tty) ---------------------------------


def _two_field_request() -> InputRequest:
    return InputRequest(
        message="Run the command and paste its output.",
        schema=ElicitationSchema(
            properties={
                "files": ElicitationStringPropertySchema(
                    type="string",
                    title="Files",
                    field_meta={MULTILINE_META_KEY: True},
                ),
                "name": ElicitationStringPropertySchema(type="string", title="Name"),
            },
            required=["files", "name"],
        ),
    )


@skip_if_trio
@pytest.mark.anyio
async def test_inline_paste_with_dot_lines_then_second_field() -> None:
    r"""A paste containing dot-only lines is one answer; the next field is separate.

    Regression for the dot-sentinel reader, where pasting
    ``first file\n . \nsecond file`` ended the first answer at the dot
    and consumed ``second file`` as the next field's answer.
    """
    pasted = "first file\n . \nsecond file"
    app = InlineQuestionApp(_two_field_request())
    async with app.run_test() as pilot:
        # Two pauses: mount, then the call_after_refresh focus pass.
        await pilot.pause()
        await pilot.pause()
        text_area = app.query_one(TextArea)
        assert app.focused is text_area

        # A terminal paste arrives at the App, which forwards it to the
        # focused widget; newlines and dot-lines are content.
        app.post_message(events.Paste(pasted))
        await pilot.pause()
        assert text_area.text == pasted

        # Enter accepts the first answer and advances to the empty
        # required Name field; it must not submit or leak paste content.
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.focused, Input)
        assert app.focused.value == ""

        await pilot.press(*"alice")
        await pilot.press("enter")
        await pilot.pause()

    assert app.return_value == InputResult(
        outcome="accepted", content={"files": pasted, "name": "alice"}
    )


@skip_if_trio
@pytest.mark.anyio
async def test_inline_typed_newlines_and_enter_submit() -> None:
    """Typed Ctrl+J / Shift+Enter insert newlines; Enter submits the form."""
    request = InputRequest(
        message="Notes?",
        schema=_multiline_schema(),
    )
    app = InlineQuestionApp(request)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("a", "ctrl+j", ".", "shift+enter", "b")
        await pilot.press("enter")
        await pilot.pause()

    assert app.return_value == InputResult(
        outcome="accepted", content={"output": "a\n.\nb"}
    )


@skip_if_trio
@pytest.mark.anyio
async def test_inline_decline_button() -> None:
    app = InlineQuestionApp(_two_field_request())
    async with app.run_test() as pilot:
        await pilot.pause()
        decline = app.query_one(f"#{InlineQuestionApp.DECLINE_QUESTION}", Button)
        decline.press()
        await pilot.pause()

    assert app.return_value == InputResult(outcome="declined")


@skip_if_trio
@pytest.mark.anyio
async def test_inline_ctrl_c_cancels() -> None:
    app = InlineQuestionApp(_two_field_request())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()

    assert app.return_value == InputResult(outcome="cancelled")


@skip_if_trio
@pytest.mark.anyio
async def test_inline_submit_empty_required_shows_error() -> None:
    """Submit with a blank required field surfaces the error, app stays up."""
    from inspect_ai._util.textual.form import FieldRow

    app = InlineQuestionApp(_two_field_request())
    async with app.run_test() as pilot:
        await pilot.pause()
        submit = app.query_one(f"#{InlineQuestionApp.SUBMIT_QUESTION}", Button)
        submit.press()
        await pilot.pause()
        rows = list(app.query(FieldRow))
        assert any("has-error" in r.classes for r in rows)
        assert app.return_value is None
        app.exit(None)


# -- console_handler dispatch: tty → inline app, non-tty → line reader ----


def _patch_tty(monkeypatch: pytest.MonkeyPatch, interactive: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: interactive)


async def test_console_handler_tty_runs_inline_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tty(monkeypatch, True)
    sentinel = InputResult(outcome="accepted", content={"name": "alice"})
    run_kwargs: dict[str, Any] = {}

    async def fake_run_async(self: InlineQuestionApp, **kwargs: Any) -> InputResult:
        run_kwargs.update(kwargs)
        return sentinel

    monkeypatch.setattr(InlineQuestionApp, "run_async", fake_run_async)

    result = await console_handler(_two_field_request())
    assert result is sentinel
    assert run_kwargs.get("inline") is True


async def test_console_handler_tty_maps_no_result_to_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tty(monkeypatch, True)

    async def fake_run_async(self: InlineQuestionApp, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(InlineQuestionApp, "run_async", fake_run_async)

    result = await console_handler(_two_field_request())
    assert result == InputResult(outcome="cancelled")


async def test_console_handler_non_tty_uses_line_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tty(monkeypatch, False)
    _patch_prompt(monkeypatch, ["alice"])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = await console_handler(InputRequest(message="hi", schema=schema))
    assert result == InputResult(outcome="accepted", content={"name": "alice"})


# -- real PTY end-to-end ---------------------------------------------------

_PTY_CHILD = """
import asyncio, json
from acp.schema import ElicitationSchema, ElicitationStringPropertySchema
from inspect_ai.util import InputRequest
from inspect_ai.util._input.console import console_handler

schema = ElicitationSchema(
    properties={
        "files": ElicitationStringPropertySchema(
            type="string", title="Files", field_meta={"inspect.multiline": True}
        ),
        "name": ElicitationStringPropertySchema(type="string", title="Name"),
    },
    required=["files", "name"],
)
result = asyncio.run(
    console_handler(InputRequest(message="paste the output", schema=schema))
)
print(
    "RESULT:" + json.dumps({"outcome": result.outcome, "content": result.content}),
    flush=True,
)
"""


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pty")
def test_pty_paste_with_dot_lines_and_typed_newline() -> None:
    """Full-stack repro of the dot-sentinel bug, through a real terminal.

    Drives `console_handler` on a pty: a bracketed paste whose newlines
    are CR (as real terminals send them) and which contains a ` . ` line,
    then a typed Ctrl+J (LF byte) newline, Enter to accept, and a
    separately answered second field. Exercises the inline Textual
    driver, the escape-sequence parser, and the tty dispatch in
    `console_handler` — none of which the Pilot tests touch.
    """
    import json
    import os
    import pty
    import re
    import select
    import time

    pid, master = pty.fork()
    if pid == 0:  # child: never returns
        os.environ["TERM"] = "xterm-256color"
        os.execv(sys.executable, [sys.executable, "-c", _PTY_CHILD])

    buf = b""

    def pump(seconds: float) -> None:
        """Read output for `seconds`, answering cursor-position queries."""
        nonlocal buf
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                # Minimal terminal emulation: the inline driver asks where
                # the cursor is (CSI 6n) and blocks layout on the answer.
                while b"\x1b[6n" in buf:
                    buf = buf.replace(b"\x1b[6n", b"", 1)
                    os.write(master, b"\x1b[10;1R")

    def wait_for(pattern: bytes, timeout: float = 30) -> None:
        end = time.time() + timeout
        while pattern not in buf:
            assert time.time() < end, (
                f"timed out waiting for {pattern!r}; tail: {buf[-1000:]!r}"
            )
            pump(0.25)

    try:
        wait_for(b"Enter submits")  # form rendered, bracketed paste enabled
        pump(1.0)
        os.write(master, b"\x1b[200~first file\r . \rsecond file\x1b[201~")
        pump(1.0)
        os.write(master, b"\ntail")  # Ctrl+J: newline as content, not submit
        pump(1.0)
        os.write(master, b"\r")  # Enter: accept files, advance to Name
        pump(2.0)  # focus advance rides a posted message; give it a beat
        os.write(master, b"alice")
        pump(1.0)
        os.write(master, b"\r")  # Enter: submit
        wait_for(b"RESULT:")
        pump(1.0)
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)

    match = re.search(rb"RESULT:(\{.*\})", buf)
    assert match, f"no RESULT line; tail: {buf[-1000:]!r}"
    assert json.loads(match.group(1)) == {
        "outcome": "accepted",
        "content": {
            "files": "first file\n . \nsecond file\ntail",
            "name": "alice",
        },
    }


def test_long_lines_not_hard_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Rich would otherwise break the command at the console width, which
    # inserts newlines into whatever the user copies from the terminal.
    _patch_prompt(monkeypatch, ["ok", "keep"])
    command = "aws ec2 describe-instances --filters Name=tag:owner,Values=me " + (
        "--query 'Reservations[].Instances[].InstanceId' --output text"
    )
    assert len(command) > 80
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False)
    schema = ElicitationSchema(
        title="Instance check: " + command,
        properties={
            "output": ElicitationStringPropertySchema(
                type="string", description="Paste the output of: " + command
            ),
            "action": ElicitationStringPropertySchema(
                type="string",
                one_of=[
                    EnumOption(const="keep", title="Keep: " + command),
                    EnumOption(const="stop", title="Stop"),
                ],
            ),
        },
        required=["output", "action"],
    )
    _ask_schema("Run this and paste the output:\n" + command, schema, console)
    lines = buf.getvalue().splitlines()
    assert command in lines
    assert "Instance check: " + command in lines
    assert "Paste the output of: " + command in lines
    assert "  keep: Keep: " + command in lines
