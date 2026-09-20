# How conclude compares

A feature-by-feature comparison with five libraries people often reach
for instead. **Verified 2026-09-19** against each project's
documentation and its PyPI metadata; the versions checked are
conclude 1.0.0, ConfigArgParse 1.7.7, jsonargparse 4.52.0,
pydantic-settings 2.15.0, Dynaconf 3.3.5 and python-decouple 3.8.

A dash (--) means no built-in support that the project's documentation
mentions. These libraries move quickly, so if a cell is wrong or has
gone stale, please open an issue. For where each one *starts from*, see
[Where it fits](https://github.com/tanakapayam/conclude#where-it-fits) in
the README; this page is the detail.

## What you write

| conclude          | ConfigArgParse         | jsonargparse                              | pydantic-settings    | Dynaconf                                | python-decouple         |
| ----------------- | ---------------------- | ----------------------------------------- | -------------------- | --------------------------------------- | ----------------------- |
| a dict of defaults | an `add()` call per option | type hints on functions, classes, dataclasses | a pydantic model class | settings files, plus optional validators | a `config()` call per value |

## Capabilities

| Capability                                            | conclude                          | ConfigArgParse                          | jsonargparse                      | pydantic-settings                        | Dynaconf                                  | python-decouple                  |
| ----------------------------------------------------- | --------------------------------- | --------------------------------------- | --------------------------------- | ---------------------------------------- | ----------------------------------------- | -------------------------------- |
| Environment variables                                 | yes                               | yes                                     | yes                               | yes                                      | yes                                       | yes                              |
| Your program's CLI flags                              | yes                               | yes                                     | yes                               | yes (opt in)                             | -- (its CLI manages settings files)       | --                               |
| TOML files                                            | yes                               | yes (`toml` extra)                      | yes (`toml` extra)                | yes (`toml` extra)                       | yes                                       | --                               |
| YAML, JSON or INI files                               | --                                | yes (YAML, INI)                         | yes (YAML, JSON)                  | yes (YAML, JSON)                         | yes (YAML, JSON, INI)                     | yes (INI)                        |
| `.env` files                                          | yes                               | --                                      | --                                | yes                                      | yes                                       | yes                              |
| Sources layered, precedence documented                | yes                               | yes                                     | yes                               | yes (reorderable)                        | yes                                       | yes (env, then file, then default) |
| Where the config files live                           | system, user and project built in | you list the paths                      | you list the paths                | you list the paths                       | you list the paths                        | searched up from your module     |
| Names inferred from the declaration                   | flags, env vars and config keys   | config keys                             | flags and config keys; env vars with `default_env` | env vars, flags and TOML keys, from field names | --                                | --                               |
| Config templates or reference generated from it       | env, TOML and CLI templates       | `-h` lists env vars and config keys     | `--print_config` (YAML)           | -- (a model can export JSON Schema)      | `dynaconf init` scaffolds files           | --                               |
| Local file above the environment, built in            | yes                               | --                                      | --                                | possible by reordering sources           | --                                        | --                               |
| Verifies a private file is gitignored before reading  | yes                               | --                                      | --                                | --                                       | -- (`init` adds `.secrets.*` to `.gitignore`; no load-time check documented) | --          |
| Schema validation of values                           | -- (casting only)                 | -- (argparse `type=`, `choices`)        | yes (type hints)                  | yes                                      | yes (validators)                          | -- (casting only)                |
| External secret backends                              | --                                | --                                      | --                                | yes (AWS, Azure, GCP)                    | yes (Vault, Redis)                        | --                               |
| Named environments (development, production, ...)    | --                                | --                                      | --                                | --                                       | yes                                       | --                               |
| Hard runtime dependencies (PyPI metadata)             | 0                                 | 0                                       | 1 (PyYAML)                        | 3                                        | 0                                         | 0                                |

## Reading the table

- **Layering is table stakes.** Every library here layers its sources
  with a documented order, and "zero dependencies" is shared by most of
  them. Neither is what sets conclude apart.
- **What conclude is for:** one dict of defaults that yields the
  environment, TOML and CLI interfaces together, generated
  templates for each, built-in system/user/project locations, and a
  private local file that beats ambient environment variables *and is
  verified to be gitignored before it is read*
  ([guide](guide.md#8-a-private-developer-config-file)).
- **What conclude gives up:** schema validation, secret-manager
  backends, YAML and JSON files, and named environments. If those
  matter more, pydantic-settings and Dynaconf are the better fit.
- **Provenance is a different feature.** ConfigArgParse can report where
  each value came from (`format_values()`); conclude's
  `describe_sources()` reports which *sources* are in play and their
  state, not the origin of each value.
- **Hydra and OmegaConf** solve a different problem -- composing large
  hierarchical configurations, sweeps and experiments -- so they are
  not compared row by row.

## Sources

- ConfigArgParse: <https://github.com/bw2/ConfigArgParse>
- jsonargparse: <https://jsonargparse.readthedocs.io/>
- pydantic-settings: <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>
- Dynaconf: <https://www.dynaconf.com/>
- python-decouple: <https://github.com/HBNetwork/python-decouple>
- Versions and dependencies: each project's PyPI metadata,
  `https://pypi.org/pypi/<name>/json`
