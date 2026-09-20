# conclude

A setting that can come from a flag, an environment variable, or a
config file usually gets written down three times: an argparse flag, an
environment variable, and a config-file key -- each with its own name,
its own type conversion, and its own copy of the default. Add a setting
and you touch three places; rename one and the other two quietly drift.

conclude has you write it once. Set up your defaults; conclude works
out the rest. You write down a setting's name, its type, and its
starting value -- as an entry in a plain dict -- and conclude infers
the environment variable name, the config-file key, the CLI flag, and
how to cast a raw value from any of those into the right type.

```python
import conclude

DEFAULTS = {
    "host": "localhost",
    "port": 8080,
    "debug": False,
    "tags": conclude.opt(list),  # unset by default, but still a list when set
}
app = conclude.App("myapp", DEFAULTS)

parser = app.build_arg_parser(prog="myapp")
namespace = parser.parse_args()
cli = {k: v for k, v in vars(namespace).items() if v is not None}
print(app.resolve(cli))
```

```
$ MYAPP_PORT=9000 myapp --debug --tags a,b
{'host': 'localhost', 'port': 9000, 'debug': True, 'tags': ['a', 'b']}
```

That one dict gave you the CLI flags (`--host`, `--port`, `--debug`,
`--tags`), the environment variables (`MYAPP_HOST`, `MYAPP_PORT`, ...),
the config-file keys (a `[myapp]` table in `~/.config/myapp/config.toml`
or `./.config.toml`), and a caster for each -- with no second list of
names to keep in sync.

## Where it fits

Configuration libraries tend to start from different things. conclude
starts from a dict of defaults and derives the rest:

| Package           | Primary abstraction                                                      | Reach for it when...                                                              |
| ----------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `argparse`        | CLI parser                                                               | you only need flags                                                               |
| ConfigArgParse    | argparse plus config files and environment variables                     | you have an argparse CLI and want files and env vars added                        |
| jsonargparse      | CLI and config built from type hints                                     | your program is functions, classes or dataclasses with type hints                 |
| python-dotenv     | `.env` loader                                                            | you just need a `.env` in `os.environ`                                            |
| python-decouple   | individual value reader (env, then file, then default)                   | you read a handful of values, Django-style                                        |
| pydantic-settings | typed, validated settings model                                          | you want validation, nested models or secret-manager sources                      |
| Dynaconf          | general-purpose layered configuration system                             | you want named environments, many file formats, or Vault                          |
| Hydra / OmegaConf | hierarchical, composable configuration                                   | you compose config groups, run sweeps or manage experiments                       |
| **conclude**      | **defaults → inferred env / TOML / CLI interfaces → layered resolution** | **you want all three interfaces from one dict, and safe private local overrides** |

