"""Layer: the developer config file -- a private, project-local TOML
file that sits *above* the environment in the precedence chain::

    defaults < system < user < project < env < developer < CLI

The motivation is a local ``DATABASE_URL`` (or any other setting a
developer wants pinned while working on one project): environment
variables are process-wide and can leak between projects through a
long-lived shell, while a file whose location the *project* decides is
scoped to exactly the project it belongs to -- so it wins over ambient
environment state. Use the CLI for a one-off override.

Where the file lives is declared in the project's ``pyproject.toml``::

    [tool.conclude.developer]
    config = ".conclude.local.toml"

(relative to the directory containing that ``pyproject.toml``). The
file's format follows its name: a ``.toml`` file uses the same ``[app]``
table layout as every other config file, and anything else -- say
``.env.local`` -- is dotenv, keyed by the app's environment variable
names, so the one private file can also serve docker compose, direnv or
an IDE run configuration. It is deliberately hard to activate by accident, because a file
that beats the environment must never come from somewhere it shouldn't
-- a deployed image, a fresh clone, a CI checkout. It only applies when
*all* of these hold, and otherwise it is skipped quietly -- no error, no
warning, though :meth:`conclude.App.describe_sources` always says which
case it is:

1. the app opted in (``App(pyproject_path=AUTO)``),
2. ``pyproject.toml`` sets ``tool.conclude.developer.config``,
3. the ``<APP>_DEVELOPER_CONFIG`` kill switch is not set to ``off``,
4. the file exists,
5. it is inside a git working tree, and
6. it is covered by that tree's ignore rules (``.gitignore`` files and
   ``.git/info/exclude``) -- i.e. private by construction. Checks 3-6
   are the shared :mod:`conclude.guard`, which needs the optional
   ``pathspec`` package (``pip install 'conclude[gitignore]'``).

Two things are deliberately *not* quiet, because they are setup errors
rather than ordinary states, and hiding them would leave a developer
wondering why their file has no effect: a missing ``pathspec`` when the
ignore check is actually needed raises ``ImportError`` (the kill switch,
checked first, avoids it), and an active file that isn't valid TOML
raises :class:`conclude.ConfigFileError`. :func:`developer_status` and
``describe_sources()`` never raise; they just report.

The ignore check's caveats (the global ``core.excludesFile`` isn't
consulted; pattern matching, not git's index) are in
:mod:`conclude.guard`.
"""

import enum
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from conclude.env import load_env
from conclude.files import ConfigFileError, load_config_file
from conclude.guard import check_guard


class DeveloperState(enum.Enum):
    """Where the developer config layer stands -- the four cases
    :meth:`conclude.App.describe_sources` tells apart.
    """

    NOT_OPTED_IN = "not opted in"
    """The app never asked for a developer layer at all."""

    NOT_CONFIGURED = "not configured"
    """Opted in, but the project's ``pyproject.toml`` names no file."""

    INACTIVE = "configured, inactive"
    """A file is named, but a safety condition isn't met (see
    :attr:`DeveloperStatus.reason`); the layer contributes nothing."""

    ACTIVE = "configured, active"
    """The file is named, exists, and is gitignored; it is read."""


@dataclass(frozen=True)
class DeveloperStatus:
    """The state of the developer layer, and -- for any state but
    ``NOT_OPTED_IN`` -- why. Never raised or logged: it's information
    for :meth:`conclude.App.describe_sources` and for an app's own
    diagnostics (e.g. a ``--diagnose`` flag).
    """

    state: DeveloperState
    path: Path | None = None
    """The developer file's path, once ``pyproject.toml`` names one."""
    reason: str | None = None
    """Why ``NOT_CONFIGURED``/``INACTIVE``, in one short phrase."""
    setup_error: bool = False
    """``True`` only for a setup error rather than a normal state -- the
    ``pathspec`` package is missing, so the ignore check can't run.
    :func:`load_developer_config` raises for it instead of quietly
    skipping the file, since silently ignoring a *tooling* problem
    would leave a developer wondering why their file has no effect."""

    @property
    def active(self) -> bool:
        return self.state is DeveloperState.ACTIVE

    @property
    def format(self) -> Literal["toml", "dotenv"] | None:
        """How the file is parsed, decided by its name alone: ``"toml"``
        for a name ending in ``.toml`` (any case), ``"dotenv"`` for
        anything else (``.env.local``, ``.env``, no extension at all),
        and ``None`` until ``pyproject.toml`` names a file.
        """
        if self.path is None:
            return None
        return "toml" if self.path.name.lower().endswith(".toml") else "dotenv"

    def __str__(self) -> str:
        if self.state is DeveloperState.NOT_OPTED_IN:
            return str(self.state.value)
        if self.state is DeveloperState.NOT_CONFIGURED:
            return f"{self.state.value} ({self.reason})" if self.reason else str(self.state.value)
        detail = f" ({self.reason})" if self.state is DeveloperState.INACTIVE else ""
        return f"{self.path} -- {self.state.value}{detail}"


