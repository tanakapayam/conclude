"""Layer: environment variables -- the real process environment, with
an optional ``.env`` file as a fallback for anything not actually set
there.

By default a ``.env`` file is read as-is, so one can be committed with
non-secret local defaults. When it holds private values instead, pass
``require_gitignored=True`` (``App(dotenv_require_gitignored=True)``):
the file is then read only if it passes the same gitignore guard as the
developer config file -- exists, inside a git working tree, and ignored
by it (see :mod:`conclude.guard`) -- and is otherwise skipped quietly,
with :func:`dotenv_status` saying why. A missing ``pathspec`` (the
optional ``conclude[gitignore]`` extra the check needs) is the one
loud case: it raises ``ImportError``.
"""

import enum
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conclude.casters import decode_backslash_escapes
from conclude.guard import check_guard


class DotenvState(enum.Enum):
    """Where the ``.env`` fallback stands."""

    DISABLED = "disabled"
    """No ``.env`` path at all (the default)."""

    ACTIVE = "active"
    """The file will be read (if it exists) -- and, when a gitignore
    guard was requested, it passed."""

    INACTIVE = "inactive"
    """A guard was requested and the file failed it (see
    :attr:`DotenvStatus.reason`); nothing is read from it."""


@dataclass(frozen=True)
class DotenvStatus:
    """The state of the ``.env`` fallback, and why. Never raised or
    logged: information for :meth:`conclude.App.describe_sources` and
    an app's own diagnostics.
    """

    state: DotenvState
    path: Path | None = None
    reason: str | None = None
    """Why ``INACTIVE``, in one short phrase."""
    guarded: bool = False
    """Whether a gitignore guard was requested."""
    setup_error: bool = False
    """``True`` only when the guard needed ``pathspec`` and it is
    missing: :func:`load_env` raises ``ImportError`` for it instead of
    quietly skipping the file."""

    @property
    def active(self) -> bool:
        return self.state is DotenvState.ACTIVE

    def __str__(self) -> str:
        if self.state is DotenvState.DISABLED:
            return "disabled"
        if self.state is DotenvState.ACTIVE:
            return f"{self.path} -- active (gitignored)" if self.guarded else str(self.path)
        return f"{self.path} -- inactive ({self.reason})"


def dotenv_status(dotenv_path: Path | None, *, require_gitignored: bool = False) -> DotenvStatus:
    """Work out the state of the ``.env`` fallback. Never raises.

    ``dotenv_path=None`` is ``DISABLED``. Otherwise, without
    ``require_gitignored`` the file is ``ACTIVE`` whether or not it
    exists yet (exactly the pre-guard behavior); with it, the file must
    also pass :func:`conclude.guard.check_guard`.
    """
    if dotenv_path is None:
        return DotenvStatus(DotenvState.DISABLED)
    if not require_gitignored:
        return DotenvStatus(DotenvState.ACTIVE, dotenv_path)
    result = check_guard(dotenv_path, escape_hint="or stop requiring it to be gitignored")
    state = DotenvState.ACTIVE if result.active else DotenvState.INACTIVE
    return DotenvStatus(
        state, dotenv_path, result.reason, guarded=True, setup_error=result.setup_error
    )


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a ``.env``-style file into a plain ``{NAME: value}`` dict
    of strings, or ``{}`` if ``path`` doesn't exist.

    Supported syntax, one variable per line: ``NAME=value``, an
    optional leading ``export `` (ignored), blank lines and lines
    starting with ``#`` skipped, and a value optionally wrapped in
    matching quotes -- single-quoted is taken completely literally;
    double-quoted additionally decodes backslash escapes (``\\n``,
    ``\\t``, ``\\r``, ``\\\\``, ``\\"`` -- see
    :func:`conclude.casters.decode_backslash_escapes`, which non-ASCII
    characters pass through unchanged), matching common ``.env``
    convention.

    The file is read as UTF-8 on every platform, whatever the default
    text encoding; a leading byte-order mark, which some Windows
    editors add, is ignored.

    Deliberately not supported: multi-line values, inline comments
    after a value on the same line, and ``${OTHER_VAR}``-style
    interpolation -- keeping the parser small and its behavior easy to
    predict beats covering every corner of every ``.env`` dialect in
    the wild. Write a fuller ``.env`` parser yourself and pass its
    result as ``environ``/merge it in ahead of time if you need one of
    these.
    """
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = decode_backslash_escapes(value)
        result[key] = value
    return result


def load_env(
    env_vars: Mapping[str, str],
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
    require_gitignored: bool = False,
) -> dict[str, Any]:
    """Read the environment-variable layer.

    ``env_vars`` maps your setting name -> the environment variable
    name that carries it (e.g. ``{"filename": "FLASHCARDS_FILENAME"}``).
    Only variables actually present end up in the result, same "no
    opinion" convention every other layer follows.

    ``environ`` (default: ``os.environ``) is always checked first and
    always wins: pass ``dotenv_path`` to also fall back to a ``.env``
    file (see :func:`load_dotenv`) for any variable ``environ`` itself
    doesn't already set -- a real, actually-exported environment
    variable overriding a stale ``.env`` file is the conventional
    behavior every dotenv-style tool follows, and it's what lets a
    ``.env`` file be safely committed for local development without
    silently overriding whatever a deployment environment injects for
    real.

    With ``require_gitignored=True`` the ``.env`` file is only used if
    it passes the gitignore guard (see :func:`dotenv_status`), and a
    missing ``pathspec`` raises ``ImportError`` rather than quietly
    dropping the file.
    """
    environ = os.environ if environ is None else environ
    merged: dict[str, str] = {}
    if dotenv_path is not None:
        status = dotenv_status(dotenv_path, require_gitignored=require_gitignored)
        if status.setup_error:
            raise ImportError(f".env file {status.path}: {status.reason}")
        if status.active:
            merged = load_dotenv(dotenv_path)
    merged.update(environ)
    result: dict[str, Any] = {}
    for key, var_name in env_vars.items():
        if var_name in merged:
            result[key] = merged[var_name]
    return result
