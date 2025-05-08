import hashlib

import mmh3


def mm3_hash(message: str) -> str:
    # Generate the 128-bit hash as two 64-bit integers
    h1, h2 = mmh3.hash64(message.encode("utf-8"))  # pylint: disable=E0633

    # Convert to unsigned integers and then to hexadecimal
    return f"{h1 & 0xFFFFFFFFFFFFFFFF:016x}{h2 & 0xFFFFFFFFFFFFFFFF:016x}"


def base57_id_hash(content: str) -> str:
    """Generate base67 hash for content.

    Hash the content, truncate to 128 bits, and then further truncate to 93 bits,
    returning a 22-character Base-57-URL string. Collision probability reaches 50%
    at approximately 70 trillion items.
    """
    digest_size = 16  # 128 bits
    digest = hashlib.blake2s(content.encode(), digest_size=digest_size).digest()

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
