import mmh3


def mm3_hash(message: str) -> str:
    # Generate the 128-bit hash as two 64-bit integers
    h1, h2 = mmh3.hash64(message.encode("utf-8"))

    # Convert to unsigned integers and then to hexadecimal
    return f"{h1 & 0xFFFFFFFFFFFFFFFF:016x}{h2 & 0xFFFFFFFFFFFFFFFF:016x}"
