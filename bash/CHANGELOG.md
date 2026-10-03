# Changelog

All notable changes to this package are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the package adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-10-04

### Added

- **A negation for every boolean flag.** A `bool` setting gets `--no-flag` as
  well as `--flag`: `conclude_resolve` reads it as `false`, and the last one
  given wins. A key that already starts with `no_` is turned off by dropping it
  (`no_color`: `--no-color` on, `--color` off). New functions:
  `conclude_cli_negated_flag_name` and `conclude_parse_cli`, the CLI-layer
  parsing `conclude_resolve` now uses.
- Two settings that claim the same flag (`cache` and `no_cache`) are an error
  from `conclude_resolve`, `conclude_format_cli` and `conclude_format_invocation`.

### Changed

- `conclude_format_invocation` writes a bool that is off as its negation, so a
  bool whose default is true reproduces; `conclude_format_cli` shows the flag
  that changes a bool's default (`--no-flag` for true, `--flag | --no-flag` for
  none).
- A bool given a value (`--debug=false`) is still an error, but its message no
  longer says there is no way to turn a bool off.
- Conforms to spec version 2 (new `spec/cli.json`, run by `test/cli.bats`).

## [0.2.0] - 2026-10-02

### Added

- A personal control file, `$XDG_CONFIG_HOME/conclude/control.toml` (or
  `~/.config/conclude/control.toml`), letting a developer set their own
  `developer_file` for every bash-conclude app on their machine, under
  `[control]` or, more specifically, `[control.bash]`. By default it's only a
  fallback for an app with no `--developer-file` of its own; `override = true`
  makes it win outright, even over an app's explicit choice. It's never
  consulted unless the app has already opted into the developer layer
  (`--developer-file` or the new `--developer-opt-in`) -- a personal dotfile
  can't make a script that never asked for this start reading one.
  (`conclude_resolve_developer_file`)
- `conclude_resolve --developer-opt-in`: opt into the developer layer with no
  path of the app's own, leaving it entirely to the control file (or else
  `.developer.toml`).

### Fixed

- `conclude_resolve`'s default user-config path now respects
  `$XDG_CONFIG_HOME` (`$XDG_CONFIG_HOME/APP/config.toml`, falling back to
  `~/.config/APP/config.toml`), matching the Python package. It previously
  always used `~/.config/APP/config.toml` even when `$XDG_CONFIG_HOME` was set
  to somewhere else.

## [0.1.0] - 2026-09-30

### Added

- First release: `conclude.sh`, a single file you `source`, implementing the
  shared [spec](../spec/README.md) for Bash 5.3 or newer with no runtime
  dependency beyond Bash, coreutils, `awk` (fractional numbers only) and `git`
  (the developer/`.env` guard).
- Declaring settings (`conclude_init`, `conclude_define`) and resolving them
  through `defaults < user config < project config (+ siblings) < env <
  developer config < CLI` (`conclude_resolve`).
- The derived names (`conclude_cli_flag_name`, `conclude_env_var_name`,
  `conclude_config_key_name`), the casters (`conclude_cast`), the `.env`
  parser (`conclude_parse_dotenv`, `conclude_load_dotenv`), TOML config-table
  reading and layering, and the git guard (`conclude_check_guard`).
- Templates and reports: `conclude_format_env`, `conclude_format_toml`,
  `conclude_format_cli`, `conclude_format_invocation`,
  `conclude_describe_sources`, `conclude_dotenv_status`,
  `conclude_developer_status`.
- Passes every shared conformance fixture the other ports pass (`bash/test/`,
  run with `bats` and `jq`), plus integration tests for `conclude_resolve`.

### Known differences from the Python and Node packages

- The developer layer is opted into with `conclude_resolve --developer-file
  PATH`; there is no `pyproject.toml`/`package.json` manifest lookup.
- The system config file and the `.env` fallback are not wired into
  `conclude_resolve` (both are off by default in the other ports too).
- A list setting is one comma-separated string in, one item per line out.
- TOML arrays are not read from config files (any other TOML value shape is
  rejected as malformed rather than misread).
