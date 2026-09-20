"""The merge itself: layers, lowest priority first.

Design: every layer (defaults, a config file, environment variables,
CLI flags) produces a dict of the *same* keys, using ``None`` (or
"not present" -- simply omitting the key) to mean "this layer
expresses no opinion". :func:`resolve` walks the layers from lowest
to highest priority and lets later, non-``None`` values overwrite
earlier ones. This avoids nested if/elif/else chains entirely --
adding a new setting to an application built on conclude means adding
one entry to its own ``DEFAULTS`` dict, one caster, and (if it should
be settable that way) one CLI flag and one env var mapping, nothing
else.
"""

from collections.abc import Mapping
from typing import Any

from conclude.infer import Caster


def resolve(
    cli: Mapping[str, Any],
    env: Mapping[str, Any],
    config_file: Mapping[str, Any],
    defaults: Mapping[str, Any],
    casters: Mapping[str, Caster],
    *,
    developer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge ``defaults < config_file < env < developer < cli``,
    casting each value as it lands. ``developer`` (the private,
    project-local developer config layer -- see
    :mod:`conclude.developer`) is optional and, when given, sits
    between the environment and the CLI.

    Returns a plain dict of fully-resolved, correctly-typed settings --
    every key in ``defaults`` is present, plus any key from a layer
    that ``casters`` knows how to cast (a layer key with no matching
    caster is silently ignored, so a config file or environment can
    carry unrelated keys without upsetting the merge).

    A required-ness check (e.g. "this particular key must not still be
    None once everything is merged") is a caller-level concern, not a
    merging one -- ``resolve`` never raises for a still-``None`` result,
    only for a caster itself raising on a value it was actually given
    (e.g. an unparseable number).
    """
    merged: dict[str, Any] = {}
    for layer in (defaults, config_file, env, developer or {}, cli):
        for key, value in layer.items():
            if key not in casters:
                continue
            if value is None:
                continue
            merged[key] = casters[key](value)
    for key, value in defaults.items():
        merged.setdefault(key, value)
    return merged
