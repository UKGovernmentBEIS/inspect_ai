"""Reading the values of options that are a flag, an integer, or both.

`--log-shared`, `--retry-on-error`, `--sample-shuffle`, `--cache` and `--batch`
are all spelled the same way: bare they mean one thing, with `true`/`false` they
mean that thing or its absence, with a number they mean the number, and two of
them accept a config-file path besides. Click expresses that with a callback,
and a callback is `(ctx, param, value)` — a shape only a command line has.

**These are the callbacks' bodies, minus the context.** `eval_set_env` reads the
same options from the environment variables they are bound to, and has to reach
the same values; the version that reproduced the logic instead agreed with the
CLI about two thirds of the time. `--cache 7` became the string `"7"`, a
`--batch true` became a batch size of one rather than the default, and
`--log-shared yes` was refused outright. Extracting the body is what makes that
class of divergence unavailable rather than merely fixed.

The context is not part of the body because it answers only one question — *was
this option given at all* — which every caller already knows by other means: a
command line by asking click, an environment by finding the variable set.
"""


def int_or_bool_value(
    value: str | None,
    true_value: int,
    false_value: int = 0,
    is_one_true: bool = True,
) -> int:
    """An option that is a bare flag or an integer.

    Args:
        value: The text given, or `None` for the bare flag.
        true_value: What the bare flag, or `true`, means.
        false_value: What `false` means.
        is_one_true: Whether `1` means `true_value` rather than the integer one. False where the integer one is a meaningful setting.

    Returns:
        The option's value.

    Raises:
        ValueError: The text is neither a boolean nor an integer.
    """
    if value is None:
        return true_value

    lowered = value.lower()
    true_values = {"true", "yes"}
    if is_one_true:
        true_values.add("1")
    if lowered in true_values:
        return true_value
    if lowered in ("false", "no", "0"):
        return false_value
    return int(value)


def int_bool_or_str_value(
    value: str | None, true_value: int, false_value: int | None = None
) -> int | str | None:
    """An option that is a bare flag, an integer, or a string.

    The extended form of `int_or_bool_value`: text that is neither a boolean nor
    an integer is returned as itself, which is how `--cache` and `--batch` take
    a config file path.

    Args:
        value: The text given, or `None` for the bare flag.
        true_value: What the bare flag, or `true`, means.
        false_value: What `false` means.

    Returns:
        The option's value.
    """
    if value is None:
        return true_value

    lowered = value.lower()
    if lowered in ("true", "yes", "1"):
        return true_value
    if lowered in ("false", "no", "0"):
        return false_value
    try:
        return int(value)
    except ValueError:
        return str(value)