conclude deliberately does not do schema validation (values are cast,
not validated), secret-manager backends, YAML or JSON files, or named
environments; the table says where to look for those. For a dated,
feature-by-feature comparison, see
[How conclude compares](https://github.com/tanakapayam/conclude/blob/main/docs/comparison.md).

## Design principles

- **One source of truth.** The defaults dict. Flags, environment
  variable names, config keys, casters and the generated templates are
  all derived from it, so they can't drift apart.
- **Opt in to anything unusual.** The system file, `.env` and the
  developer file are off until you ask; the user and project files are
  one `None` from off.
- **Private files have to prove they're private.** The developer file
  (and `.env`, if you ask) is read only when git is ignoring it.
- **Quiet for ordinary situations, loud for broken setups.** A missing
  local file is normal and silent, and `describe_sources()` explains
  it; a malformed developer file or a missing `pathspec` raises.
- **Standard library only.** `pathspec`, for the gitignore check, is an
  optional extra.

## The layers

```
1. CLI flags
2. Developer config file (opt-in; private, gitignored, project-local,
   TOML or dotenv -- beats the environment)
3. Environment variables (with an opt-in `.env` file as a fallback)
4. Config file(s), in this order (each overrides the previous):
   a. /etc/<app>/config.toml            (system-wide; opt-in, off by default)
   b. ~/.config/<app>/config.toml       (user-global, overrides system)
   c. ./.config.toml                    (project-local, overrides user)
   d. ./.config.*.toml                  (sibling files, sorted by name)
5. Hardcoded defaults
```

Or, lowest priority to highest:

```
defaults < system < user < project < env < developer < CLI
```

Everything hangs off that one dict: the layers it feeds, and what
conclude infers from it so you never write any of it twice:

```
                ┌── CLI
defaults ───────┼── developer config (explicit opt-in, must be gitignored)
       │        ├── environment
       │        ├── .env (explicit opt-in)
       │        └── config files
       │
       └── inference
             ├── caster
             ├── formatter
             ├── CLI name
             └── environment name
```

(The layers are listed highest priority first; `defaults` sits beneath
all of them.) The user and project config files are on by default, and
each is one `None` away from off. The system file, `.env`, and the
developer file are off until you ask for them.

## Local files: which one?

Two of the layers are about your own machine, and each comes in two
formats:

| Format | Below the environment                     | Above the environment                      |
| ------ | ----------------------------------------- | ------------------------------------------ |
| TOML   | the system, user and project config files | the developer file, e.g. `.developer.toml` |
| dotenv | `.env`                                    | the developer file, e.g. `.env.local`      |

- **Non-secret local defaults you're happy to commit** -- use `.env`.
  A real `export` in the shell still beats it, so it can't override a
  deployment.
- **Private values that must win over stray shell exports** (a local
  `DATABASE_URL`, say) -- use the developer file. Make it TOML if only
  your app reads it (it gets `[table]`s, including per-recipient ones);
  make it dotenv, like `.env.local`, if docker compose, direnv or your
  IDE need the same values.
- **A private `.env` that stays below the environment** -- use `.env`
  with `dotenv_require_gitignored=True`.

The developer file's location lives in your committed `pyproject.toml`
(any name works; the name decides the format, and only `.toml` means
TOML):

```toml
[tool.conclude.developer]
config = ".developer.toml"  # or ".env.local"
```

```python
app = conclude.App(
    "myapp",
    DEFAULTS,
    pyproject_path=conclude.AUTO,  # the developer file
    dotenv_path=conclude.AUTO,  # .env
)
```

The developer file is always guarded, and `.env` is when you ask: the
file is used only if it exists, sits in a git working tree, and is
gitignored. Otherwise it is skipped quietly, and `describe_sources()`
says why. Details: [the `.env` file](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#6-local-development-a-env-file), [the developer file](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#8-a-private-developer-config-file).

## What's in it

- **Inference** of casters, formatters, CLI flags, env var names and
  config keys from the defaults alone; `opt(type)` for a setting that
  starts out unset ([guide, section 1](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#1-the-bare-minimum), [section 3](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#3-when-inference-isnt-quite-enough-casters-and-formatters)).
- **Config-file tables**, including a positional shorthand that picks a
  table per recipient/deck/profile ([section 4](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#4-a-positional-shorthand--per-recipient-config-tables)).
- **`--print-invocation`** and `App.format_invocation()`: print the
  command line that reproduces a resolved configuration
  ([section 5](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#5-debugging-and-documentation---print-invocation)).
- **A `.env` fallback**, optionally required to be gitignored, sitting
  beneath real environment variables ([section 6](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#6-local-development-a-env-file)).
- **A system-wide config file**, the lowest-priority file ([section 7](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#7-machine-wide-defaults-a-system-config-file)).
- **A private developer file**, TOML or dotenv, that beats ambient
  environment variables ([section 8](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#8-a-private-developer-config-file)).
- **`describe_sources()`** for `--help`: which sources are in play, and
  why a given one isn't ([section 9](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#9-turning-off-a-source-and-telling-the-user)).
- **Templates and docs generated from your defaults**:
  `format_env()`, `format_toml()`, `format_cli()`
  ([section 10](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md#10-generating-docs-and-templates)).
- Standard library only, fully typed (`py.typed`), Python 3.11+. The
  gitignore check (developer file, strict `.env`) uses the optional
  `pathspec` package.

## Install

```
pip install conclude
```

The developer config layer (and a `.env` you ask to be held to the same
standard) needs one small pure-Python dependency, only to check that a
private file is gitignored:

```
pip install 'conclude[gitignore]'
```

## Documentation

- [Guide](https://github.com/tanakapayam/conclude/blob/main/docs/guide.md) -- builds a small CLI, `remind`, one
  idea at a time.
- [Reference](https://github.com/tanakapayam/conclude/blob/main/docs/reference.md) -- every class, method, and
  module.
- [Changelog](https://github.com/tanakapayam/conclude/blob/main/CHANGELOG.md).

## Development

```
uv sync --locked  # fails if uv.lock is out of date; `uv lock` refreshes it
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv build && uvx twine check --strict dist/*
```

CI runs these same commands on Python 3.11 through 3.14.

## License

MIT -- see [LICENSE](https://github.com/tanakapayam/conclude/blob/main/LICENSE).
