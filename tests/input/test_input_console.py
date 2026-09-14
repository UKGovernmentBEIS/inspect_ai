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


@pytest.fixture(autouse=True)
def pin_display_type(monkeypatch: pytest.MonkeyPatch) -> None:
    # `_use_inline_app` reads the process-global display type, which an
    # earlier test in the same worker may have latched (any eval run with
    # display="none"/"plain"). Pin it so the tty gate is deterministic.
    from inspect_ai.util import _display as display_mod

    monkeypatch.setattr(display_mod, "_display_type", "full")


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
    assert f"'{MULTILINE_END_TOKEN}'" in out


@pytest.mark.parametrize(
    "typed,expected",
    [
        # paste without trailing newline: Enter submits the last line
        (["one", "two", EOFError()], "one\ntwo"),
        # paste with trailing newline: Enter yields a blank line, dropped
        (["one", "two", "", EOFError()], "one\ntwo"),
        # inner blank lines are content
        (["one", "", "two", "", EOFError()], "one\n\ntwo"),
    ],
)
def test_multiline_tty_drops_the_blank_line_from_the_closing_enter(
    monkeypatch: pytest.MonkeyPatch, typed: list[str | EOFError], expected: str
) -> None:
    _patch_tty(monkeypatch, True)
    _patch_input_lines(monkeypatch, typed)
    result = _ask_schema("paste", _multiline_schema(), _silent_console())
    assert result == InputResult(outcome="accepted", content={"output": expected})


def test_multiline_tty_hint_names_ctrl_d_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sentinel isn't offered at a terminal, so don't advertise it: a
    # dot-only line there is content.
    _patch_tty(monkeypatch, True)
    _patch_input_lines(monkeypatch, [EOFError()])
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False)
    _ask_schema("paste", _multiline_schema(default="x"), console)
    out = buf.getvalue()
    assert "Ctrl-D" in out
    assert f"'{MULTILINE_END_TOKEN}'" not in out


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


async def test_question_prints_on_a_console_silenced_by_display_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Otherwise the eval blocks on stdin with nothing on screen.
    import rich

    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False, quiet=True)
    monkeypatch.setattr(rich, "get_console", lambda: console)
    _patch_tty(monkeypatch, False)
    _patch_prompt(monkeypatch, ["alice"])

    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = await console_handler(InputRequest(message="describe it", schema=schema))
    assert result == InputResult(outcome="accepted", content={"name": "alice"})
    assert "describe it" in buf.getvalue()
    assert console.quiet is True  # restored


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


class _FakeTty:
    """Stands in for sys.__stderr__, whose isatty can't be monkeypatched."""

    def __init__(self, interactive: bool) -> None:
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


def _patch_tty(monkeypatch: pytest.MonkeyPatch, interactive: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: interactive)
    monkeypatch.setattr(sys, "__stderr__", _FakeTty(interactive))


@skip_if_trio  # under trio the gate correctly refuses the app (tested above)
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


@skip_if_trio  # under trio the gate correctly refuses the app (tested above)
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


async def test_console_handler_trio_uses_line_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Textual is asyncio-only: under trio the tty gate must not select it.

    Runs under both backends (the trio variant needs --runtrio): on
    asyncio the app path is taken, on trio the line reader — either way
    the handler must not crash and must return the expected result.
    """
    import sniffio

    _patch_tty(monkeypatch, True)

    if sniffio.current_async_library() == "trio":
        # Would raise RuntimeError('no running event loop') if the gate
        # let the Textual app run.
        _patch_prompt(monkeypatch, ["alice"])
    else:

        async def fake_run_async(self: InlineQuestionApp, **kwargs: Any) -> InputResult:
            return InputResult(outcome="accepted", content={"name": "alice"})

        monkeypatch.setattr(InlineQuestionApp, "run_async", fake_run_async)

    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = await console_handler(InputRequest(message="hi", schema=schema))
    assert result == InputResult(outcome="accepted", content={"name": "alice"})


def test_use_inline_app_requires_stderr_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Textual driver renders the UI to sys.__stderr__; with stderr
    # redirected the form would be invisible while the tty sits in raw mode.
    _patch_tty(monkeypatch, True)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert console_module._use_inline_app()
    monkeypatch.setattr(sys, "__stderr__", _FakeTty(False))
    assert not console_module._use_inline_app()
    monkeypatch.setattr(sys, "__stderr__", None)
    assert not console_module._use_inline_app()


def test_use_inline_app_rejects_dumb_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # TERM=dumb (e.g. Emacs M-x shell): isatty is True but escape
    # sequences render as garbage; Rich prompts degrade gracefully there.
    import rich

    _patch_tty(monkeypatch, True)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(rich.get_console(), "_force_terminal", True)
    assert not console_module._use_inline_app()


@pytest.mark.parametrize(
    "display,inline",
    [
        ("full", True),
        ("rich", True),
        ("conversation", True),
        ("plain", False),
        ("log", False),
        ("none", False),
    ],
)
def test_use_inline_app_follows_display_type(
    monkeypatch: pytest.MonkeyPatch, display: str, inline: bool
) -> None:
    # --display plain/log/none promise line-oriented output, so an
    # interactive tty is not on its own enough to take over the terminal.
    from inspect_ai.util import _display as display_mod

    _patch_tty(monkeypatch, True)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(display_mod, "_display_type", display)
    assert console_module._use_inline_app() is inline


async def test_console_handler_plain_display_reads_lines_to_ctrl_d(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--display plain at a tty: line reader, but Ctrl-D ends the answer.

    The dot sentinel would end a pasted answer early at the very
    terminal the operator pasted into, so it applies to non-tty stdin
    only (`test_multiline_dot_sentinel_*` cover that).
    """
    from inspect_ai.util import _display as display_mod

    _patch_tty(monkeypatch, True)
    monkeypatch.setattr(display_mod, "_display_type", "plain")

    def fail(self: InlineQuestionApp, **kwargs: Any) -> None:
        raise AssertionError("inline app must not run under --display plain")

    monkeypatch.setattr(InlineQuestionApp, "run_async", fail)
    _patch_input_lines(monkeypatch, ["one", MULTILINE_END_TOKEN, "two", EOFError()])
    _patch_prompt(monkeypatch, ["second"])

    schema = ElicitationSchema(
        properties={
            "output": ElicitationStringPropertySchema(
                type="string", field_meta={MULTILINE_META_KEY: True}
            ),
            "name": ElicitationStringPropertySchema(type="string"),
        },
        required=["output", "name"],
    )
    result = await console_handler(InputRequest(message="hi", schema=schema))
    assert result == InputResult(
        outcome="accepted",
        content={"output": f"one\n{MULTILINE_END_TOKEN}\ntwo", "name": "second"},
    )


