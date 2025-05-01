import hashlib
import string


def eval_id(run_id: str, task_id: str) -> str:
    """Generate unique eval_id based on hash of run_id and task_id.

    Hash the concatenation of *u1* and *u2* with Blake2s, truncate to 96 bits,
    and return a 17-character Base-62-URL string (no padding).
    Collision risk still well below 1% even with hundreds of billions of rows.
    """
    msg = (run_id + task_id).encode()
    digest_96 = hashlib.blake2s(msg, digest_size=12).digest()
    as_int = int.from_bytes(digest_96, "big")
    return to_base62(as_int, 17)  # 96 bits ⇒ ceil(96 / log₂62)


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
