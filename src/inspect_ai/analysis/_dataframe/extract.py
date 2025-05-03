import hashlib
from typing import cast

from pydantic import JsonValue

from inspect_ai._util.json import jsonable_python
from inspect_ai._util.path import native_path
from inspect_ai.log._log import EvalLog


def scores_dict(log: EvalLog) -> JsonValue:
    if log.results is not None:
        metrics: JsonValue = [
            {
                score.name: {
                    metric.name: metric.value for metric in score.metrics.values()
                }
            }
            for score in log.results.scores
        ]
        return metrics
    else:
        return None


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def log_to_record(log: EvalLog) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], jsonable_python(log))


def eval_log_location(log: EvalLog) -> str:
    return native_path(log.location)


def eval_id(log: EvalLog) -> str:
    """Generate unique eval_id based on hash of run_id and task_id.

    Hash the concatenation of *run_id* and *task_id* with Blake2s, truncate to 128 bits,
    and then further truncate to 93 bits, returning a 22-character Base-57-URL string.
    Collision probability reaches 50% at approximately 70 trillion records.
    """
    msg = (log.eval.run_id + log.eval.task_id).encode()
    digest_size = 16  # 128 bits
    digest = hashlib.blake2s(msg, digest_size=digest_size).digest()

    # Truncate to ~93 bits (log₂57^22 ≈ 128.3)
    as_int = int.from_bytes(digest, "big")
    base57_str = to_base57(as_int)
    if len(base57_str) > 22:
        return base57_str[-22:]  # Take last 22 chars if longer
    else:
        # This is unlikely with a 128-bit input
        return base57_str.rjust(22, ALPHABET57[0])


# shortuuid uses these 57 characters (excluding similar-looking characters like 0/O, 1/I/l, etc.)
ALPHABET57 = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def to_base57(n: int) -> str:
    if n == 0:
        return ALPHABET57[0]

    out = []
    while n:
        n, rem = divmod(n, 57)
        out.append(ALPHABET57[rem])

    # reverse and return
    return "".join(reversed(out))
