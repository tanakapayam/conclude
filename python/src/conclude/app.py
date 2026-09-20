"""The convenience layer: give :class:`App` your application's name
and its defaults dict, and it infers everything the rest of conclude
would otherwise need spelled out by hand -- env var names, casters,
and (via :meth:`App.add_arguments`/:meth:`App.build_arg_parser`) CLI
flag names -- so the common case really is "set up the defaults, get
a working CLI/env/config-file app back".

Minimal usage::

    import conclude

    DEFAULTS = {
        "filename": conclude.opt(str),
        "shuffle": False,
        "size": 1,
    }
    app = conclude.App("myapp", DEFAULTS)

    parser = app.build_arg_parser(prog="myapp")
    namespace = parser.parse_args()
    cli = {k: v for k, v in vars(namespace).items() if v is not None}
    settings = app.resolve(cli)

Every piece of that is overridable when inference genuinely isn't
enough for one particular setting (custom --help text, a caster with
its own error-message wording, an env var name that doesn't follow
the ``APPNAME_SETTING`` convention) -- see each method's docstring --
without giving up inference for every *other* setting.

Three template generators turn the same ``defaults`` into documentation
instead of behavior -- :meth:`App.format_env`, :meth:`App.format_toml`,
and :meth:`App.format_cli` render every setting's name in that layer
next to its default value, ready to paste into a ``.env`` file, a
config file, or a README, with no hand-written example to keep in sync.

Two more pieces of common boilerplate ``App`` handles:
:meth:`App.add_print_invocation_argument` adds the conventional
``--print-invocation`` flag for :meth:`App.format_invocation` to pair
with, and a ``.env`` file can supply the environment-variable layer's
fallback (see :meth:`App.load_env`) -- opt-in only, via
``dotenv_path=AUTO`` or a specific path, since reading an arbitrary
local file looking for secrets is not something that should ever
happen by accident.

The full precedence chain, lowest to highest::

    defaults < system < user < project < env < developer < CLI

where "system" is an optional, opt-in system-wide config file (see
``config_system_path`` on :class:`App`), "user" and "project" are the
user-global and project-local config files, "env" includes the opt-in
``.env`` fallback, and "developer" is an optional, opt-in, private
project-local file that beats the environment (see
``pyproject_path`` on :class:`App` and :mod:`conclude.developer`).

Any path -- ``dotenv_path``, ``config_system_path``, ``pyproject_path``,
``config_home_path``, ``config_cwd_path`` -- can be set to ``None`` to
disable that source outright (handy for
debugging, or for an app that deliberately shouldn't read a given
layer at all); :meth:`App.describe_sources` renders a short summary of
which sources are active, meant for your program's own ``--help``
text.
"""

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from conclude.developer import DeveloperStatus
from conclude.developer import developer_status as _developer_status
from conclude.developer import load_developer_config as _load_developer_config
from conclude.env import DotenvStatus
from conclude.env import dotenv_status as _dotenv_status
from conclude.env import load_env as _load_env
from conclude.files import load_config_files as _load_config_files
from conclude.files import resolve_config_table as _resolve_config_table
from conclude.formatters import Formatter, infer_formatters
from conclude.infer import Caster, Opt, effective_defaults, infer_casters
from conclude.merge import resolve as _resolve
from conclude.naming import cli_flag_name, config_key_name, env_var_name
from conclude.paths import default_config_home_path, default_config_system_path
from conclude.templates import env_value, plain_text, toml_value
from conclude.tomlwrite import toml_key, toml_string


class _AutoType:
    """The type of :data:`conclude.AUTO` -- see that constant. A named
    class (rather than a bare ``object()``) purely so it reprs as
    ``AUTO`` instead of a memory address, which matters here since
    ``AUTO`` is public and shows up in ``repr(App(...))``.
    """

    def __repr__(self) -> str:
        return "AUTO"


