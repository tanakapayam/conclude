"""Inferring a caster -- and, for a setting whose default is ``None``,
the real type a provided value should become -- from a defaults dict
alone, so a setting only has to be written once (as its default
value) rather than also needing a matching entry in some separate
casters dict.

A default that's already a concrete ``bool``/``int``/``float``/``str``/
``list`` value carries its own type directly (``type(default)``). A
default of plain ``None`` doesn't -- and "optional, unset by default"
is the single most common shape a setting takes -- so wrap it with
:func:`opt` instead of writing a bare ``None``: ``opt(str)`` still
*is* ``None`` at runtime (as the actual default, and as the "not
provided in this layer" sentinel every other layer already follows),
it just also remembers what type a provided value should cast to.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from conclude.casters import (
    cast_bool,
    cast_comma_list,
    cast_float_or_none,
    cast_int_or_none,
    cast_str_or_none,
)

Caster: TypeAlias = Callable[[Any], Any]
"""A function taking a raw value from any layer (a CLI string, an env
var string, a TOML-native value, ...) and returning the properly-typed
Python value it represents -- what :func:`infer_caster` picks one of,
and what an override in ``casters=``/``overrides=`` is expected to be.
"""

_CASTERS_BY_TYPE: dict[type, Caster] = {
    bool: cast_bool,
    int: cast_int_or_none,
    float: cast_float_or_none,
    str: cast_str_or_none,
    list: cast_comma_list,
}


@dataclass(frozen=True)
class Opt:
    """A typed placeholder for "no default value, but here's the type
    a provided value should cast to" -- see :func:`opt`. Not meant to
    be constructed directly; use ``opt(type_)``.
    """

    type: type

    def __repr__(self) -> str:
        return f"opt({self.type.__name__})"


def opt(type_: type) -> Opt:
    """The default to write for an optional setting of type ``type_``
    -- e.g. ``opt(str)`` for a setting that starts out unset but,
    once a value reaches it from any layer, should be a string; or
    ``opt(list)`` for one that becomes a comma-separated list. Behaves
    as plain ``None`` everywhere a default is actually *used* (the
    defaults layer itself, and the "not provided" check every other
    layer follows) -- this wrapper only exists so caster inference has
    a type to work from.
    """
    return Opt(type_)


def infer_caster(type_: type) -> Caster:
    """The caster conclude picks for a bare Python ``type_``
    (``bool``/``int``/``float``/``str``/``list``). Raises ``TypeError``
    for anything else -- write your own caster and pass it via an
    ``overrides``/``casters`` mapping for that one setting instead of
    relying on inference.
    """
    try:
        return _CASTERS_BY_TYPE[type_]
    except KeyError as exc:
        raise TypeError(
            f"no built-in caster for type {type_!r} -- pass an explicit "
            "caster for this setting instead of relying on inference"
        ) from exc


def effective_defaults(defaults: Mapping[str, Any]) -> dict[str, Any]:
    """``defaults``, with every :class:`Opt` placeholder unwrapped to
    the ``None`` it actually stands for -- this is what the defaults
    *layer* of the merge should use as real values.
    """
    return {key: (None if isinstance(value, Opt) else value) for key, value in defaults.items()}


def infer_casters(
    defaults: Mapping[str, Any],
    overrides: Mapping[str, Caster] | None = None,
) -> dict[str, Caster]:
    """A caster for every key in ``defaults``: inferred from each
    default's type (:class:`Opt`'s wrapped type, or ``type(default)``
    for anything else) -- except for a key present in ``overrides``,
    whose caster there is used outright instead. Reach for an override
    when inference alone isn't enough for that one setting: a caster
    that needs custom error-message wording, or a string setting (like
    a separator) where an explicit empty value is meaningfully
    different from "not provided" (see :func:`conclude.cast_escaped_str`).
    """
    overrides = overrides or {}
    casters: dict[str, Caster] = {}
    for key, default in defaults.items():
        if key in overrides:
            casters[key] = overrides[key]
            continue
        type_ = default.type if isinstance(default, Opt) else type(default)
        casters[key] = infer_caster(type_)
    return casters
