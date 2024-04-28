from typing import Literal

from ._common import match_str, str_match_scorer
from ._metrics import accuracy, bootstrap_std
from ._scorer import Scorer, scorer


@scorer(metrics=[accuracy(), bootstrap_std()])
def match(
    location: Literal["begin", "end", "any", "exact"] = "end",
    *,
    ignore_case: bool = True,
    numeric: bool = False,
) -> Scorer:
    """Scorer which matches text or a number.

    Args:
       location (Literal["begin", "end", "any", "exact"]):
          Location to match at. "any" matches anywhere in the
          output; "exact" requires the output be exactly
          equal to the target (module whitespace, etc.)
       ignore_case (bool): Do case insenstive comparison.
       numeric (bool): Is this a numeric match? (in this
          case different punctuation removal rules are
          used and numbers are normalized before comparisoin).
    """

    def check(value: str, target: str) -> tuple[str, bool]:
        return match_str(
            value=value,
            target=target,
            location=location,
            ignore_case=ignore_case,
            numeric=numeric,
        )

    return str_match_scorer(check)


@scorer(metrics=[accuracy(), bootstrap_std()])
def includes(ignore_case: bool = True) -> Scorer:
    """Check whether the specified text is included in the model output.

    Args:
       ignore_case (bool): Use a case insensitive comparison.

    """

    def check(value: str, target: str) -> tuple[str, bool]:
        if ignore_case:
            idx = value.lower().rfind(target.lower())
        else:
            idx = value.rfind(target)
        return value, idx != -1

    return str_match_scorer(check)
