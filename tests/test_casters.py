import pytest

from conclude.casters import (
    _try_parse_exact_int,
    cast_bool,
    cast_comma_list,
    cast_escaped_str,
    cast_int_or_none,
    cast_positive_int,
    cast_str_or_none,
    decode_backslash_escapes,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("y", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("n", False),
        ("", False),
        ("  ", False),
    ],
)
def test_cast_bool(value, expected):
    assert cast_bool(value) is expected


@pytest.mark.parametrize("value", ["nonsense", "tru", "flase", "yess", "TRU", "2", "-1", "maybe"])
def test_cast_bool_rejects_unrecognized_strings(value):
    # A typo like "tru" should be caught, not silently treated as
    # false just because it isn't in the recognized true set.
    with pytest.raises(ValueError, match="expected a boolean"):
        cast_bool(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("5", 5),
        (5.0, 5),
        ("1.5", 1.5),
        (2.5, 2.5),
    ],
)
def test_cast_int_or_none(value, expected):
    assert cast_int_or_none(value) == expected


def test_cast_int_or_none_bad_value_raises_with_label():
    with pytest.raises(ValueError, match="a number of seconds"):
        cast_int_or_none("nope", label="a number of seconds")


# 2**53 + 1 -- the smallest positive integer a float can't represent
# exactly (float(BIG) rounds down to 2**53, silently losing the +1).
BIG = 9007199254740993


def test_cast_int_or_none_does_not_lose_precision_on_large_int():
    assert cast_int_or_none(BIG) == BIG
    assert cast_int_or_none(str(BIG)) == BIG
    assert cast_int_or_none(f"{BIG}.0") == BIG
    assert cast_int_or_none(-BIG) == -BIG


def test_cast_int_or_none_still_returns_float_for_fractional_input():
    # The precision fix shouldn't change behavior for genuinely
    # fractional values -- still returned as a float, not truncated.
    assert cast_int_or_none("1.5") == 1.5
    assert isinstance(cast_int_or_none("1.5"), float)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("1", 1),
        ("3.0", 3),
        (4, 4),
    ],
)
def test_cast_positive_int(value, expected):
    assert cast_positive_int(value) == expected


def test_cast_positive_int_rejects_zero_and_negative():
    with pytest.raises(ValueError):
        cast_positive_int("0")
    with pytest.raises(ValueError):
        cast_positive_int("-1")


def test_cast_positive_int_rejects_non_numeric():
    with pytest.raises(ValueError):
        cast_positive_int("abc")


def test_cast_positive_int_rejects_non_whole_numbers():
    # int(float(1.9)) would silently truncate to 1 -- that's hiding a
    # real input error, not a legitimate "positive integer" value.
    with pytest.raises(ValueError, match="whole number"):
        cast_positive_int(1.9)
    with pytest.raises(ValueError, match="whole number"):
        cast_positive_int("2.5")


@pytest.mark.parametrize("value", ["inf", "-inf", "Infinity", "nan"])
def test_cast_positive_int_rejects_non_finite_values(value):
    # float(value) parses these successfully, but int() on the result
    # raises OverflowError (inf) or a second ValueError (nan) -- both
    # must come out as the one documented ValueError, not leak through
    # as a different, undocumented exception type (pytest.raises below
    # would itself fail if an OverflowError escaped instead).
    with pytest.raises(ValueError, match="whole number"):
        cast_positive_int(value)


def test_cast_positive_int_does_not_lose_precision_on_large_int():
    # int(float(BIG)) would silently corrupt this -- see BIG's
    # definition above (2**53 + 1, the smallest integer a float can't
    # represent exactly). Neither a plain int input nor an equivalent
    # numeral string (with or without a redundant trailing ".0")
    # should ever be routed through float() for a value this shape.
    assert cast_positive_int(BIG) == BIG
    assert cast_positive_int(str(BIG)) == BIG
    assert cast_positive_int(f"{BIG}.0") == BIG


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("hi", "hi"),
        (5, "5"),
    ],
)
def test_cast_str_or_none(value, expected):
    assert cast_str_or_none(value) == expected


