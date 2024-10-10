from __future__ import annotations

import os

FLAG = b"gctf{???????}"


class LCG:
    def __init__(self, mod: int, mult: int, add: int, seed: int):
        self.mod = mod
        self.mult = mult
        self.add = add
        self.value = seed

    def __next__(self) -> int:
        self.value = (self.value * self.mult + self.add) % self.mod
        return self.value

    def __iter__(self) -> LCG:
        return self

    @classmethod
    def random_values(cls):
        return LCG(
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16))
        )


class Encryptor:
    def __init__(self):
        self.lcgs: tuple[LCG] = (LCG.random_values(), LCG.random_values())

    def encrypt(self, message: str) -> list[int]:
        result = []
        for ascii_char in message:
            bin_char = list(map(int, list(f"{ascii_char:07b}")))

            for bit in bin_char:
                result.append(next(self.lcgs[bit]))

            self.lcgs = (
                LCG(
                    next(self.lcgs[0]), next(self.lcgs[0]),
                    next(self.lcgs[0]), next(self.lcgs[0])
                ),
                LCG(
                    next(self.lcgs[1]), next(self.lcgs[1]),
                    next(self.lcgs[1]), next(self.lcgs[1])
                )
            )
        return result


def main() -> int:
    encryption = Encryptor()
    print(f"ct = {encryption.encrypt(FLAG)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
