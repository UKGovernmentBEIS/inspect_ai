from __future__ import annotations

import math
import os

from Crypto.Util.number import inverse

from ciphertext import ct as RESULTS


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

    def __repr__(self) -> str:
        return f"LCG(mod={self.mod}, mult={self.mult}, add={self.add})"

    @classmethod
    def random_values(cls):
        return LCG(
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16)),
            int.from_bytes(os.urandom(16))
        )


def calc_summand(rng_values: list[int], mod: int, mult: int) -> int:
    summands: set[int] = set()
    for val1, val2 in zip(rng_values[:1], rng_values[1:]):
        summands.add(
            (val2 - val1 * mult) % mod
        )

    assert len(summands) == 1

    return summands.pop()


def calc_multiplicator(rng_values: list[int], mod: int) -> int:
    multiplicators: set[int] = set()
    for val1, val2, val3 in zip(rng_values, rng_values[1:], rng_values[2:]):
        multiplicators.add(
            ((val2 - val3) * inverse((val1 - val2), mod)) % mod
        )
    assert len(multiplicators) == 1

    return multiplicators.pop()


def calc_mod(rng_values: list[int]) -> int:
    deltas = [
        val2 - val1 for val1, val2 in zip(rng_values, rng_values[1:])
    ]
    n_times_k = [
        d1*d3 - d2**2 for d1, d2, d3 in zip(deltas, deltas[1:], deltas[2:])
    ]

    candidates = [
        math.gcd(val1, val2) for val1, val2 in zip(n_times_k, n_times_k[1:])
    ]

    return set(candidates).pop()


def main() -> int:
    bin_char = list(map(int, list(f'{ord("g"):b}')))

    # get all values that we know comes from the LCG that
    # is used if the bit is 1
    known_consecutive_values = [
        RESULTS[0], RESULTS[1], RESULTS[4], RESULTS[5], RESULTS[6]
    ]

    # calcualte the modulus, the multiple and the additive value
    mod = calc_mod(known_consecutive_values)
    mult = calc_multiplicator(known_consecutive_values, mod)
    add = calc_summand(known_consecutive_values, mod, mult)

    # create a variable for the known LCG ans set it to none
    lcg: LCG = None

    # Build a list of lists that hold the "ciphertext" for every bit
    encrypted_chars_bits = [
        RESULTS[i*7: (i+1)*7] for i in range(len(RESULTS)//7)
    ]

    flag_bits = []

    for encrypted_char_bit in encrypted_chars_bits:
        for encrypted_bit in encrypted_char_bit:
            # if it is the first block, then we need to create the LCG
            if not lcg:
                lcg = LCG(mod=mod, mult=mult, add=add, seed=encrypted_bit)
                # the first bit was 1, therefor we can set it
                flag_bits.append(1)
                continue

            # in case we are wrong, we need to restore the previous seed
            seed = lcg.value
            rng_next_val = next(lcg)

            # check if the next ciphertext value is the same as the value that
            # the LCG would have generated
            if rng_next_val == encrypted_bit:
                flag_bits.append(1)
            else:
                # if the values did not match, we know that the plaintext at
                # this position was a 0
                flag_bits.append(0)
                # restore the previous seed to not get out of sync with the
                # LCG used during encryption
                lcg.value = seed

        lcg = LCG(next(lcg), next(lcg), next(lcg), next(lcg))

    chars_bits = [flag_bits[i*7: (i+1)*7] for i in range(len(flag_bits)//7)]
    for char_bits in chars_bits:
        result = 0
        for bit in char_bits:
            result = result << 1 | bit
        print(chr(result), end="")

    print("\n", end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
