# Reference

Every public name in `conclude`. For a walkthrough that builds a small
CLI one idea at a time, see the [guide](guide.md); docstrings carry the
full detail for each function.

conclude is deliberately function-first: almost everything is a plain
function taking plain dicts and paths in and returning a plain dict
out. `App` bundles those functions around one app's `name` and
`defaults` so most code never calls them directly.

## `App`

`conclude.App` is a frozen dataclass: a *spec*, not a session. Construct
one, call its methods as often as you like, nothing on it ever mutates.
(The one exception is `__post_init__`, which replaces any path field
still holding the `AUTO` sentinel with its real value exactly once, at
construction.)

### Fields

| Field                    | Default                      | Meaning                                                                                                        |
| ------------------------ | ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `name`                   | required                     | The app's name: prefix of its env vars, default config table, and default file locations.                        |
| `defaults`               | required                     | `{key: default}` -- the one dict everything is inferred from. Use `opt(type)` for a typed, unset-by-default setting. |
| `casters`                | `None`                       | Per-key overrides of the inferred caster.                                                                      |
| `formatters`             | `None`                       | Per-key overrides of the inferred formatter (also used by the `format_*` templates).                           |
| `env_vars`               | `None`                       | Per-key overrides of the inferred environment variable name.                                                   |
| `dotenv_path`            | `None` (off)                 | `AUTO` for `./.env`, or a `Path`. The `.env` fallback beneath real environment variables.                      |
| `dotenv_require_gitignored` | `False`                   | Read the `.env` fallback only if it is gitignored (the developer file's guard). Needs the `gitignore` extra. |
| `config_home_path`       | `AUTO` -> `~/.config/<name>/config.toml` | The user-global config file. `None` disables it.                                                     |
| `config_cwd_path`        | `./.config.toml`             | The project-local config file. `None` disables it *and* the sibling search.                                    |
| `config_cwd_aux_pattern` | `".config.*.toml"`           | Sibling files merged after the project file, sorted by name. `None` keeps the project file but drops the siblings. |
| `config_system_path`     | `None` (off)                 | `AUTO` for `/etc/<name>/config.toml`, or a `Path`. The lowest-priority config file.                            |
| `pyproject_path`         | `None` (off)                 | `AUTO` for `./pyproject.toml`, or a `Path`. Opts in to the developer config layer ([section 8](guide.md#8-a-private-developer-config-file)).                    |
| `default_table`          | `None` -> `name`             | The TOML table config files are read from.                                                                     |

### Resolved properties

Computed from the fields above, never stored: `resolved_defaults`,
`resolved_casters`, `resolved_formatters`, `resolved_env_vars`,
`resolved_config_system_path`, `resolved_config_home_path`,
`resolved_config_cwd_path`, `resolved_dotenv_path`,
`resolved_pyproject_path`, `resolved_default_table`.

### Methods

| Group             | Method                            | Purpose                                                                                         |
| ----------------- | --------------------------------- | ----------------------------------------------------------------------------------------------- |
| Build a CLI       | `add_arguments(parser)`           | Add one inferred flag per setting to an existing `ArgumentParser` (`skip=`/`overrides=`).       |
|                   | `build_arg_parser()`              | A fresh parser with those flags already added.                                                  |
|                   | `add_print_invocation_argument()` | Add the conventional `--print-invocation` flag ([section 5](guide.md#5-debugging-and-documentation---print-invocation)).                                        |
| Read a layer      | `load_env()`                      | The environment layer (and the `.env` fallback, if opted in).                                   |
|                   | `load_config_files()`             | The config-file layers, merged: system, user, project, siblings.                                |
|                   | `load_developer_config()`         | The developer layer (a `.toml` table, or a dotenv file keyed by env var names) -- `{}` unless it is active ([section 8](guide.md#8-a-private-developer-config-file)).                                      |
|                   | `resolve_config_table()`          | Which table to read: `--config`, or a positional shorthand ([section 4](guide.md#4-a-positional-shorthand--per-recipient-config-tables)).                            |
| Do the work       | `resolve(cli, ...)`               | Merge every layer, casting as it goes: `defaults < system < user < project < env < developer < CLI`. |
|                   | `format_invocation(resolved)`     | The inverse: the command line that reproduces a resolved dict.                                  |
| Write templates   | `format_env()`                    | An environment-variable template with the defaults filled in ([section 10](guide.md#10-generating-docs-and-templates)).                         |
|                   | `format_toml()`                   | A config-file template.                                                                         |
|                   | `format_cli()`                    | A CLI reference, one aligned line per flag.                                                     |
| Explain itself    | `describe_sources()`              | Which sources are in play, for `--help` ([section 9](guide.md#9-turning-off-a-source-and-telling-the-user)).                                               |
|                   | `developer_status()`              | The developer layer's state and reason, as data. Never raises.                                  |
|                   | `dotenv_status()`                 | The `.env` fallback's state and reason, as data. Never raises.                                  |

## Other classes

- **`Opt`**, built by `opt(type_)` -- a typed placeholder for a setting
  that starts out `None`. One field (`type`); it exists so `opt(str)`
  can *be* `None` at runtime while still telling inference what type a
  real value should become.
- **`AUTO`** -- a sentinel (the one instance of a private class) meaning
  "compute the conventional default for this path", distinct from both
  an unset field and an explicit `None`.
- **`ConfigFileError`** (subclasses `ValueError`) -- a config file exists
  but isn't valid TOML. For the developer file the message starts with
  `developer config file`.
- **`DotenvState`** (enum: `DISABLED`, `ACTIVE`, `INACTIVE`) and
  **`DotenvStatus`** (frozen dataclass: `state`, `path`, `reason`,
  `guarded`, `setup_error`, plus `active`) -- where the `.env` fallback
  stands; returned by `App.dotenv_status()`. `setup_error` is `True`
  only when a requested gitignore guard needed `pathspec` and it is
  missing; `load_env` then raises `ImportError`.
- **`DeveloperState`** (enum: `NOT_OPTED_IN`, `NOT_CONFIGURED`,
  `INACTIVE`, `ACTIVE`) and **`DeveloperStatus`** (frozen dataclass:
  `state`, `path`, `reason`, `setup_error`, plus `active` and `format`, which is `"toml"` for a `.toml` name and `"dotenv"` for any other) -- where the
  developer layer stands ([section 8](guide.md#8-a-private-developer-config-file)). `setup_error` is `True` only when
  `pathspec` is missing but needed; `load_developer_config` then raises
  `ImportError` instead of skipping the file.
- **`Caster`** and **`Formatter`** -- type aliases for
  `Callable[[Any], Any]` and `Callable[[Any], str | None]`, naming the
  shape of a per-key override.

## Functions, by module

**`conclude.naming`** -- each layer's conventional name for a setting.

| Function                     | Purpose                                                     |
| ---------------------------- | ----------------------------------------------------------- |
| `cli_flag_name(key)`         | `"filter_col"` -> `"--filter-col"`.                         |
| `env_var_name(app_name, key)` | `("remind", "retries")` -> `"REMIND_RETRIES"`.             |
| `config_key_name(key)`       | The config-file key -- just `key` itself.                   |

**`conclude.infer`** -- casters from types.

| Function                         | Purpose                                                                 |
| -------------------------------- | ----------------------------------------------------------------------- |
| `opt(type_)`                     | The default for an optional, typed setting.                             |
| `effective_defaults(defaults)`   | `defaults` with every `Opt` unwrapped to the `None` it stands for.      |
| `infer_caster(type_)`            | The caster for a bare type (`bool`/`int`/`float`/`str`/`list`).         |
| `infer_casters(defaults, overrides)` | A caster for every key, with your overrides applied.                |

**`conclude.formatters`** -- the inverse of the casters, for rendering values as CLI tokens.

| Function                             | Purpose                                                |
| ------------------------------------ | ------------------------------------------------------ |
| `infer_formatter(type_)`             | The formatter for a bare type.                         |
| `infer_formatters(defaults, overrides)` | A formatter for every key, with your overrides applied. |
| `format_bool(value)`                 | `True` -> the bare flag; `False` -> not rendered.      |
| `format_list(value)`                 | Shell-quoted, comma-joined.                            |
| `format_scalar(value)`               | Shell-quoted `str(value)`.                             |

**`conclude.casters`** -- reusable casters (inference picks from these; they also work written out by hand).

| Function                     | Purpose                                                                     |
| ---------------------------- | --------------------------------------------------------------------------- |
| `cast_bool(value)`           | Truthy/falsy strings, numbers, bools -> `bool`.                             |
| `cast_int_or_none(value)`    | A whole or fractional number, or `None`.                                    |
| `cast_positive_int(value)`   | A whole number >= 1, or `None`.                                             |
| `cast_float_or_none(value)`  | A float, or `None`.                                                         |
| `cast_str_or_none(value)`    | A string; `None`/`""` mean "not provided".                                  |
| `cast_escaped_str(value)`    | Like `cast_str_or_none`, but `""` is a real value, and `\n`/`\t` are decoded. |
| `cast_comma_list(value)`     | `"a,b"` (or a TOML array) -> `list[str]`, or `None`.                        |
| `decode_backslash_escapes(text)` | Decode just `\n \t \r \\ \"`, leaving everything else untouched.    |

**`conclude.env`** -- the environment layer.

| Function                              | Purpose                                                    |
| ------------------------------------- | ---------------------------------------------------------- |
| `load_env(env_vars, environ, dotenv_path=, require_gitignored=)` | Read the environment (and an opt-in `.env` beneath it, optionally required to be gitignored). |
| `dotenv_status(dotenv_path, require_gitignored=)` | The `.env` fallback's `DotenvStatus`. Never raises.        |
| `load_dotenv(path)`                   | Parse a `.env` file into `{NAME: value}`.                 |

**`conclude.files`** -- the config-file layers.

| Function                                     | Purpose                                                              |
| -------------------------------------------- | -------------------------------------------------------------------- |
| `load_raw_toml(path)`                        | A file's raw TOML, or `{}` if disabled/missing.                     |
| `load_config_file(path, defaults, table_path)` | One file's settings from the selected table(s).                    |
| `load_config_files(home, cwd, defaults, table_path, aux_pattern, system_path=)` | Every config file merged, lowest priority first. |
| `cwd_aux_config_paths(cwd_path, pattern)`    | The sibling files next to the project file, sorted by name.          |
| `parse_config_table(value, default_table)`   | `"A"`/`"A.B"` -> `["A"]`/`["A", "B"]`.                               |
| `resolve_config_table(...)`                  | Which table to read: `--config`, or a positional shorthand.          |
| `table_exists(raw, table_path)`              | Whether a parsed file has that table.                                |

**`conclude.merge`**

| Function                                        | Purpose                                                                 |
| ----------------------------------------------- | ----------------------------------------------------------------------- |
| `resolve(cli, env, config_file, defaults, casters, developer=)` | Merge `defaults < config_file < env < developer < cli`, casting each value. |

**`conclude.developer`** -- the developer config layer ([section 8](guide.md#8-a-private-developer-config-file)).

| Name                                   | Purpose                                                              |
| -------------------------------------- | -------------------------------------------------------------------- |
| `developer_status(pyproject_path, kill_switch_var=, environ=)` | The layer's `DeveloperStatus`. Never raises.        |
| `load_developer_config(status, defaults, table_path, env_vars=)` | The layer's settings -- a `.toml` file's table, or (any other name, dotenv) the variables named by `env_vars`; raises `ImportError`/`ConfigFileError` for the two setup errors. |

**`conclude.guard`** -- the gitignore guard shared by the developer file and a strict `.env`.

| Name                                             | Purpose                                                                            |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `check_guard(path, kill_switch_var=, environ=, escape_hint=)` | Whether `path` may be used -- not switched off, existing, in a git tree, ignored by it -- as a `GuardResult`. Never raises. |
| `GuardResult`                                    | `active`, `reason`, `setup_error` (`pathspec` missing).                            |
| `matches_git_ignore_rules(root, target)`                   | Whether the ignore rules match `target` -- pure Python, never runs `git` (needs `pathspec`). |

**`conclude.paths`**

| Function                               | Purpose                                         |
| -------------------------------------- | ----------------------------------------------- |
| `default_config_home_path(app_name)`   | `~/.config/<app_name>/config.toml`.             |
| `default_config_system_path(app_name)` | `/etc/<app_name>/config.toml`.                  |

**`conclude.tomlwrite`** -- TOML-escaping helpers, for a "print me a config entry" feature.

| Function          | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `toml_key(s)`     | A TOML key: bare if valid, quoted otherwise.                   |
| `toml_string(s)`  | `s` as a double-quoted TOML basic string, correctly escaped.   |

**`conclude.templates`** -- the value renderers behind `format_env`/`format_toml`/`format_cli`: `plain_text`, `env_value`, `toml_value`.

## Thin wrappers

Seven of `App`'s methods (`load_env`, `load_config_files`,
`load_developer_config`, `developer_status`, `dotenv_status`,
`resolve_config_table`, `resolve`) are thin wrappers around the module-level functions above
with the app's own fields filled in -- so you can call the function
yourself, with your own dicts and paths, and no `App`. The rest
(`add_arguments`, `build_arg_parser`, `add_print_invocation_argument`,
`format_invocation`, `format_env`, `format_toml`, `format_cli`,
`describe_sources`) need everything `App` bundles at once, and have no
standalone equivalent.

## Requirements

Python 3.11+, standard library only. The optional `gitignore` extra
(`pip install 'conclude[gitignore]'`) adds `pathspec`, used solely to
check that a private file -- the developer config file, or a `.env`
held to `dotenv_require_gitignored` -- is gitignored. The package ships
`py.typed`.
