# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-09-26

### Fixed

- Python tree is now under `python/` to match `node/` tree.

## [1.0.1] - 2026-09-20

### Fixed

- `.env` files, and dotenv-format developer files, are now read as UTF-8 on
  every platform, and a leading byte-order mark is ignored. Previously the
  platform's default text encoding was used, which garbled non-ASCII values
  on Windows, and a byte-order mark (which some Windows editors add) made
  the first variable silently disappear.

### Changed

- The package's OS classifier is now `Operating System :: Unix` rather than
  `OS Independent`: the tests run on Linux, and the paths conclude uses
  (`~/.config`, `/etc`) are Unix conventions.
- The source distribution no longer includes `uv.lock` or `.github/`.

## [1.0.0] - 2026-09-20

First public release.

### Added

- **Inference from one dict.** `App(name, defaults)` infers each setting's
  environment variable, config-file key, CLI flag, caster and formatter
  from its name, type and default. `opt(type)` declares a typed setting
  that starts out unset.
- **Layered resolution:** `defaults < system < user < project < env <
  developer < CLI`, with per-key casting at every layer.
- **Config files:** user (`~/.config/<name>/config.toml`) and project
  (`./.config.toml`, plus `.config.*.toml` siblings, configurable or
  disabled with `config_cwd_aux_pattern`) files; an opt-in system-wide
  `/etc/<name>/config.toml`; two-level `[PARENT]` / `[PARENT.CHILD]`
  tables; a positional shorthand that picks a table.
- **`.env` fallback** beneath real environment variables (opt-in).
  `dotenv_require_gitignored=True` holds it to the developer file's
  gitignore guard, and `App.dotenv_status()` reports its state.
- **Developer config layer** (opt-in via `pyproject_path`): a private,
  gitignored, project-local file named by `pyproject.toml`'s
  `tool.conclude.developer.config` that beats ambient environment
  variables and loses to the CLI. The file is TOML if its name ends in
  `.toml` and dotenv otherwise (say `.env.local`, keyed by the app's
  environment variable names, so it can be shared with docker compose or
  direnv). It is applied only when the file exists, sits in a git working
  tree, and is covered by its ignore rules, checked with the optional
  `pathspec` extra: `pip install 'conclude[gitignore]'`.
  `<NAME>_DEVELOPER_CONFIG=off` is a kill switch, and
  `App.developer_status()` reports the layer's state and reason as data.
- **`describe_sources()`** for `--help`, listing every source and, for the
  developer layer and a strict `.env`, whether it is active and why not.
- **Generated templates and docs:** `format_env()`, `format_toml()` and
  `format_cli()` render every setting next to its default.
- **`--print-invocation`** and `format_invocation()`: reproduce a resolved
  configuration as a command line.
- Standard library only; fully typed (`py.typed`); Python 3.11 and newer.
