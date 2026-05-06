from inspect_ai._util.hash import mm3_hash


def test_mm3_hash_lone_surrogate_does_not_raise():
    # `str.encode("utf-8")` rejects lone surrogates without
    # `errors="surrogatepass"`; mm3_hash must not crash on this input.
    h = mm3_hash("\udca1")
    assert isinstance(h, str)
    assert len(h) == 32  # two 64-bit hex ints concatenated


def test_mm3_hash_split_surrogate_pair_does_not_raise():
    # Shape that crashed cybench: a non-BMP character (U+1F4A1 LIGHT BULB)
    # arriving as two split surrogates embedded in text.
    h = mm3_hash("canud83d\udca1build")
    assert isinstance(h, str)
    assert len(h) == 32


def test_mm3_hash_stable_for_plain_ascii():
    # Regression guard: switching to `surrogatepass` must not change the
    # hash of valid UTF-8 inputs.
    assert mm3_hash("hello") == mm3_hash("hello")
    assert mm3_hash("a") != mm3_hash("b")
