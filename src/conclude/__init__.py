"""conclude: layered CLI-flag / env-var / config-file / default config
resolution, with no opinion about what your settings actually are.

The name: you write down your settings' *defaults* -- their names,
their types, their starting values -- and conclude works out
everything else (env var names, config file keys, CLI flag names, and
how to cast a raw value from any layer into the right type) from that
one dict. You supply the premises; conclude draws the conclusion.

This package is the arg-env-config-default *mechanism* extracted out of
an application's config module: given a dict of hardcoded defaults, a
dict of casters (one per setting, so every layer normalizes the same
way before merging), and the already-loaded CLI/env/config-file layers,
``resolve()`` merges them lowest-priority-first into one plain dict.
Everything else here exists to *produce* those layers:

- :class:`conclude.App` -- the convenience layer: give it your app's
  name and its defaults dict, and it infers env var names, casters,
  and (via ``add_arguments``/``build_arg_parser``) CLI flag names, all
  from that one dict. This is the one most applications want; the
  rest of this list is what it's built from, for anyone who wants the
  pieces separately. It also has ``format_invocation()``, the inverse
  direction: given a resolved settings dict, render the standalone
  command line that reproduces it -- handy for debugging a confusing
  resolved setup, or documenting one. Its ``format_env()``/
  ``format_toml()``/``format_cli()`` render every setting's name in
  that layer next to its default -- a ready-to-paste ``.env``/config-file
  template or CLI reference, generated from the same ``defaults``. Any of
  its three file-based
  sources (``dotenv_path``/``config_home_path``/``config_cwd_path``)
  can be set to ``None`` to disable that source outright (plus an
  opt-in, lowest-priority system-wide file, ``config_system_path=AUTO``
  for ``/etc/<name>/config.toml``, and an opt-in developer file above
  the environment, ``pyproject_path=AUTO``; the project file's
  ``.config.*.toml`` siblings have their own ``config_cwd_aux_pattern``
  knob), and
  ``describe_sources()`` renders which ones are active/disabled --
  meant for your program's own ``--help`` text, since that's a fact
  about the program, not about any one run's resolved values.
- :mod:`conclude.templates` -- the value-rendering helpers behind
  ``App.format_env()``/``format_toml()``/``format_cli()``.
- :mod:`conclude.guard` -- the gitignore guard shared by the developer
  file and (optionally) a ``.env`` file: exists, inside a git working
  tree, and ignored by it.
- :mod:`conclude.developer` -- the opt-in developer config layer
  (``defaults < ... < env < developer < CLI``): a private,
  gitignored, project-local file, named by ``pyproject.toml``'s
  ``tool.conclude.developer.config``, that beats ambient environment
  variables; ``DeveloperStatus`` says which of four states it is in.
- :func:`conclude.opt` -- the default to write for an optional
  setting (one that starts out ``None``) so caster/formatter inference
  still knows its real type, e.g. ``opt(str)``.
- :mod:`conclude.naming` -- ``cli_flag_name()``/``env_var_name()``/
  ``config_key_name()``, deriving each layer's conventional name for a
  setting from its Python key alone.
- :mod:`conclude.infer` -- ``infer_caster()``/``infer_casters()``,
  picking a caster from a default's type (or an ``opt()``-wrapped
  type), and ``effective_defaults()`` to unwrap ``opt()`` placeholders.
  ``conclude.Caster`` names the shape a caster/override is expected to
  have: ``Callable[[Any], Any]``.
- :mod:`conclude.formatters` -- ``infer_formatter()``/
  ``infer_formatters()``, the inverse of :mod:`conclude.infer`: picking
  the CLI-token rendering for a resolved value from its type, for
  ``App.format_invocation()``. ``conclude.Formatter`` names that shape:
  ``Callable[[Any], str | None]``.
- :mod:`conclude.casters` -- the small, reusable value casters
  (bool, int-or-None, float-or-None, positive int, str-or-None,
  comma-separated list, backslash-escaped string) that inference picks
  from, and that also work fine written out by hand for a setting that
  needs an explicit override. ``decode_backslash_escapes()`` is the
  narrow ``\n``/``\t``/``\r``/``\\``/``\"`` decoder
  ``cast_escaped_str`` (and ``.env`` double-quoted values) use under
  the hood -- non-ASCII text always passes through unchanged.
- :mod:`conclude.env` -- ``load_env()`` reads a dict of
  ``{setting_name: ENV_VAR_NAME}`` out of the environment, optionally
  falling back to a ``.env`` file (``load_dotenv()``) for anything not
  actually set there.
- :mod:`conclude.files` -- TOML config file loading, with support for
  a two-level ``[PARENT]``/``[PARENT.CHILD]`` table selection, a
  project-local file that overrides a user-global one, sibling
  "auxiliary" files picked up automatically, and resolving which
  table a bare positional shorthand argument (a "deck" name, a
  "profile" name, whatever your app calls it) maps to by peeking at
  the config files themselves.
- :mod:`conclude.tomlwrite` -- ``toml_string()``/``toml_key()`` for
  generating ready-to-paste TOML snippets (e.g. for a
  "print me a config entry for what I just set up" flag).
- :mod:`conclude.paths` -- the conventional
  ``~/.config/<app_name>/config.toml`` user path and
  ``/etc/<app_name>/config.toml`` system path for a given app name.
- :func:`conclude.resolve` -- the merge itself, for anyone assembling
  the CLI/env/config-file layers by hand instead of through ``App``.

What stays in your own application: your defaults dict (that's the
whole point), and anything inference genuinely can't guess for a
particular setting -- a caster with its own error-message wording, a
hand-written ``--help`` string, or CLI/config behavior beyond "one
flag per setting" (a positional shorthand argument, say). Each of
those is a small, targeted override; you don't lose inference for
every other setting to get one.
"""