def test_cast_comma_list():
    assert cast_comma_list(None) is None
    assert cast_comma_list("") is None
    assert cast_comma_list("a,b,c") == ["a", "b", "c"]
    assert cast_comma_list("a, b ,, c") == ["a", "b", "c"]
    assert cast_comma_list(["x", " y "]) == ["x", "y"]
    assert cast_comma_list("solo") == ["solo"]


def test_cast_escaped_str_preserves_empty_string():
    assert cast_escaped_str(None) is None
    assert cast_escaped_str("") == ""


def test_cast_escaped_str_decodes_backslash_escapes():
    assert cast_escaped_str("\\n\\n") == "\n\n"
    assert cast_escaped_str("plain") == "plain"


def test_cast_escaped_str_leaves_lone_trailing_backslash_alone():
    assert cast_escaped_str("weird\\") == "weird\\"


def test_cast_escaped_str_does_not_corrupt_non_ascii_text():
    # The historical bug: text.encode("utf-8").decode("unicode_escape")
    # reinterprets each UTF-8 *byte* as a separate Latin-1 character,
    # silently corrupting any non-ASCII input ("café" -> "cafÃ©", and
    # far worse outside Latin-1).
    assert cast_escaped_str("café") == "café"
    assert cast_escaped_str("日本語") == "日本語"
    assert cast_escaped_str("emoji: 🎉") == "emoji: 🎉"


def test_cast_escaped_str_decodes_escapes_alongside_non_ascii_text():
    assert cast_escaped_str("café\\nmore") == "café\nmore"


class TestTryParseExactInt:
    """The shared helper cast_int_or_none and cast_positive_int both
    use to avoid ever routing an already-exact integer through
    float() -- see conclude.casters._try_parse_exact_int.
    """

    def test_bare_integer(self):
        assert _try_parse_exact_int("5") == 5
        assert _try_parse_exact_int("-5") == -5
        assert _try_parse_exact_int("+5") == 5

    def test_large_integer_exact(self):
        assert _try_parse_exact_int(str(BIG)) == BIG

    def test_trailing_zero_decimal(self):
        assert _try_parse_exact_int("5.0") == 5
        assert _try_parse_exact_int("5.") == 5
        assert _try_parse_exact_int("5.00") == 5
        assert _try_parse_exact_int(f"{BIG}.0") == BIG

    def test_fractional_returns_none(self):
        assert _try_parse_exact_int("1.9") is None
        assert _try_parse_exact_int("5.01") is None

    def test_non_numeric_returns_none(self):
        assert _try_parse_exact_int("abc") is None
        assert _try_parse_exact_int("inf") is None
        assert _try_parse_exact_int("nan") is None
        assert _try_parse_exact_int("1e2") is None

    def test_empty_string_returns_none(self):
        assert _try_parse_exact_int("") is None


class TestDecodeBackslashEscapes:
    """The underlying helper cast_escaped_str and .env's double-quoted
    values both share -- see conclude.casters.decode_backslash_escapes.
    """

    def test_all_five_recognized_escapes(self):
        assert decode_backslash_escapes("a\\nb") == "a\nb"
        assert decode_backslash_escapes("a\\tb") == "a\tb"
        assert decode_backslash_escapes("a\\rb") == "a\rb"
        assert decode_backslash_escapes("a\\\\b") == "a\\b"
        assert decode_backslash_escapes('a\\"b') == 'a"b'

    def test_non_ascii_untouched(self):
        for text in ("café", "日本語", "emoji: 🎉", "Ñoño", "Straße"):
            assert decode_backslash_escapes(text) == text

    def test_unrecognized_escape_preserved_literally(self):
        # Not part of the documented \n \t \r \\ \" set -- both
        # characters stay exactly as written, no guessing at hex/octal/
        # unicode escapes the way Python's own "unicode_escape" would.
        assert decode_backslash_escapes("a\\xb") == "a\\xb"
        assert decode_backslash_escapes("a\\u00e9b") == "a\\u00e9b"
        assert decode_backslash_escapes("a\\qb") == "a\\qb"

    def test_trailing_lone_backslash_preserved(self):
        assert decode_backslash_escapes("weird\\") == "weird\\"

    def test_empty_string(self):
        assert decode_backslash_escapes("") == ""

    def test_mixed_recognized_and_unrecognized(self):
        assert decode_backslash_escapes("a\\nb\\xc\\td") == "a\nb\\xc\td"
