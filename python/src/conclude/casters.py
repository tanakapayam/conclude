"""Reusable casters for the common shapes a CLI config setting takes.

Every caster here follows the same convention the rest of conclude
relies on: given "no opinion" input (``None``, or ``""`` for the
string-ish ones), it returns ``None`` rather than raising, so a layer
that didn't mention a setting merges away cleanly (see
:func:`conclude.merge.resolve`). A caster is applied uniformly to every
layer -- CLI string, env var string, TOML-native value -- so e.g. the
env var string ``"true"`` and a TOML boolean ``true`` normalize to the
exact same Python value before the merge happens.

These cover the common cases; an application with a setting that needs
its own bespoke casting (a "STYLE" mini-language, say) just writes its
own caster function -- :func:`conclude.merge.resolve` takes any
``dict[str, Callable]``, not specifically these.
"""

import re
from typing import Any

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on", "y"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off", "n"})

# Matches a bare integer literal with a redundant all-zero decimal
# tail ("5.0", "5.", "-3.00") -- see _try_parse_exact_int below.
_TRAILING_ZERO_DECIMAL_RE = re.compile(r"^([+-]?\d+)\.0*$")

# The exact, narrow set of backslash escapes cast_escaped_str (and
# conclude.env.load_dotenv's double-quoted values) decode -- see
# decode_backslash_escapes below for why this has to be a manual,
# character-by-character scan rather than reusing Python's own
# "unicode_escape" codec.
_BACKSLASH_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    '"': '"',
}