from conclude.app import AUTO, App
from conclude.casters import (
    cast_bool,
    cast_comma_list,
    cast_escaped_str,
    cast_float_or_none,
    cast_int_or_none,
    cast_positive_int,
    cast_str_or_none,
    decode_backslash_escapes,
)
from conclude.developer import DeveloperState, DeveloperStatus, developer_status
from conclude.env import DotenvState, DotenvStatus, dotenv_status, load_dotenv, load_env
from conclude.files import (
    ConfigFileError,
    cwd_aux_config_paths,
    load_config_file,
    load_config_files,
    load_raw_toml,
    parse_config_table,
    resolve_config_table,
    table_exists,
)
from conclude.formatters import (
    Formatter,
    format_bool,
    format_list,
    format_scalar,
    infer_formatter,
    infer_formatters,
)
from conclude.infer import Caster, Opt, effective_defaults, infer_caster, infer_casters, opt
from conclude.merge import resolve
from conclude.naming import cli_flag_name, config_key_name, env_var_name
from conclude.paths import default_config_home_path, default_config_system_path
from conclude.tomlwrite import toml_key, toml_string

__version__ = "1.0.1"

__all__ = [
    "App",
    "AUTO",
    "Opt",
    "opt",
    "Caster",
    "Formatter",
    "effective_defaults",
    "infer_caster",
    "infer_casters",
    "format_bool",
    "format_list",
    "format_scalar",
    "infer_formatter",
    "infer_formatters",
    "cli_flag_name",
    "config_key_name",
    "env_var_name",
    "cast_bool",
    "cast_comma_list",
    "cast_escaped_str",
    "cast_float_or_none",
    "cast_int_or_none",
    "cast_positive_int",
    "cast_str_or_none",
    "decode_backslash_escapes",
    "DotenvState",
    "DotenvStatus",
    "dotenv_status",
    "DeveloperState",
    "DeveloperStatus",
    "developer_status",
    "load_env",
    "load_dotenv",
    "ConfigFileError",
    "cwd_aux_config_paths",
    "load_config_file",
    "load_config_files",
    "load_raw_toml",
    "parse_config_table",
    "resolve_config_table",
    "table_exists",
    "resolve",
    "default_config_home_path",
    "default_config_system_path",
    "toml_key",
    "toml_string",
]