def test_use_inline_app_requires_main_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Textual's driver installs signal handlers, which raises off the
    # main thread (same reason util/_display.py throttles to plain).
    import threading

    _patch_tty(monkeypatch, True)
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(console_module._use_inline_app())
    )
    thread.start()
    thread.join()
    assert result == [False]


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
        pump(0.5)
        os.write(master, b"\x1b[200~first file\r . \rsecond file\x1b[201~")
        wait_for(b"second file")  # paste rendered in the TextArea
        os.write(master, b"\ntail")  # Ctrl+J: newline as content, not submit
        wait_for(b"tail")
        os.write(master, b"\r")  # Enter: accept files, advance to Name
        # The focus advance rides a posted message and has no greppable
        # render marker (it's only a style repaint), so a fixed settle is
        # the one unavoidable sleep here.
        pump(2.0)
        os.write(master, b"alice")
        wait_for(b"alice")  # typed into the (focused) Name input
        os.write(master, b"\r")  # Enter: submit
        wait_for(b"RESULT:")
        # The JSON tail may arrive in a later chunk than "RESULT:".
        end = time.time() + 10
        while not re.search(rb"RESULT:\{.*\}", buf) and time.time() < end:
            pump(0.25)
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


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pty")
def test_pty_plain_display_paste_with_dot_line_ends_at_ctrl_d() -> None:
    """The same paste through the line reader `--display plain` selects.

    No Textual app here: the paste goes through the tty line discipline
    into `Console.input`, so the guarantee has to come from the
    terminator. A ` . ` line stays content, Ctrl-D ends the answer, and
    the second field reads its own answer rather than the paste's tail.
    """
    import json
    import os
    import pty
    import re
    import select
    import time

    child = 'import os\nos.environ["INSPECT_DISPLAY"] = "plain"\n' + _PTY_CHILD
    pid, master = pty.fork()
    if pid == 0:  # child: never returns
        os.environ["TERM"] = "xterm-256color"
        os.execv(sys.executable, [sys.executable, "-c", child])

    buf = b""

    def wait_for(pattern: bytes, timeout: float = 30) -> None:
        nonlocal buf
        end = time.time() + timeout
        while pattern not in buf:
            assert time.time() < end, (
                f"timed out waiting for {pattern!r}; tail: {buf[-1000:]!r}"
            )
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk

    try:
        wait_for(b"Ctrl-D")  # the multiline hint: reader is up
        wait_for(b"Files")
        # CR line endings, as a terminal sends them; no bracketed paste
        # wrappers, since the reader doesn't enable the mode.
        os.write(master, b"first file\r . \rsecond file")
        wait_for(b"second file")  # echoed by the tty
        # No trailing newline: the last line is still in readline's buffer,
        # where Ctrl-D is delete-char. Enter submits it, then Ctrl-D ends.
        os.write(master, b"\r\x04")
        wait_for(b"Name")
        os.write(master, b"alice\r")
        wait_for(b"RESULT:")
        end = time.time() + 10
        while not re.search(rb"RESULT:\{.*\}", buf) and time.time() < end:
            # The JSON tail may arrive in a later chunk than "RESULT:".
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                buf += os.read(master, 65536)
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
        "content": {"files": "first file\n . \nsecond file", "name": "alice"},
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
