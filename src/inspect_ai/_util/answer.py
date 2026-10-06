def answer_character(index: int) -> str:
    r"""
    Helper to go from array index to char, for example:

        0 -> 'A', 1 -> 'B', etc
    """
    if index < 26:
        return chr(ord("A") + index)
    else:
        return str(index - 25)


def answer_index(char: str) -> int:
    r"""
    Helper to go from char to array index, for example:

        'A' -> 0, 'B' -> 1, etc
    """
    if len(char) == 1 and char.isalpha():
        return ord(char.upper()) - ord("A")
    elif char.isnumeric():
        if int(char) == 0:
            raise ValueError(
                f"Unexpected multiple choice answer: {char} (numeric choices start at 1)"
            )
        return 25 + int(char)
    else:
        raise ValueError(
            f"Unexpected multiple choice answer: {char} (must be a letter or number)"
        )
