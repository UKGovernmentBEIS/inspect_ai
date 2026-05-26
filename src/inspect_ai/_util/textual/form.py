"""Shared Textual form widget for ACP `ElicitationSchema` requests.

`ElicitationForm` renders one form field per property and exposes a
`collect()` method that returns either parsed values or per-field errors.

Display-agnostic: lives in `_util/textual` so both the main Inspect task
display (`inspect_ai/input/panel.py`) and the ACP TUI client
(`inspect_ai/agent/_acp/tui/`) can mount it without taking a dependency
on each other.
"""

from typing import Any

from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from rich.segment import Segment
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.strip import Strip
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Select, SelectionList, Static
from textual.widgets.selection_list import Selection
from typing_extensions import override

from inspect_ai.util._input._validate import (
    PropertySchema,
    multiselect_options,
    string_choice_labels,
    validate_integer,
    validate_multiselect,
    validate_number,
    validate_string,
)

# Canonical "required but empty" error string returned by FieldRow's
# per-type collect helpers. Extracted as a module constant so
# :meth:`FieldRow.is_empty_required` can match against it without
# duplicating the control-by-control "is the input blank?" walk.
# Keep the string itself in sync with the literals used inside
# ``FieldRow._collect_string`` / ``_collect_integer`` / ``_collect_number``.
_REQUIRED_ERROR = "This field is required."


class _CleanCheckbox(Checkbox):
    """Checkbox that fully hides its toggle button when unchecked.

    Same story as `_CleanSelectionList`: Textual renders `▐X▌` for every
    state, with the side bracket characters painted in
    `button_style.background`. CSS can hide the inner `X`, but the side
    bracket blocks remain visible as gray rectangles. We override the
    `_button` property to emit three plain-background spaces when off,
    so the toggle area reads as completely blank.
    """

    @property
    def _button(self) -> Content:  # type: ignore[override]
        if self.value:
            return super()._button
        bg = self.background_colors[1]
        return Content.assemble(("   ", Style(background=bg)))


class _CleanSelectionList(SelectionList[str]):
    """SelectionList that fully hides the toggle button when unselected.

    Textual's `SelectionList.render_line` hard-codes a `▐X▌` glyph for every
    row (even unselected ones). The side `▐` and `▌` are painted in
    `button_style.bgcolor`, so even after using CSS to make the inner `X`
    invisible the surrounding bracket blocks remain visible as small gray
    rectangles. That reads as a faint always-on toggle and undermines the
    "blank means off, X means on" semantics we want.

    Instead of fighting the styling, we replace the toggle's first three
    columns with spaces whenever the row isn't selected, so off rows render
    flush against the line background.
    """

    @override
    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        # Map y-coordinate back to the option (mirrors render_line in upstream).
        _, scroll_y = self.scroll_offset
        index = scroll_y + y
        try:
            option = self.get_option_at_index(index)
        except Exception:
            return strip
        if option.value in self._selected:
            return strip
        # Unselected: blank out the first three columns (the ▐X▌ toggle).
        # Reuse the underlying line style so the blanks match the row bg
        # (including the cursor-highlight tint when this row is highlighted).
        segments = list(strip._segments)
        if not segments:
            return strip
        underlying = next(iter(segments[3:]), Segment(" ")).style
        blanked = [Segment("   ", style=underlying)]
        return Strip(blanked + segments[3:], strip.cell_length)


