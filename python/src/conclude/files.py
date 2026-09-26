"""Layer: config file(s).

Supports the pattern of a project-local file (in the current working
directory) overriding a user-global one (which in turn overrides an
optional, opt-in system-wide one), any number of sibling
"auxiliary" files picked up automatically, and a two-level
``[PARENT]``/``[PARENT.CHILD]`` table selection within each file --
plus resolving which table a bare positional "shorthand" argument (a
deck name, a profile name, whatever your app calls it) maps to, by
peeking at the config files themselves.

None of this cares what your app is called or what its settings are:
callers pass in the paths, the ``defaults`` dict (used only to know
which keys are worth pulling out of a TOML table), and the already-
decided ``table_path``.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ConfigFileError(ValueError):
    """A config file exists but couldn't be parsed."""


def load_raw_toml(path: Path | None) -> dict[str, Any]:
    """The raw, unfiltered TOML content of ``path``, or ``{}`` if
    ``path`` is ``None`` (that source disabled) or doesn't exist.
    Raises :class:`ConfigFileError` on a malformed file.
    """
    if path is None or not path.is_file():
        return {}
    with path.open("rb") as fh:
        try:
            return tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigFileError(f"{path}: {exc}") from exc


def table_exists(raw: Mapping[str, Any], table_path: list[str]) -> bool:
    """Whether ``raw`` has a table at ``table_path`` (e.g. ``["a", "b"]``
    for ``[a.b]``) -- as opposed to that path being absent, or present
    but holding something other than a table (a bare key/value).
    """
    node: Any = raw
    for part in table_path:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, dict)


def cwd_aux_config_paths(
    cwd_path: Path | None, pattern: str | None = ".config.*.toml"
) -> list[Path]:
    """Any sibling files matching ``pattern`` alongside ``cwd_path``
    (its own e.g. ``.config.toml``) -- e.g. ``.config.filters.toml`` --
    sorted by name for a deterministic merge order. This is what lets
    settings that don't belong in the main config file (a pile of
    generated, self-contained tables, say) live in a file of their own
    instead, while still being picked up automatically.

    ``cwd_path=None`` (that source disabled) means no directory to
    search alongside, and ``pattern=None`` turns the sibling search off
    while leaving ``cwd_path`` itself alone; either way this returns
    ``[]``.
    """
    if cwd_path is None or pattern is None:
        return []
    directory = cwd_path.parent if str(cwd_path.parent) else Path()
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob(pattern) if p != cwd_path and p.is_file())


def load_config_file(
    path: Path | None, defaults: Mapping[str, Any], table_path: list[str]
) -> dict[str, Any]:
    """Load one config file's settings from the selected TOML table(s).

    With a single-element ``table_path`` (``[PARENT]``), this just
    reads that top-level table. With a two-element ``[PARENT, CHILD]``
    ``table_path``, ``[PARENT]`` supplies shared settings and the
    nested ``[PARENT.CHILD]`` table overrides them -- so several
    profiles in one config file can share most settings and only
    override what differs, e.g. ``[japanese]`` holding defaults common
    to a deck, with ``[japanese.verbs]`` and ``[japanese.vocab]`` each
    layering their own overrides on top.

    Only keys already present in ``defaults`` are pulled out -- an
    unrelated key sitting in the same table is ignored here, same as
    everywhere else in conclude's "only keys a caster/default knows
    about matter" convention.

    ``path=None`` (that source disabled), a missing file, or a file
    with no matching table, all simply contribute nothing (same "no
    opinion" convention as every other layer). Raises
    :class:`ConfigFileError` on a malformed file.
    """
    if path is None or not path.is_file():
        return {}
    raw = load_raw_toml(path)

    parent = raw.get(table_path[0], {})
    if not isinstance(parent, dict):
        return {}
    merged = {key: parent[key] for key in defaults if key in parent}

    if len(table_path) == 2:
        child = parent.get(table_path[1], {})
        if isinstance(child, dict):
            merged.update({key: child[key] for key in defaults if key in child})

    return merged