def decode_backslash_escapes(text: str) -> str:
    """Decode just ``\\n``/``\\t``/``\\r``/``\\\\``/``\\"`` in ``text``,
    leaving every other character -- including every non-ASCII one --
    completely untouched, and leaving any *other* backslash sequence
    (``\\x41``, ``\\u00e9``, an unrecognized ``\\q``, a trailing lone
    ``\\``) exactly as written rather than guessing at it.

    This is deliberately not ``text.encode("utf-8").decode("unicode_escape")``,
    which looks like it does the same thing but doesn't: encoding to
    UTF-8 first turns any non-ASCII character into multiple bytes, and
    "unicode_escape" then decodes those bytes one at a time as if each
    were its own Latin-1 character -- so e.g. ``"café"`` silently comes
    back as ``"cafÃ©"``, and anything outside Latin-1 (CJK text, emoji,
    ...) comes back as multi-character garbage. A plain scan for
    exactly the handful of escapes this is meant to support has no such
    failure mode, at the cost of not supporting the rest of
    "unicode_escape"'s much larger grammar (octal/hex/named escapes) --
    which was never the point here (see :func:`cast_escaped_str`).
    """
    result: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch == "\\" and i + 1 < length and text[i + 1] in _BACKSLASH_ESCAPES:
            result.append(_BACKSLASH_ESCAPES[text[i + 1]])
            i += 2
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def cast_bool(value: Any) -> bool:
    """Truthy/falsy strings/numbers/bools -> bool.

    Recognizes ``1``/``true``/``yes``/``on``/``y`` (case-insensitive) as
    true, ``0``/``false``/``no``/``off``/``n`` as false, and an empty
    string as false (the "not provided, so falsy" case a bool setting's
    absence normally means). A Python ``bool`` is passed through
    unchanged, so a TOML-native ``true``/``false`` is unaffected by this
    string-oriented check.

    Anything else raises ``ValueError`` rather than silently guessing --
    a typo like ``"tru"`` should be caught, not quietly treated as
    false just because it isn't in the recognized true set.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "":
        return False
    if text in _TRUE_STRINGS:
        return True
    if text in _FALSE_STRINGS:
        return False
    raise ValueError(f"expected a boolean (true/false/yes/no/on/off/1/0/y/n), got {value!r}")


def _try_parse_exact_int(text: str) -> int | None:
    """Parse ``text`` as an exact Python ``int`` if it's a clean
    integer literal -- optionally with a redundant all-zero decimal
    tail, e.g. ``"5"`` or ``"5.00"`` -- without ever routing it
    through ``float()``. Returns ``None`` for anything else (a
    genuinely fractional value like ``"1.9"``, scientific notation,
    ``"inf"``/``"nan"``, or non-numeric text) -- callers fall back to
    ``float()`` themselves for those, accepting its limits since
    there's no way around them for input that isn't a bare integer to
    begin with.

    The reason this exists at all: a Python ``float`` only has 53 bits
    of exact integer precision. Routing an already-exact integer (or a
    numeral string representing one) through ``float()`` first -- the
    obvious way to also accept ``"5.0"``-style input -- can silently
    corrupt it once it's larger than that: ``int(float(9007199254740993))``
    quietly becomes ``9007199254740992``, one off from the real value,
    with no error raised anywhere. Handling the "already an exact
    integer, possibly with a pointless trailing ``.0``" shape directly,
    before ``float()`` ever enters the picture, avoids that entirely.
    """
    try:
        return int(text)
    except ValueError:
        pass
    match = _TRAILING_ZERO_DECIMAL_RE.match(text)
    return int(match.group(1)) if match else None


def cast_int_or_none(value: Any, *, label: str = "a number") -> int | float | None:
    """A whole or fractional number, or ``None``.

    Returns an ``int`` when the value is a whole number (``"5"``,
    ``5.0``) and a ``float`` otherwise (``"1.5"``), which is usually
    what you want for a "seconds" or similar real-valued setting where
    whole numbers should print/compare cleanly but fractions are still
    allowed. Raises ``ValueError`` (message customizable via ``label``,
    e.g. ``"a number of seconds"``) on anything that isn't a number at
    all.

    An already-``int`` value, or a numeral string like ``"5"`` or
    ``"9007199254740993"``, is parsed as an exact integer directly --
    see :func:`_try_parse_exact_int` -- rather than always routing
    through ``float()`` first, which would silently corrupt a large
    enough integer.
    """
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    exact = _try_parse_exact_int(str(value).strip())
    if exact is not None:
        return exact
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected {label}, got {value!r}") from exc
    return int(as_float) if as_float.is_integer() else as_float


def cast_positive_int(value: Any, *, label: str = "a positive integer") -> int | None:
    """A whole number >= 1, or ``None``.

    Raises ``ValueError`` (message customizable via ``label``) on
    non-numeric input, on a number below 1, and -- unlike a naive
    ``int(float(value))`` -- on a value that parses as a number but
    isn't actually a whole one (``1.9``, which ``int()`` would
    silently truncate to ``1`` rather than reject) or isn't finite
    (``"inf"``/``"nan"``, which ``int()`` raises ``OverflowError``/
    another ``ValueError`` internally -- both are normalized to the
    one documented ``ValueError`` here, same as everything else this
    rejects).

    Like :func:`cast_int_or_none`, an already-``int`` value or a clean
    integer-literal string never goes through ``float()`` at all, so a
    large value (beyond a float's 53 bits of exact integer precision)
    is never at risk of silently losing precision along the way.
    """
    if value in (None, ""):
        return None
    if isinstance(value, int):
        as_int = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"expected {label} (a whole number), got {value!r}")
        as_int = int(value)
    else:
        exact = _try_parse_exact_int(str(value).strip())
        if exact is not None:
            as_int = exact
        else:
            try:
                as_float = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"expected {label}, got {value!r}") from exc
            if not as_float.is_integer():
                raise ValueError(f"expected {label} (a whole number), got {value!r}")
            as_int = int(as_float)
    if as_int < 1:
        raise ValueError(f"{label} must be >= 1, got {value!r}")
    return as_int


def cast_float_or_none(value: Any) -> float | None:
    """A floating-point number, or ``None``. Raises ``ValueError`` on
    anything that isn't numeric at all. Prefer :func:`cast_int_or_none`
    for a setting that should print as a whole number when the value
    given happens to be one (e.g. "5" rather than "5.0") -- this one
    always returns a ``float``.
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected a number, got {value!r}") from exc


def cast_str_or_none(value: Any) -> str | None:
    """A string, or ``None`` for "not provided" (``None`` or ``""``).

    Use this for settings where an empty string never means anything
    different from "unset" -- e.g. a filename or column name. For a
    setting where an explicit empty string IS a meaningful, distinct
    choice, use :func:`cast_escaped_str` instead.
    """
    if value in (None, ""):
        return None
    return str(value)


def cast_comma_list(value: Any) -> list[str] | None:
    """Comma-separated string (or an already-a-list TOML value) ->
    ``list[str]``, or ``None`` for "not provided".

    Each item is stripped of surrounding whitespace; empty items
    (e.g. from a trailing comma) are dropped.
    """
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def cast_escaped_str(value: Any) -> str | None:
    """Like :func:`cast_str_or_none`, but an explicit empty string is a
    real choice (e.g. "no separator at all"), not "not provided" -- so
    unlike the other string casters, ``""`` is preserved rather than
    folded into ``None``. Only an actual ``None`` means "not provided".

    Also decodes backslash escapes -- ``\\n``/``\\t``/``\\r``/``\\\\``/``\\"``
    -- into their real characters, so a CLI value like
    ``--separator='\\n\\n'`` behaves the way a user would expect; see
    :func:`decode_backslash_escapes` for exactly what is and isn't
    touched (non-ASCII text is always left alone).
    """
    if value is None:
        return None
    return decode_backslash_escapes(str(value))
