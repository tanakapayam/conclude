"""Rendering a setting's default value as plain text, an ``.env``
value, or a TOML value -- the building blocks behind
:meth:`conclude.App.format_env`, :meth:`conclude.App.format_toml`, and
:meth:`conclude.App.format_cli`, which generate a ready-to-fill-in
configuration template (or a bit of reference documentation) straight
from an app's ``defaults``, so there's no hand-written example config
to keep in sync with them.

Unlike :mod:`conclude.formatters`, whose output is a shell-quoted CLI
token, everything here renders for a *reader* or a *file*: unquoted
``localhost``, not ``'localhost'``.
"""

import re
import shlex
from collections.abc import Callable
from typing import Any

from conclude.tomlwrite import toml_string

# Characters that never need quoting in an .env value: word characters
# (letters, digits, "_" -- Unicode-aware, so "café" stays bare) plus a
# few punctuation marks that are unremarkable in every .env dialect.
_ENV_BARE_RE = re.compile(r"[\w./:@%+,-]*")

_ENV_DOUBLE_QUOTE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def plain_text(value: Any, formatter: Callable[[Any], str | None] | None = None) -> str | None:
    """``value`` as unquoted, human-readable text, or ``None`` for
    "no value" (an unset ``None`` setting).

    A bool is ``true``/``false`` (never the bare-flag-or-nothing shape a
    CLI formatter gives it); a list is comma-joined, matching what
    :func:`conclude.cast_comma_list` casts back out of. ``formatter``,
    if given, is an explicit per-setting :data:`conclude.Formatter`
    override -- its (shell-quoted) output is unquoted again, so a
    setting with a custom caster/formatter pair renders as text that
    casts back to the same value.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if formatter is not None:
        rendered = formatter(value)
        if rendered is None:
            return None
        return " ".join(shlex.split(rendered))
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def env_value(text: str) -> str:
    """``text`` as the right-hand side of a ``NAME=value`` line that
    :func:`conclude.load_dotenv` reads back as exactly ``text``: bare
    when it's made only of unremarkable characters, single-quoted
    (taken literally) when it has anything else, and double-quoted with
    backslash escapes only when it contains a single quote or a
    newline/tab/carriage return, which single quotes can't carry.
    """
    if _ENV_BARE_RE.fullmatch(text):
        return text
    if "'" not in text and not any(ch in text for ch in "\n\t\r"):
        return f"'{text}'"
    return '"' + "".join(_ENV_DOUBLE_QUOTE_ESCAPES.get(ch, ch) for ch in text) + '"'


def toml_value(value: Any) -> str:
    """``value`` as a native TOML value: ``true``/``false``, an integer
    or float as-is, a list as an array, and anything else as a quoted
    string.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return toml_string(str(value))