def load_config_files(
    home_path: Path | None,
    cwd_path: Path | None,
    defaults: Mapping[str, Any],
    table_path: list[str],
    aux_pattern: str | None = ".config.*.toml",
    *,
    system_path: Path | None = None,
) -> dict[str, Any]:
    """Merge every config-file location, lowest priority first.

    ``system_path`` (the system-wide file, e.g. ``/etc/<app>/config.toml``)
    is the lowest-priority file of all: ``home_path`` overrides it on
    any key it sets, and so does everything after that. It is opt-in
    at this level too -- ``None`` (the default) means no system file is
    read.

    ``cwd_path`` (project-local) is checked -- and wins on any key it
    sets -- ahead of ``home_path`` (the user's global config file), so
    a project directory can override the user's defaults just by
    having its own local config file. Any files matching
    ``aux_pattern`` alongside ``cwd_path`` (see
    :func:`cwd_aux_config_paths`) are merged in last, in sorted-by-name
    order, each winning over anything before it -- so, on the rare
    occasion a key is set in more than one of these files, the more
    specifically-named one wins over the plain project-local one.

    Any path can be ``None`` to disable that one source entirely
    (dropping it out of the merge, same as it never existing) --
    ``cwd_path=None`` also disables the aux-file search, since there's
    no longer a directory to search alongside; ``aux_pattern=None``
    disables just the aux-file search.
    """
    merged: dict[str, Any] = {}
    merged.update(load_config_file(system_path, defaults, table_path))
    merged.update(load_config_file(home_path, defaults, table_path))
    merged.update(load_config_file(cwd_path, defaults, table_path))
    for aux_path in cwd_aux_config_paths(cwd_path, aux_pattern):
        merged.update(load_config_file(aux_path, defaults, table_path))
    return merged


def parse_config_table(value: str | None, default_table: str) -> list[str]:
    """``"PARENT"`` or ``"PARENT.CHILD"`` -> ``["PARENT"]`` or
    ``["PARENT", "CHILD"]``. ``None``/``""`` (no explicit table
    selection given at all) means ``[default_table]``.

    A stray extra dot -- ``"a..b"``, ``"a."``, ``".a"`` -- is rejected
    with ``ValueError`` rather than silently dropped: each of those
    reads as a plausible typo (a doubled separator, a trailing/leading
    one) for a table name the person actually meant to type
    correctly, not as a third way to spell ``"a.b"``/``"a"``/``"a"``.
    """
    if not value:
        return [default_table]
    parts = value.split(".")
    if len(parts) > 2 or any(not part for part in parts):
        raise ValueError(f"config table must be PARENT or PARENT.CHILD, got {value!r}")
    return parts


def _resolve_shorthand_table_path(
    shorthand: str,
    default_table: str,
    home_path: Path | None,
    cwd_path: Path | None,
    aux_pattern: str | None,
    system_path: Path | None = None,
) -> list[str]:
    """Figure out which config table a bare positional shorthand value
    (e.g. a deck name typed as ``myapp CARDS``) maps to, by peeking at
    the config files themselves: a same-named top-level ``[SHORTHAND]``
    table takes priority, as if that table had been selected
    explicitly. Failing that, a nested ``[default_table.SHORTHAND]``
    (inheriting whatever's shared in ``[default_table]``). Failing that
    too, just ``[default_table]``, same as no shorthand at all.

    Checked across ``cwd_path``, ``home_path``, ``system_path``, and
    any auxiliary files alongside ``cwd_path`` as a simple union (any one of them having
    the table counts) -- the usual value-priority between all of these
    is unaffected, since that's still handled entirely by
    :func:`load_config_files` once this returns which table(s) to read.
    A ``None`` path (that source disabled) simply contributes nothing
    to the union, same as everywhere else here.
    """
    raws = [load_raw_toml(cwd_path), load_raw_toml(home_path), load_raw_toml(system_path)]
    raws.extend(load_raw_toml(path) for path in cwd_aux_config_paths(cwd_path, aux_pattern))
    if any(table_exists(raw, [shorthand]) for raw in raws):
        return [shorthand]
    if any(table_exists(raw, [default_table, shorthand]) for raw in raws):
        return [default_table, shorthand]
    return [default_table]


def resolve_config_table(
    *,
    config_value: str | None,
    shorthand_value: str | None,
    default_table: str,
    home_path: Path | None,
    cwd_path: Path | None,
    aux_pattern: str | None = ".config.*.toml",
    system_path: Path | None = None,
) -> list[str]:
    """Figure out which TOML table(s) to read config files from.

    ``config_value`` -- your app's already-resolved "--config, or its
    env var" value, CLI winning -- always wins outright when given:
    this part can't itself be layered through the normal config-file
    mechanism (a config file can't tell us which table of itself to
    read).

    Otherwise, ``shorthand_value`` (a bare positional argument like a
    deck name) picks the table by looking the name up in the config
    files themselves -- see :func:`_resolve_shorthand_table_path`.
    Pass ``shorthand_value=None`` if your app has no such shorthand.

    Falls back to ``[default_table]`` when neither is given.
    ``home_path``/``cwd_path``/``system_path`` can each be ``None`` to
    disable that source (the shorthand lookup then simply finds
    nothing there).
    """
    if config_value:
        return parse_config_table(config_value, default_table)
    if shorthand_value:
        return _resolve_shorthand_table_path(
            shorthand_value, default_table, home_path, cwd_path, aux_pattern, system_path
        )
    return [default_table]
