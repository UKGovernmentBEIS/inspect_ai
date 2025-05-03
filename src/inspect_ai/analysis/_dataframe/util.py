import hashlib
import string
from typing import cast

from pydantic import JsonValue


def eval_id(run_id: str, task_id: str) -> str:
    """Generate unique eval_id based on hash of run_id and task_id.

    Hash the concatenation of *u1* and *u2* with Blake2s, truncate to 96 bits,
    and return a 22-character Base-62-URL string (no padding).
    Collision risk reaches 50% fator 73 quintillion rows.
    """
    msg = (run_id + task_id).encode()
    digest_136 = hashlib.blake2s(msg, digest_size=17).digest()
    as_int = int.from_bytes(digest_136, "big")
    return to_base62(as_int, 22)  # 136 bits ⇒ ceil(136 / log₂62) = 22


ALPHABET62 = string.digits + string.ascii_letters  # 0-9 A-Z a-z  (62 symbols)


def to_base62(n: int, length: int) -> str:
    if n == 0:
        return "0" * length

    out = []
    while n:
        n, rem = divmod(n, 62)
        out.append(ALPHABET62[rem])

    # Pad with '0's at the beginning after reversing
    result = "".join(reversed(out))
    return result.rjust(length, "0")


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def extract_scores(x: JsonValue) -> JsonValue:
    from inspect_ai.log._log import EvalScore

    # convert to native EvalScore then extract metrics
    scores = [EvalScore.model_validate(score) for score in cast(list[JsonValue], x)]
    metrics: JsonValue = [
        {score.name: {metric.name: metric.value for metric in score.metrics.values()}}
        for score in scores
    ]
    return metrics