def developer_status(
    pyproject_path: Path | None,
    *,
    kill_switch_var: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> DeveloperStatus:
    """Work out the state of the developer layer. Never raises.

    ``pyproject_path`` is the ``pyproject.toml`` to read
    ``tool.conclude.developer.config`` from, or ``None`` if the app
    didn't opt in. ``kill_switch_var`` names an environment variable
    that, set to ``off``/``0``/``false``/``no``, deactivates a
    configured file (read from ``environ``, default ``os.environ``,
    and only ever from the real environment -- it is a control knob, not
    a setting, so no ``.env`` file or config layer can carry it).
    """
    if pyproject_path is None:
        return DeveloperStatus(DeveloperState.NOT_OPTED_IN)

    configured = _read_configured_path(pyproject_path)
    if isinstance(configured, str):
        return DeveloperStatus(DeveloperState.NOT_CONFIGURED, reason=configured)
    path = configured

    result = check_guard(path, kill_switch_var=kill_switch_var, environ=environ)
    state = DeveloperState.ACTIVE if result.active else DeveloperState.INACTIVE
    return DeveloperStatus(state, path, result.reason, setup_error=result.setup_error)


def load_developer_config(
    status: DeveloperStatus,
    defaults: Mapping[str, Any],
    table_path: list[str],
    env_vars: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The developer layer's settings from the file ``status`` says is
    active, or ``{}`` for any state but ``ACTIVE``.

    A ``.toml`` file is read like any config file: the selected TOML
    table(s), only keys in ``defaults`` (see
    :func:`conclude.load_config_file`), and an active file that isn't
    valid TOML raises :class:`conclude.ConfigFileError` (a developer
    editing their own file should be told). Any other file is dotenv
    (see :func:`conclude.load_dotenv`): ``env_vars`` -- your
    ``{setting: ENV_VAR_NAME}`` mapping, required for this format --
    says which variables in it are settings, and ``table_path`` is
    ignored because dotenv has no tables; the values are raw strings,
    cast later like any other layer. Either way, ``ImportError`` is
    raised if ``pathspec`` is missing (see
    :attr:`DeveloperStatus.setup_error`).
    """
    if status.setup_error:
        raise ImportError(f"developer config file {status.path}: {status.reason}")
    if not status.active:
        return {}
    if status.format == "dotenv":
        if env_vars is None:
            raise ValueError(
                f"developer config file {status.path} is dotenv (only .toml files are "
                "TOML), so reading it needs env_vars= to map its variables to settings"
            )
        return load_env(env_vars, {}, dotenv_path=status.path)
    try:
        return load_config_file(status.path, defaults, table_path)
    except ConfigFileError as exc:
        raise ConfigFileError(f"developer config file {exc}") from exc


def _read_configured_path(pyproject_path: Path) -> Path | str:
    """The developer file path named by ``pyproject_path`` (relative
    to its directory), or a short reason string if none is.
    """
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"no {pyproject_path}"
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return f"{pyproject_path} is not readable TOML"

    node: Any = data
    for part in ("tool", "conclude", "developer"):
        node = node.get(part) if isinstance(node, dict) else None
    value = node.get("config") if isinstance(node, dict) else None
    if value is None:
        return f"no tool.conclude.developer.config in {pyproject_path}"
    if not isinstance(value, str) or not value.strip():
        return "tool.conclude.developer.config must be a non-empty string"
    return pyproject_path.parent / value.strip()