AUTO = _AutoType()
"""Sentinel meaning "compute the conventional default for this path",
distinct from both an unset field and an explicit ``None``. Used for
:class:`App`'s file-based sources:

- ``config_home_path`` defaults to ``AUTO`` -- i.e. config files are
  read from ``~/.config/<name>/config.toml`` unless you say otherwise.
  Pass ``config_home_path=None`` to disable that source instead, or a
  ``Path`` for a specific location.
- ``dotenv_path`` defaults to plain ``None`` (no ``.env`` file read at
  all) -- unlike the user/project config files, reading arbitrary
  files for environment-variable-shaped secrets is exactly the kind of
  thing that should never happen just because nobody thought about
  it, so conclude requires you to opt in: pass ``dotenv_path=AUTO``
  for the conventional ``./.env``, or a ``Path`` for a specific file.
- ``config_system_path`` defaults to plain ``None`` too (no system-wide
  config file read at all) -- machine-wide configuration changing an
  app's behavior for every user on the box is a decision about the
  program, not something to pick up by accident. Pass
  ``config_system_path=AUTO`` for the conventional
  ``/etc/<name>/config.toml``, or a ``Path`` for a specific file.
- ``pyproject_path`` defaults to plain ``None`` as well (no developer
  config layer at all): a file that beats the environment is something
  an app should turn on deliberately. Pass ``pyproject_path=AUTO`` to
  read ``tool.conclude.developer.config`` from ``./pyproject.toml``, or
  a ``Path`` for a specific ``pyproject.toml``.
- ``config_cwd_path`` doesn't use ``AUTO`` -- its conventional default
  (``./.config.toml``) doesn't depend on anything else about the
  ``App``, so the field's own default already *is* that path; pass
  ``None`` to disable it the same way as the other two.
"""


