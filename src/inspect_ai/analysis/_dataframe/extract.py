import hashlib
import string

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
    record: dict[str, JsonValue] = jsonable_python(log) | {
        "id": eval_id(log.eval.run_id, log.eval.task_id),
        "log": native_path(log.location),
    }
    return record


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