class ElicitationForm(VerticalScroll):
    """Renders an `ElicitationSchema` as a Textual form.

    Field-only — the host (a panel or modal) is responsible for the
    Submit / Decline buttons and for calling `collect()` on submit.
    """

    DEFAULT_CSS = """
    ElicitationForm {
        scrollbar-size-vertical: 1;
        scrollbar-gutter: stable;
        padding: 0 1 0 1;
    }
    ElicitationForm .form-header {
        color: $secondary;
        text-style: bold;
        margin-bottom: 1;
    }
    ElicitationForm .form-description {
        color: $text-muted;
        margin-bottom: 1;
    }
    ElicitationForm FieldRow {
        height: auto;
        margin-bottom: 1;
    }
    ElicitationForm FieldRow .field-label-row {
        height: auto;
    }
    ElicitationForm FieldRow .field-label-row .field-label {
        color: $secondary;
        width: auto;
    }
    ElicitationForm FieldRow .field-label-row .field-description {
        color: $text-muted;
        width: 1fr;
        margin-left: 2;
    }
    ElicitationForm FieldRow .field-error {
        color: $error;
        display: none;
    }
    ElicitationForm FieldRow.has-error .field-error {
        display: block;
    }
    ElicitationForm FieldRow Input {
        width: 1fr;
    }
    /* SelectionList toggle: paint the inner X success-green when selected.
       The off state is handled in `_CleanSelectionList.render_line` (which
       blanks the toggle's first three columns entirely), so no off-state
       rules are needed here. */
    ElicitationForm SelectionList > .selection-list--button-selected {
        color: $text-success;
        text-style: bold;
    }
    ElicitationForm SelectionList > .selection-list--button-selected-highlighted {
        color: $text-success;
        text-style: bold;
    }
    /* Checkbox on-state: paint the inner X success-green so it reads at a
       glance. The off state is handled by `_CleanCheckbox._button` (which
       emits three plain-background spaces), so no off rule is needed. */
    ElicitationForm Checkbox.-on > .toggle--button {
        color: $text-success;
        text-style: bold;
    }
    """

    def __init__(self, schema: ElicitationSchema) -> None:
        super().__init__()
        self._schema = schema
        self._fields: list[FieldRow] = []

    @override
    def compose(self) -> ComposeResult:
        if self._schema.title:
            yield Static(self._schema.title, classes="form-header")
        if self._schema.description:
            yield Static(self._schema.description, classes="form-description")

        required = set(self._schema.required or [])
        for name, prop in (self._schema.properties or {}).items():
            row = FieldRow(name=name, prop=prop, required=name in required)
            self._fields.append(row)
            yield row

    def collect(self) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate every field and either return values or per-field errors.

        Returns `(values, {})` on success or `(None, {name: error})` when one
        or more fields fail validation. Optional fields left blank are
        omitted from `values`.
        """
        values: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for row in self._fields:
            value, error = row.collect()
            if error is not None:
                errors[row.field_name] = error
            elif value is not _OMIT:
                values[row.field_name] = value
        if errors:
            return None, errors
        return values, {}

    def clear_errors(self) -> None:
        for row in self._fields:
            row.clear_error()

    def show_errors(self, errors: dict[str, str]) -> None:
        first_failed: FieldRow | None = None
        for row in self._fields:
            row.show_error(errors.get(row.field_name))
            if first_failed is None and row.field_name in errors:
                first_failed = row
        # Scroll the first failed field into view and focus its control so
        # the user lands directly on the thing they need to fix.
        if first_failed is not None:
            self.scroll_to_widget(first_failed, animate=False)
            first_failed.focus_control()

    def focus_first(self) -> None:
        if self._fields:
            self._fields[0].focus_control()

    def focus_next_empty_required(self, *, after: Widget) -> bool:
        """Focus the next empty-required field after the one owning ``after``.

        ``after`` is typically the :class:`Input` widget that
        emitted :class:`Input.Submitted` (Enter on the focused
        input). The control widgets the form composes — ``Input``,
        ``Select``, ``Checkbox``, ``SelectionList`` — are yielded
        directly from :meth:`FieldRow._compose_control`, so
        ``after.parent`` is the owning :class:`FieldRow`.

        Returns:
            ``True`` if focus moved to a later empty-required
            field; ``False`` if no such field exists, in which case
            the caller should submit (or otherwise advance past
            the form). Also returns ``False`` if ``after`` isn't
            recognised as one of this form's controls — defensive,
            so a stray bubbled :class:`Input.Submitted` from
            outside the form doesn't crash the dispatch.
        """
        owner = after.parent
        if not isinstance(owner, FieldRow) or owner not in self._fields:
            return False
        start = self._fields.index(owner) + 1
        for row in self._fields[start:]:
            if row.is_empty_required():
                row.focus_control()
                return True
        return False


_OMIT = object()


class FieldRow(Vertical):
    """One labeled form field plus a reserved error slot."""

    def __init__(self, *, name: str, prop: PropertySchema, required: bool) -> None:
        super().__init__()
        self.field_name = name
        self._prop = prop
        self._required = required
        self._error = Static("", classes="field-error")

    @override
    def compose(self) -> ComposeResult:
        # Render the field name and description on a single row so each
        # property occupies one fewer line. The two are separate Statics so
        # each can carry its own CSS class — Textual's $text-muted token is
        # an "auto 60%" computed color and doesn't propagate through Rich
        # Text spans, so inline markup on a single Static would inherit the
        # parent label color instead of going gray.
        title = self._prop.title or self.field_name
        with Horizontal(classes="field-label-row"):
            yield Static(title, classes="field-label")
            if self._prop.description:
                yield Static(self._prop.description, classes="field-description")
        yield from self._compose_control()
        yield self._error

    def _compose_control(self) -> ComposeResult:
        prop = self._prop
        if isinstance(prop, ElicitationStringPropertySchema):
            labels = string_choice_labels(prop)
            if labels is not None:
                # `Select` requires (renderable, value); we use (title, const).
                select_kwargs: dict[str, Any] = {
                    "allow_blank": not self._required,
                    "prompt": self._prop.title or self.field_name,
                }
                if prop.default is not None:
                    select_kwargs["value"] = prop.default
                yield Select(
                    [(title, const) for const, title in labels],
                    **select_kwargs,
                )
            else:
                placeholder = prop.format or ""
                yield Input(
                    value=prop.default or "",
                    placeholder=placeholder,
                )
        elif isinstance(prop, ElicitationIntegerPropertySchema):
            yield Input(
                value="" if prop.default is None else str(prop.default),
                type="integer",
            )
        elif isinstance(prop, ElicitationNumberPropertySchema):
            yield Input(
                value="" if prop.default is None else str(prop.default),
                type="number",
            )
        elif isinstance(prop, ElicitationBooleanPropertySchema):
            yield from self._compose_boolean(prop)
        elif isinstance(prop, ElicitationMultiSelectPropertySchema):
            options = multiselect_options(prop)
            defaults = set(prop.default or [])
            selections = [
                Selection(title, const, const in defaults) for const, title in options
            ]
            yield _CleanSelectionList(*selections)
        else:
            raise ValueError(f"Unsupported property type: {type(prop).__name__}")

    def focus_control(self) -> None:
        for child in self.children:
            if isinstance(child, (Input, Checkbox, Select, SelectionList)):
                child.focus()
                return

    def is_empty_required(self) -> bool:
        """``True`` iff this field is required and currently blank.

        Drives the "advance to next empty required" Enter-key
        behaviour in :meth:`ElicitationForm.focus_next_empty_required`.
        Piggybacks on :meth:`collect` rather than re-walking the
        per-type controls so the predicate stays in sync with the
        canonical "blank" check that drives validation errors.
        Non-required fields always return ``False`` — pressing
        Enter past an empty optional field is fine, the form will
        treat it as ``_OMIT`` on submit.
        """
        if not self._required:
            return False
        _, error = self.collect()
        return error == _REQUIRED_ERROR

    def collect(self) -> tuple[Any, str | None]:
        """Parse and validate this field's current input.

        Returns `(value, None)` on success (`value` may be `_OMIT` for an
        optional blank field) or `(None, error_message)` on failure.
        """
        prop = self._prop

        if isinstance(prop, ElicitationStringPropertySchema):
            return self._collect_string(prop)
        if isinstance(prop, ElicitationIntegerPropertySchema):
            return self._collect_integer(prop)
        if isinstance(prop, ElicitationNumberPropertySchema):
            return self._collect_number(prop)
        if isinstance(prop, ElicitationBooleanPropertySchema):
            return self._collect_boolean(prop)
        if isinstance(prop, ElicitationMultiSelectPropertySchema):
            return self._collect_multiselect(prop)
        raise ValueError(f"Unsupported property type: {type(prop).__name__}")

    def _collect_string(
        self, prop: ElicitationStringPropertySchema
    ) -> tuple[Any, str | None]:
        if string_choice_labels(prop) is not None:
            select = self.query_one(Select)
            if select.is_blank():
                if self._required:
                    return None, _REQUIRED_ERROR
                return _OMIT, None
            return select.value, None

        input_widget = self.query_one(Input)
        raw = input_widget.value
        if not raw:
            if self._required:
                return None, _REQUIRED_ERROR
            return _OMIT, None
        return validate_string(prop, raw)

    def _collect_integer(
        self, prop: ElicitationIntegerPropertySchema
    ) -> tuple[Any, str | None]:
        raw = self.query_one(Input).value.strip()
        if not raw:
            if self._required:
                return None, _REQUIRED_ERROR
            return _OMIT, None
        return validate_integer(prop, raw)

    def _collect_number(
        self, prop: ElicitationNumberPropertySchema
    ) -> tuple[Any, str | None]:
        raw = self.query_one(Input).value.strip()
        if not raw:
            if self._required:
                return None, _REQUIRED_ERROR
            return _OMIT, None
        return validate_number(prop, raw)

    def _compose_boolean(self, prop: ElicitationBooleanPropertySchema) -> ComposeResult:
        # When a boolean is optional AND has no default, a plain Checkbox would
        # collapse "left untouched" into False — losing the distinction the
        # console handler preserves (blank → omit). Render a 3-way Select so
        # the user can leave it unset. Required booleans (or those with a
        # default) get a Checkbox as before.
        if self._is_tristate_boolean():
            yield Select(
                [("Yes", True), ("No", False)],
                allow_blank=True,
                prompt=self._prop.title or self.field_name,
            )
        else:
            yield _CleanCheckbox(
                label=prop.title or self.field_name,
                value=bool(prop.default),
            )

    def _collect_boolean(
        self, prop: ElicitationBooleanPropertySchema
    ) -> tuple[Any, str | None]:
        if self._is_tristate_boolean():
            select = self.query_one(Select)
            if select.is_blank():
                return _OMIT, None
            return bool(select.value), None
        checkbox = self.query_one(Checkbox)
        return bool(checkbox.value), None

    def _is_tristate_boolean(self) -> bool:
        prop = self._prop
        return (
            isinstance(prop, ElicitationBooleanPropertySchema)
            and not self._required
            and prop.default is None
        )

    def _collect_multiselect(
        self, prop: ElicitationMultiSelectPropertySchema
    ) -> tuple[Any, str | None]:
        selection_list = self.query_one(SelectionList)
        selected = list(selection_list.selected)
        if not selected:
            min_required = prop.min_items or 0
            if min_required == 0:
                return [] if self._required else _OMIT, None
            return None, f"Select at least {min_required}."
        return validate_multiselect(prop, selected)

    def clear_error(self) -> None:
        self._error.update("")
        self.remove_class("has-error")

    def show_error(self, message: str | None) -> None:
        if message:
            self._error.update(message)
            self.add_class("has-error")
        else:
            self.clear_error()
