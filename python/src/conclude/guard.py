"""The gitignore guard: a check that a private, local file really is
private, shared by the developer config file
(:mod:`conclude.developer`) and, optionally, a ``.env`` file
(``App(dotenv_require_gitignored=True)``).

A file that beats -- or quietly backstops -- the environment must never
come from somewhere it shouldn't: a deployed image, a fresh clone, a CI
checkout. "It is inside a git working tree *and* git is ignoring it" is
the practical proxy for "this is somebody's private local file", and
it's checkable without git installed. :func:`check_guard` runs the
whole sequence and never raises; it reports which check stopped it, so
the callers can show a reason instead of leaving anyone to wonder why a
file has no effect.

The ignore check needs the optional ``pathspec`` package
(``pip install 'conclude[gitignore]'``). A missing ``pathspec`` is
reported as a *setup error* (:attr:`GuardResult.setup_error`) rather
than as an ordinary inactive file, so the callers can raise instead of
skipping the file quietly.

Caveats of the ignore check, all of which fail closed (the file stays
inactive) except the last: the global ``core.excludesFile`` is not
consulted; and the check is pattern matching, not git's index, so a
*tracked* file that matches an ignore pattern (``git add -f``) still
counts as ignored, even though git itself would not call it so.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_KILL_SWITCH_VALUES = frozenset({"0", "off", "false", "no"})

_PATHSPEC_HINT = (
    "the 'pathspec' package is required to verify the file is gitignored -- "
    "pip install 'conclude[gitignore]'"
)


@dataclass(frozen=True)
class GuardResult:
    """The outcome of :func:`check_guard`."""

    active: bool
    """Every check passed: the file exists, is in a git tree, and is
    ignored by it (and no kill switch is set)."""
    reason: str | None = None
    """Why not, in one short phrase, when ``active`` is ``False``."""
    setup_error: bool = False
    """``True`` only when ``pathspec`` is missing, so the ignore check
    couldn't run -- a tooling problem the caller should raise for, not a
    state to skip quietly."""


def check_guard(
    path: Path,
    *,
    kill_switch_var: str | None = None,
    environ: Mapping[str, str] | None = None,
    escape_hint: str | None = None,
) -> GuardResult:
    """Whether ``path`` may be used: not switched off, existing, inside
    a git working tree, and ignored by it. Never raises. Checks run in
    that order and the first failure is the reason returned.

    ``kill_switch_var`` names an environment variable that, set to
    ``off``/``0``/``false``/``no``, deactivates the file (read from
    ``environ``, default ``os.environ``, and only ever from the real
    environment -- it is a control knob, not a setting, so no ``.env``
    file or config layer can carry it). It is checked first, so it also
    avoids the ``pathspec`` requirement. ``escape_hint`` completes the
    missing-``pathspec`` message with the way out; by default that is
    the kill switch, if there is one.
    """
    environ = os.environ if environ is None else environ
    if kill_switch_var and environ.get(kill_switch_var, "").strip().lower() in _KILL_SWITCH_VALUES:
        return GuardResult(
            False, f"disabled by {kill_switch_var}={environ[kill_switch_var].strip()}"
        )

    if not path.is_file():
        return GuardResult(False, "file not found")

    absolute = Path(os.path.abspath(path))
    root = _find_git_root(absolute.parent)
    if root is None:
        return GuardResult(False, "not inside a git working tree")

    try:
        ignored = matches_git_ignore_rules(root, absolute)
    except ImportError:
        if escape_hint is None and kill_switch_var:
            escape_hint = f"or set {kill_switch_var}=off to skip the file"
        hint = _PATHSPEC_HINT + (f" ({escape_hint})" if escape_hint else "")
        return GuardResult(False, hint, setup_error=True)
    if not ignored:
        return GuardResult(False, "not covered by .gitignore")
    return GuardResult(True)


def _find_git_root(start: Path) -> Path | None:
    """The nearest directory at or above ``start`` containing ``.git``
    (a directory, or a file for a worktree/submodule).
    """
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return None


def matches_git_ignore_rules(root: Path, target: Path) -> bool:
    """Whether the working tree's ignore rules match ``target`` (an
    absolute path inside the working tree at ``root``).

    Pure Python: it evaluates the rules itself and never runs ``git``,
    so it answers "would these rules ignore this path?", not "does git
    say it is ignored?" -- the two can differ (see the module docstring:
    tracked files, and the global ``core.excludesFile``). The rules are
    the ``.gitignore`` files from ``root`` down to the target's
    directory plus ``root/.git/info/exclude``; nearer ``.gitignore``
    files override farther ones, the last matching pattern in a file
    wins, and an ignored parent directory ignores everything beneath
    it, as :manpage:`gitignore(5)` describes. Raises ``ImportError`` if
    the optional ``pathspec`` package isn't installed.
    """
    import pathspec

    parts = target.relative_to(root).parts
    exclude_lines = _read_lines(root / ".git" / "info" / "exclude")
    specs: dict[tuple[str, ...], Any] = {}

    def spec_for(directory_parts: tuple[str, ...]) -> Any:
        if directory_parts not in specs:
            lines = _read_lines(root.joinpath(*directory_parts, ".gitignore"))
            specs[directory_parts] = pathspec.GitIgnoreSpec.from_lines(lines) if lines else None
        return specs[directory_parts]

    exclude_spec = pathspec.GitIgnoreSpec.from_lines(exclude_lines) if exclude_lines else None

    def ignored(path_parts: tuple[str, ...], is_dir: bool) -> bool:
        # Nearest .gitignore first; the first file with any matching
        # pattern (ignore *or* negation) decides.
        for depth in range(len(path_parts) - 1, -1, -1):
            spec = spec_for(path_parts[:depth])
            if spec is None:
                continue
            relative = "/".join(path_parts[depth:]) + ("/" if is_dir else "")
            include = spec.check_file(relative).include
            if include is not None:
                return bool(include)
        if exclude_spec is not None:
            relative = "/".join(path_parts) + ("/" if is_dir else "")
            include = exclude_spec.check_file(relative).include
            if include is not None:
                return bool(include)
        return False

    # Git never descends into an ignored directory, so nothing inside
    # one can be re-included: check every ancestor directory first.
    for depth in range(1, len(parts)):
        if ignored(parts[:depth], is_dir=True):
            return True
    return ignored(parts, is_dir=False)


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