@dataclass(frozen=True)
class App:
    """Everything conclude can infer from an app name + a defaults
    dict, bundled up so you don't have to keep passing both to every
    function separately.

    ``casters``/``formatters``/``env_vars``, if given, override
    specific keys' inferred value outright -- every key not mentioned
    there still comes from inference on its own, so you only override
    what actually needs it.

    Any of ``dotenv_path``/``config_system_path``/``config_home_path``/
    ``config_cwd_path`` can be set to ``None`` to disable that source
    entirely -- handy for
    debugging (ruling a source out while narrowing down where a value
    is coming from), or for an app that deliberately doesn't want a
    given layer at all (e.g. one that should never read a project-local
    ``.config.toml`` regardless of cwd). See :data:`AUTO` for how the
    conventional default is opted into for each, and
    :meth:`describe_sources` for surfacing which sources are active to
    the person running your program.

    Config-file precedence, lowest to highest, is
    ``system < user < project`` (``config_system_path``,
    ``config_home_path``, ``config_cwd_path`` plus its sibling aux
    files), all of which sit above the hardcoded defaults and below the
    environment and CLI: ``defaults < system < user < project < env <
    developer < CLI``. ``config_system_path`` is the only one of the
    three that is off by default. ``developer`` is a fourth, separate
    kind of file: private, project-local, and *above* the environment
    (``pyproject_path``, off by default -- see :mod:`conclude.developer`
    for exactly when it applies, and :meth:`developer_status`).
    """

    name: str
    defaults: Mapping[str, Any]
    casters: Mapping[str, Caster] | None = None
    formatters: Mapping[str, Formatter] | None = None
    env_vars: Mapping[str, str] | None = None
    # Unlike the other two sources, .env reads whatever's sitting in
    # the current directory looking for environment-variable-shaped
    # secrets -- so, unlike them, it defaults to off. Pass
    # dotenv_path=AUTO for the conventional ./.env, opting in on
    # purpose, or a specific Path.
    dotenv_path: Path | _AutoType | None = None
    config_home_path: Path | _AutoType | None = AUTO
    config_cwd_path: Path | None = field(default_factory=lambda: Path(".config.toml"))
    default_table: str | None = None
    # Machine-wide config (/etc/<name>/config.toml), the lowest-priority
    # config file. Off by default, like .env: pass config_system_path=AUTO
    # to opt in on purpose, or a specific Path. (Declared last so
    # existing positional construction keeps working.)
    config_system_path: Path | _AutoType | None = None
    # Opt-in developer config layer: the pyproject.toml whose
    # tool.conclude.developer.config names a private, gitignored file
    # that beats the environment. Off by default; AUTO -> ./pyproject.toml.
    pyproject_path: Path | _AutoType | None = None
    # Which sibling files next to the project-local config file are
    # merged in too (sorted by name, each beating the plain file).
    # ``None`` keeps the project file but drops the sibling search --
    # otherwise any stray ``.config.<anything>.toml`` joins the merge.
    config_cwd_aux_pattern: str | None = ".config.*.toml"
    # Hold the .env fallback to the same standard as the developer file:
    # read it only if it exists, sits in a git working tree, and is
    # gitignored. Off by default (a committed .env of non-secret defaults
    # is common); needs the optional ``pathspec`` (conclude[gitignore]).
    dotenv_require_gitignored: bool = False

    def __post_init__(self) -> None:
        if self.config_home_path is AUTO:
            # frozen dataclass -- object.__setattr__ is the documented
            # way to fill in a computed default in __post_init__.
            object.__setattr__(self, "config_home_path", default_config_home_path(self.name))
        if self.dotenv_path is AUTO:
            object.__setattr__(self, "dotenv_path", Path(".env"))
        if self.config_system_path is AUTO:
            object.__setattr__(self, "config_system_path", default_config_system_path(self.name))
        if self.pyproject_path is AUTO:
            object.__setattr__(self, "pyproject_path", Path("pyproject.toml"))

    @property
    def resolved_defaults(self) -> dict[str, Any]:
        """``defaults`` with every :func:`conclude.opt` placeholder
        unwrapped to the ``None`` it stands for."""
        return effective_defaults(self.defaults)

    @property
    def resolved_casters(self) -> dict[str, Caster]:
        """A caster per setting: inferred from each default's type,
        with ``self.casters`` overriding specific keys."""
        return infer_casters(self.defaults, self.casters)

    @property
    def resolved_formatters(self) -> dict[str, Formatter]:
        """A formatter per setting -- the inverse of a caster, used by
        :meth:`format_invocation` -- inferred from each default's
        type, with ``self.formatters`` overriding specific keys."""
        return infer_formatters(self.defaults, self.formatters)

    @property
    def resolved_env_vars(self) -> dict[str, str]:
        """An ``APPNAME_SETTING``-style env var name per setting, with
        ``self.env_vars`` overriding specific keys."""
        inferred = {key: env_var_name(self.name, key) for key in self.defaults}
        inferred.update(self.env_vars or {})
        return inferred

    @property
    def resolved_config_system_path(self) -> Path | None:
        """The system-wide config file path in effect -- ``None`` by
        default (source disabled; see :data:`AUTO` for opting into the
        conventional ``/etc/<name>/config.toml``), or whatever ``Path``
        ``config_system_path`` was set to. Lowest priority of the
        config files: user-global, project-local, and everything above
        those override it."""
        return cast("Path | None", self.config_system_path)  # AUTO resolved in __post_init__

    @property
    def resolved_pyproject_path(self) -> Path | None:
        """The ``pyproject.toml`` the developer config layer reads its
        file location from -- ``None`` by default (layer not opted
        into; see :data:`AUTO` for ``./pyproject.toml``), or whatever
        ``Path`` ``pyproject_path`` was set to."""
        return cast("Path | None", self.pyproject_path)  # AUTO resolved in __post_init__

    @property
    def resolved_config_home_path(self) -> Path | None:
        """The user-global config file path in effect -- the
        conventional ``~/.config/<name>/config.toml`` (the default,
        ``config_home_path=AUTO``) unless set to a specific ``Path``,
        or ``None`` if set to ``None`` (source disabled)."""
        return cast("Path | None", self.config_home_path)  # AUTO resolved in __post_init__

    @property
    def resolved_config_cwd_path(self) -> Path | None:
        """The project-local config file path in effect (default:
        ``./.config.toml``), or ``None`` if ``config_cwd_path`` was set
        to ``None`` (source disabled, including the aux-file search
        alongside it; see ``config_cwd_aux_pattern`` to drop only the
        sibling search)."""
        return self.config_cwd_path

    @property
    def resolved_dotenv_path(self) -> Path | None:
        """The ``.env`` file path in effect -- ``None`` by default
        (source disabled; see :data:`AUTO` for opting into the
        conventional ``./.env``), or whatever ``Path`` ``dotenv_path``
        was set to."""
        return cast("Path | None", self.dotenv_path)  # AUTO resolved in __post_init__

    @property
    def resolved_default_table(self) -> str:
        return self.default_table or self.name

    def describe_sources(self, environ: Mapping[str, str] | None = None) -> str:
        """A short, human-readable summary of which config-file/``.env``
        sources this app checks, lowest priority first -- or
        ``"disabled"`` for any turned off (or, for the system config
        and ``.env`` file, never opted into; a ``.env`` file held to
        ``dotenv_require_gitignored`` also says whether it is active,
        or why not; the project row also lists
        the sibling-file pattern unless ``config_cwd_aux_pattern`` is
        ``None``) via
        ``config_system_path``/``config_home_path``/``config_cwd_path``/
        ``dotenv_path`` being ``None``.

        The last row is the developer config layer, which is never
        merely on or off: it says which of ``not opted in``,
        ``not configured``, ``configured, inactive (<why>)``, or
        ``configured, active`` it is (see :meth:`developer_status`;
        ``environ`` is only consulted for its kill switch).

        Meant to be dropped into ``--help`` output (e.g. as part of an
        ``ArgumentParser``'s ``epilog``) -- which sources exist at all
        is a fact about how this ``App`` was built, true for every run
        of the program, so it belongs where someone goes to understand
        the program's shape before running it. This is deliberately
        *not* something :meth:`format_invocation` reports: that method
        describes one run's already-resolved *values*, not which
        layers were even in play to produce them.

        This renders as aligned, multi-line text -- pass
        ``formatter_class=argparse.RawDescriptionHelpFormatter`` (or
        ``RawTextHelpFormatter``) to your ``ArgumentParser``, or
        argparse's default formatter will re-wrap it into one run-on
        paragraph and lose the alignment entirely.
        """
        project = self.resolved_config_cwd_path
        project_text = "disabled"
        if project is not None:
            project_text = str(project)
            if self.config_cwd_aux_pattern is not None:
                project_text += f", {project.parent / self.config_cwd_aux_pattern}"

        def path_text(path: Path | None) -> str:
            return str(path) if path is not None else "disabled"

        texts = [
            ("system config", path_text(self.resolved_config_system_path)),
            ("user config", path_text(self.resolved_config_home_path)),
            ("project config", project_text),
            (".env file", str(self.dotenv_status())),
            ("developer config", str(self.developer_status(environ))),
        ]
        label_width = max(len(label) for label, _ in texts)
        lines = ["config sources:"]
        for label, value in texts:
            lines.append(f"  {label.ljust(label_width)}  {value}")
        return "\n".join(lines)

    def add_arguments(
        self,
        parser: argparse.ArgumentParser,
        *,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
        skip: Iterable[str] = (),
    ) -> None:
        """Add one CLI flag per setting in ``defaults`` to ``parser``.

        The flag name is inferred (``filter_col`` -> ``--filter-col``,
        via :func:`conclude.naming.cli_flag_name`), ``dest`` is always
        the setting's own key (so the parsed namespace's attributes
        line up 1:1 with ``defaults``, whatever the flag looks like),
        and the action is inferred from the setting's type: a
        bool-typed setting (a bare ``False``/``True`` default, or
        ``opt(bool)``) becomes a ``store_true`` flag; anything else
        becomes a plain value flag.

        ``overrides[key]``, if given, is a dict of kwargs merged into
        that one flag's ``add_argument()`` call -- typically a
        hand-written ``help`` string and/or ``metavar``, which
        inference has no way to guess well. ``skip`` leaves specific
        keys out of this loop entirely, for a setting you're adding a
        hand-built flag for yourself instead (e.g. a positional
        argument, or one flag standing in for several settings).
        """
        overrides = overrides or {}
        skip = set(skip)
        for key, default in self.defaults.items():
            if key in skip:
                continue
            type_ = default.type if isinstance(default, Opt) else type(default)
            kwargs: dict[str, Any] = {"dest": key, "default": None}
            if type_ is bool:
                kwargs["action"] = "store_true"
            else:
                kwargs["metavar"] = key.upper()
            kwargs.update(overrides.get(key, {}))
            parser.add_argument(cli_flag_name(key), **kwargs)

    def build_arg_parser(self, **parser_kwargs: Any) -> argparse.ArgumentParser:
        """A fresh ``argparse.ArgumentParser`` with one inferred flag
        per setting already added via :meth:`add_arguments` -- for an
        app that doesn't need anything beyond that. ``parser_kwargs``
        pass straight through to ``ArgumentParser()`` (``prog``,
        ``description``, ...). For a parser that also needs a
        positional argument, extra non-setting flags, or per-flag help
        text, build the parser yourself and call :meth:`add_arguments`
        (with ``overrides``/``skip`` as needed) instead of this.
        """
        parser = argparse.ArgumentParser(**parser_kwargs)
        self.add_arguments(parser)
        return parser

    def add_print_invocation_argument(
        self,
        parser: argparse.ArgumentParser,
        *,
        flag: str = "--print-invocation",
        dest: str = "print_invocation",
        help: str | None = None,
    ) -> None:
        """Add a conventional ``--print-invocation`` flag to ``parser``.

        This only adds the flag -- it's the same shape for every app
        (a bare, ``store_true`` flag defaulting to ``False``), so
        there's nothing to infer per setting the way
        :meth:`add_arguments` infers one flag per entry in
        ``defaults``. Your app checks ``namespace.<dest>`` itself, same
        as any other non-setting flag (``--diagnose``, say), and if
        it's true, prints ``app.format_invocation(resolved, ...)`` and
        exits however it normally would -- conclude doesn't force an
        exit here, since that's a decision about your app's own
        control flow, not something a config library should make for
        you.
        """
        parser.add_argument(
            flag,
            dest=dest,
            action="store_true",
            default=False,
            help=help
            or (
                "Print the equivalent standalone command line, with every "
                "setting fully resolved through the CLI/env/config-file/"
                "default chain, then exit without doing anything else."
            ),
        )

    def load_env(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
        """The environment-variable layer, using ``resolved_env_vars``.

        Falls back to a ``.env`` file at ``self.resolved_dotenv_path``
        for any variable not actually set in the real environment --
        see :func:`conclude.load_dotenv` for the file format, and
        :func:`conclude.load_env` for why a real environment variable
        always wins over it. Off by default (``dotenv_path=None``);
        pass ``dotenv_path=AUTO`` (for the conventional ``./.env``) or
        a specific ``Path`` to this ``App`` to enable it. With
        ``dotenv_require_gitignored=True`` the file is read only if it
        is gitignored (see :meth:`dotenv_status`); a missing ``pathspec``
        then raises ``ImportError``.
        """
        return _load_env(
            self.resolved_env_vars,
            environ,
            dotenv_path=self.resolved_dotenv_path,
            require_gitignored=self.dotenv_require_gitignored,
        )

    def dotenv_status(self) -> DotenvStatus:
        """Where the ``.env`` fallback stands -- see
        :class:`conclude.DotenvStatus`. Never raises. Without
        ``dotenv_require_gitignored`` it is ``DISABLED`` or plain
        ``ACTIVE``; with it, ``ACTIVE`` only if the file passes the
        gitignore guard (:mod:`conclude.guard`), else ``INACTIVE`` with
        the reason.
        """
        return _dotenv_status(
            self.resolved_dotenv_path, require_gitignored=self.dotenv_require_gitignored
        )

    def load_config_files(
        self,
        table_path: list[str] | None = None,
        *,
        cwd_path: Path | None = None,
    ) -> dict[str, Any]:
        """The config-file layer, merged across the usual locations --
        see :func:`conclude.load_config_files`. Defaults to this app's
        own ``[name]`` table if ``table_path`` isn't given, and this
        app's own ``resolved_config_system_path``/
        ``resolved_config_home_path``/``resolved_config_cwd_path`` (any
        of which may be ``None``, disabling that source) if
        ``cwd_path`` isn't given here.
        """
        return _load_config_files(
            self.resolved_config_home_path,
            cwd_path if cwd_path is not None else self.resolved_config_cwd_path,
            self.resolved_defaults,
            table_path or [self.resolved_default_table],
            aux_pattern=self.config_cwd_aux_pattern,
            system_path=self.resolved_config_system_path,
        )

    def developer_status(self, environ: Mapping[str, str] | None = None) -> DeveloperStatus:
        """Where the developer config layer stands -- see
        :class:`conclude.DeveloperStatus`. Never raises, so it's safe to
        call from ``--help`` or a diagnostics flag. The kill switch is
        the ``<NAME>_DEVELOPER_CONFIG`` environment variable (from
        ``environ``, default ``os.environ``): set it to ``off`` to
        deactivate a configured file, e.g. in a deployment.
        """
        return _developer_status(
            self.resolved_pyproject_path,
            kill_switch_var=env_var_name(self.name, "developer_config"),
            environ=environ,
        )

    def load_developer_config(
        self,
        table_path: list[str] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """The developer config layer -- ``{}`` unless
        :meth:`developer_status` is active. A ``.toml`` file is read
        like a config file: the same table(s) (this app's own ``[name]``
        table if ``table_path`` isn't given; pass the same
        ``table_path`` you gave :meth:`load_config_files` when you chose
        one yourself, see :meth:`resolve_config_table`, so both layers
        read the same table). Any other file name is dotenv -- say
        ``.env.local`` -- and is keyed by ``resolved_env_vars``, with no
        tables, so ``table_path`` doesn't apply to it.
        """
        return _load_developer_config(
            self.developer_status(environ),
            self.resolved_defaults,
            table_path or [self.resolved_default_table],
            env_vars=self.resolved_env_vars,
        )

    def resolve_config_table(
        self,
        *,
        config_value: str | None = None,
        shorthand_value: str | None = None,
        cwd_path: Path | None = None,
    ) -> list[str]:
        """Which config-file table(s) to read -- see
        :func:`conclude.resolve_config_table`, using this app's own
        default table name and config-file paths (either of which may
        be ``None``, disabling that source from the shorthand lookup)."""
        return _resolve_config_table(
            config_value=config_value,
            shorthand_value=shorthand_value,
            default_table=self.resolved_default_table,
            home_path=self.resolved_config_home_path,
            cwd_path=cwd_path if cwd_path is not None else self.resolved_config_cwd_path,
            aux_pattern=self.config_cwd_aux_pattern,
            system_path=self.resolved_config_system_path,
        )

    def resolve(
        self,
        cli: Mapping[str, Any],
        env: Mapping[str, Any] | None = None,
        config_file: Mapping[str, Any] | None = None,
        developer: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge ``cli`` (already parsed, e.g. from
        ``vars(namespace)``, with unset/``None`` keys left in or
        dropped -- either way, only non-``None`` values win) with the
        env-var, config-file, and developer-config layers -- loading
        whichever of those three isn't passed in already -- against
        this app's inferred defaults and casters, lowest-priority-first
        (``defaults < config files < env < developer < cli``). Pass
        ``env``/``config_file``/``developer`` yourself when you need to
        choose a specific config table first (see
        :meth:`resolve_config_table`) rather than this app's plain
        default table -- ``developer=app.load_developer_config(table_path)``
        alongside ``config_file=app.load_config_files(table_path)``.
        """
        if env is None:
            env = self.load_env()
        if config_file is None:
            config_file = self.load_config_files()
        if developer is None:
            developer = self.load_developer_config()
        return _resolve(
            cli,
            env,
            config_file,
            self.resolved_defaults,
            self.resolved_casters,
            developer=developer,
        )

    def format_invocation(
        self,
        resolved: Mapping[str, Any],
        *,
        prog: str | None = None,
        formatters: Mapping[str, Formatter] | None = None,
        compare_defaults: Mapping[str, Any] | None = None,
        always_include: Iterable[str] = (),
        skip: Iterable[str] = (),
    ) -> str:
        """Render a standalone command line that reproduces ``resolved``
        (a dict from :meth:`resolve`, or an equivalent one you built
        yourself) with no env vars, config files, or CLI shorthand
        needed to get back to the same result -- handy for debugging a
        confusing resolved setup, or turning one into a documented,
        copy-pasteable command.

        A setting whose resolved value equals its default (see
        ``compare_defaults``) is left out entirely: omitting a flag
        already reproduces that default on its own, so there's nothing
        to gain by spelling it out, and every setting an app defines
        is covered by this rule automatically -- there's no separate
        list of "settings worth mentioning" to maintain by hand. A
        setting genuinely required in practice (no real default,
        conventionally written ``opt(str)`` or similar) falls out of
        this the same way, with no special-casing needed: its
        "default" is ``None``, a resolved run essentially never
        matches that, so it's always included.

        ``prog``, if given, is prepended as the first token (with
        nothing else quoted around it); leave it out to get back just
        the space-joined flags, e.g. to assemble your own command line
        around them (see ``skip`` below).

        ``formatters`` overrides specific keys' inferred formatter --
        pair it with a matching ``casters`` override on this ``App``
        for a setting whose caster does more than a plain type
        conversion (e.g. decodes backslash escapes), since the
        inferred formatter for that setting's bare type would produce
        text that doesn't cast back to the same value.

        ``compare_defaults`` overrides what counts as "the default" for
        this call only, instead of this app's own ``resolved_defaults``
        -- for a setting whose *effective* default is something other
        than what's in ``defaults`` because your app substitutes a
        fallback value after ``resolve()`` runs (e.g. an ``opt(str)``
        setting that becomes a hardcoded constant when still ``None``
        after merging). Pass ``{**app.resolved_defaults, "key": value}``
        to override just that one key.

        ``always_include`` forces specific keys to be shown even when
        they equal their default. ``skip`` leaves specific keys out of
        this call entirely -- typically because your app renders them
        itself, with its own conditional logic ``format_invocation``
        has no way to know about (e.g. a flag only meaningful given
        some other setting's value, or one setting whose value gets
        folded into another's before display).
        """
        formatters = infer_formatters(self.defaults, formatters or self.formatters)
        defaults = compare_defaults if compare_defaults is not None else self.resolved_defaults
        always_include = set(always_include)
        skip = set(skip)

        parts = [prog] if prog else []
        for key in self.defaults:
            if key in skip:
                continue
            value = resolved.get(key)
            if value == defaults.get(key) and key not in always_include:
                continue
            rendered = formatters[key](value)
            if rendered is None:
                continue
            flag = cli_flag_name(key)
            parts.append(flag if rendered == "" else f"{flag}={rendered}")
        return " ".join(parts)

    def _template_rows(
        self,
        skip: Iterable[str],
        formatters: Mapping[str, Formatter] | None,
        defaults: Mapping[str, Any] | None,
    ) -> list[tuple[str, Any, Formatter | None]]:
        """``(key, default value, explicit formatter or None)`` per
        setting, in ``defaults`` order, for the ``format_env``/
        ``format_toml``/``format_cli`` template generators. Only an
        *explicitly* overridden formatter is ever returned: a setting
        of a plain built-in type renders directly from its value, so
        these never need (and never raise for lack of) an inferred
        formatter, unlike :meth:`format_invocation`.
        """
        overrides = formatters or self.formatters or {}
        values = {**self.resolved_defaults, **effective_defaults(defaults or {})}
        skip = set(skip)
        return [(key, values[key], overrides.get(key)) for key in self.defaults if key not in skip]

    def format_env(
        self,
        *,
        skip: Iterable[str] = (),
        formatters: Mapping[str, Formatter] | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> str:
        """An environment-variable template: one ``NAME=value`` line
        per setting, with the env var name from ``resolved_env_vars``
        and the setting's default as the value --

        .. code-block:: text

            MYAPP_HOST=localhost
            MYAPP_PORT=8080
            MYAPP_DEBUG=false

        The output is valid ``.env`` file syntax (see
        :func:`conclude.load_dotenv`): a value is quoted only when it
        has to be, and always so that it reads back as exactly the
        default. A setting with no default (``None``, i.e. ``opt(str)``
        and friends) is a commented-out ``# NAME=`` placeholder,
        since an unset variable and an empty one are different things
        to a shell.

        ``skip`` leaves specific settings out. ``defaults`` overrides
        what's shown as the default for this call only (merged over
        this app's own ``resolved_defaults``) -- for a setting whose
        *effective* default isn't what's in ``defaults`` because your
        app substitutes a fallback after :meth:`resolve` runs (e.g. an
        ``opt(str)`` that becomes a hardcoded constant when still
        ``None``). ``formatters`` overrides the explicit formatters for
        this call (default: this app's own ``formatters``); only a
        setting with such an explicit formatter uses one here -- pair
        it with its custom caster so the text casts back to the same
        value.
        """
        env_vars = self.resolved_env_vars
        lines = []
        for key, value, formatter in self._template_rows(skip, formatters, defaults):
            text = plain_text(value, formatter)
            name = env_vars[key]
            lines.append(f"# {name}=" if text is None else f"{name}={env_value(text)}")
        return "\n".join(lines)

    def format_toml(
        self,
        *,
        table: str | Sequence[str] | None = None,
        header: bool = True,
        skip: Iterable[str] = (),
        formatters: Mapping[str, Formatter] | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> str:
        """A config-file template: a ``[table]`` header and one
        ``key = value`` line per setting, with the setting's default as
        the value --

        .. code-block:: text

            [myapp]
            host = "localhost"
            port = 8080
            debug = false

        Values are native TOML (``8080``, ``false``, ``["a", "b"]``,
        not strings) so the template reads like a config file a person
        would write; a setting with an explicit formatter (see
        below) is written as the string that formatter produces,
        since that's the text its custom caster expects. A setting with
        no default (``None``) is a commented-out ``# key =``
        placeholder.

        ``table`` is the header's name -- a string, or a sequence for a
        nested table (``["myapp", "deck"]`` -> ``[myapp.deck]``) --
        defaulting to this app's ``resolved_default_table``. Pass
        ``header=False`` for just the key lines, to paste under a
        header that's already in the file. ``skip``, ``formatters``,
        and ``defaults`` work as in :meth:`format_env`.
        """
        lines = []
        if header:
            if table is None:
                path = [self.resolved_default_table]
            elif isinstance(table, str):
                path = [table]
            else:
                path = list(table)
            if path:
                lines.append("[" + ".".join(toml_key(part) for part in path) + "]")
        for key, value, formatter in self._template_rows(skip, formatters, defaults):
            name = toml_key(config_key_name(key))
            if formatter is not None and not isinstance(value, bool):
                text = plain_text(value, formatter)
                rendered = None if text is None else toml_string(text)
            else:
                rendered = None if value is None else toml_value(value)
            lines.append(f"# {name} =" if rendered is None else f"{name} = {rendered}")
        return "\n".join(lines)

    def format_cli(
        self,
        *,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
        skip: Iterable[str] = (),
        formatters: Mapping[str, Formatter] | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> str:
        """A CLI reference: one line per flag :meth:`add_arguments`
        adds, with a ``(default: ...)`` column, aligned --

        .. code-block:: text

            --host <HOST>       (default: localhost)
            --port <PORT>       (default: 8080)
            --debug             (default: false)
            --timeout <TIMEOUT> (default: 30)

        A bool setting is a bare flag; every other setting shows its
        metavar (``key.upper()``, or ``overrides[key]["metavar"]`` --
        pass the same ``overrides`` you gave :meth:`add_arguments` so
        the two agree; nothing else in it, ``help`` included, is
        rendered). A setting with no default (``None``) shows
        ``(default: none)``, and an empty string shows ``""``.

        ``skip``, ``formatters``, and ``defaults`` work as in
        :meth:`format_env`; ``skip`` should match the ``skip`` you gave
        :meth:`add_arguments`, so a flag you build by hand isn't
        listed.
        """
        overrides = overrides or {}
        rows: list[tuple[str, str]] = []
        for key, value, formatter in self._template_rows(skip, formatters, defaults):
            declared = self.defaults[key]
            type_ = declared.type if isinstance(declared, Opt) else type(declared)
            flag = cli_flag_name(key)
            if type_ is not bool:
                metavar = overrides.get(key, {}).get("metavar", key.upper())
                metavars = [metavar] if isinstance(metavar, str) else list(metavar)
                flag += " " + " ".join(f"<{name}>" for name in metavars)
            text = plain_text(value, formatter)
            rows.append((flag, "none" if text is None else text or '""'))
        width = max((len(flag) for flag, _ in rows), default=0)
        return "\n".join(f"{flag.ljust(width)} (default: {text})" for flag, text in rows)
