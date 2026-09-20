"""Formatting a resolved value back into a CLI-flag token -- the
inverse of casting. Used by :meth:`conclude.App.format_invocation` to
render a standalone command line that reproduces a resolved settings
dict, with no env vars or config files needed to get back to the same
result.

Each formatter returns one of three things for a given value:

- a plain string -- the flag's value, already shell-quoted, to render
  as ``--flag=<string>``
- ``""`` (the empty string) -- render the flag bare, with no ``=value``
  at all (used for a boolean that's on)
- ``None`` -- don't render this flag at all
"""

import shlex
from collections.abc import Callable, Mapping
from typing import Any, TypeAlias

from conclude.infer import Opt

Formatter: TypeAlias = Callable[[Any], str | None]
"""A function taking a resolved value and returning the CLI-token text
to render it as (see the module docstring above for the three possible
shapes) -- what :func:`infer_formatter` picks one of, and what an
override in ``formatters=``/``overrides=`` is expected to be.
"""


def format_bool(value: bool) -> str | None:
    """``True`` -> the bare flag; ``False`` -> not rendered at all.

    This matches :meth:`conclude.App.add_arguments`'s inferred
    ``store_true``-only CLI flags for a bool setting: there's no
    inferred CLI syntax to explicitly turn a bool back to ``False``,
    so a setting whose *default* is ``True`` can't be faithfully
    reproduced this way -- write your own formatter (and, likely, your
    own CLI flag) for that one instead of relying on inference.
    """
    return "" if value else None


def format_scalar(value: Any) -> str:
    """Any other single value -- shell-quoted ``str(value)``."""
    return shlex.quote(str(value))


def format_list(value: list[Any]) -> str:
    """A list -- shell-quoted, comma-joined, matching the convention
    :func:`conclude.cast_comma_list` casts back out of.
    """
    return shlex.quote(",".join(str(item) for item in value))


_FORMATTERS_BY_TYPE: dict[type, Formatter] = {
    bool: format_bool,
    int: format_scalar,
    float: format_scalar,
    str: format_scalar,
    list: format_list,
}


def infer_formatter(type_: type) -> Formatter:
    """The formatter conclude picks for a bare Python ``type_``. Raises
    ``TypeError`` for anything else -- pass an explicit formatter for
    that one setting instead.
    """
    try:
        return _FORMATTERS_BY_TYPE[type_]
    except KeyError as exc:
        raise TypeError(
            f"no built-in formatter for type {type_!r} -- pass an explicit "
            "formatter for this setting instead of relying on inference"
        ) from exc


def infer_formatters(
    defaults: Mapping[str, Any],
    overrides: Mapping[str, Formatter] | None = None,
) -> dict[str, Formatter]:
    """A formatter for every key in ``defaults`` -- inferred the same
    way :func:`conclude.infer_casters` infers a caster (from an
    :class:`conclude.Opt`'s wrapped type, or ``type(default)``), except
    for a key present in ``overrides``, whose formatter there is used
    outright. Pair a formatter override with any matching caster
    override that needs one: a setting whose caster does something
    beyond a plain type conversion (e.g. decoding backslash escapes)
    needs a formatter that reverses that same thing, not the type's
    default one.
    """
    overrides = overrides or {}
    formatters: dict[str, Formatter] = {}
    for key, default in defaults.items():
        if key in overrides:
            formatters[key] = overrides[key]
            continue
        type_ = default.type if isinstance(default, Opt) else type(default)
        formatters[key] = infer_formatter(type_)
    return formatters
