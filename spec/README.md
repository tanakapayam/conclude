# Conformance fixtures

Language-neutral test data for [the conclude concept](../docs/concept.md).
Every file is plain JSON: inputs and expected outputs, with no code in it,
so any implementation -- the Python package in this repository, a
TypeScript one, anything else -- can run the same cases and be held to the
same behavior. **Spec version 1.**

The Python implementation runs them in
[`python/test/test_spec.py`](../python/test/test_spec.py), which is also the best
example of an adapter: a small function per fixture file that turns each
case into a call on the implementation and compares the result.

## Who runs them

| Implementation | Harness |
| --- | --- |
| Python (the reference implementation) | [`python/test/test_spec.py`](../python/test/test_spec.py) |
| TypeScript / Node.js | [`node/test/spec.test.ts`](../node/test/spec.test.ts) |

Each harness also checks that it runs every `*.json` file here, so a new
fixture cannot be added without both learning about it.

## Format

Each file is `{"spec_version": 1, "description": "...", "cases": [...]}`,
and every case has a unique `name`. A case that must fail carries
`"error": true` instead of an expected value; an expected `null` means
"unset".

A *setting* is `{"key": "port", "type": "int", "default": 8080}` -- `type`
is one of `bool`, `int`, `float`, `str`, `list`, and a `null` default means
the setting starts out unset. Settings are given as arrays so their order
is unambiguous. Declaring the type explicitly (rather than inferring it
from the default) keeps the fixtures usable from a language where `3` and
`3.0` are the same number.

| File | What it pins down | Case fields |
| --- | --- | --- |
| `naming.json` | env var, CLI flag and config key for a setting | `app`, `key`; `env_var`, `cli_flag`, `config_key` |
| `casters.json` | casting a raw value to a declared type | `type`, `input`; `output` or `error` |
| `dotenv.json` | the `.env` dialect | `text` (the file, UTF-8); `expect` |
| `merge.json` | layering and precedence | `settings`, `layers` (`config`, `env`, `developer`, `cli`); `expect` or `error` |
| `config_layers.json` | merging system, user, project and sibling config files | `settings`, `table_path`, `files`, optional `aux_pattern`; `expect` or `error` |
| `config_tables.json` | choosing which TOML table to read | `op` (`parse` or `resolve`), inputs; `expect` or `error` |
| `templates.json` | generated env, TOML and CLI templates | `app`, `settings`, optional `options`; `expect` (`env`, `toml`, `cli`) |
| `gitignore.json` | whether gitignore rules match a path | `files`, `paths` (`path`, `ignored`) |
| `guard.json` | the gitignore guard for a private file | `files`, `target`, optional `kill_switch_var` and `env`; `expect` (`active`, `reason`) |
| `invocation.json` | reproducing a resolved configuration as a command line | `settings`, `resolved`, optional `options` (`prog`, `always_include`, `skip`, `compare_defaults`); `expect` (the command line) |
| `sources.json` | the report of which sources are in play | `app`, `options` (the sources configured), `files`, optional `env`; `expect` (the whole report) |

The top-level fields of each file, and the meaning of every option, are in
its `description`.

## Rules for the fixtures

- **Expected values are written by hand from the intended behavior**, not
  recorded from an implementation, so the fixtures can disagree with one --
  that is their job. The exception is `gitignore.json`, where every
  verdict comes from `git check-ignore --no-index` (with no global or
  system git configuration); the Python suite re-checks them against a
  real `git` whenever one is installed.
- **Only intended behavior is pinned down.** Where implementations may
  reasonably differ (numbers beyond 2^53, `inf`, underscores in numerals,
  exotic Unicode line breaks, exponent formatting, ...) there is
  deliberately no case; the concept document lists them under
  "Implementation-defined".
- **Reason strings are part of the spec** (`guard.json`): they are what a
  person sees when a private file is not being used.
- **Adding or changing a case is a spec change.** Say so in the concept
  document; bump the spec version only for a change that a conforming
  implementation must react to.
