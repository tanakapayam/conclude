# Changelog

All notable changes to this package are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the package adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-20

### Added

- `defineConfig`: declare settings once (`camelCase` keys; a boolean, string or
  string-array default, or `int()`, `float()`, `bool()`, `str()`, `list()`), and
  `resolve()` every layer -- defaults, system, user and project config files, a
  `.env` fallback, the environment, a private developer file named in
  `package.json`, and the CLI -- into one typed settings object. Also
  `describeSources()`, `developerStatus()`, `dotenvStatus()`, the template
  generators (`formatEnv()`, `formatToml()`, `formatCli()`), and `cliOptions()` /
  `parseArgs()` over `node:util`'s parser.
- The building blocks of the conclude concept -- names, casting, the `.env`
  dialect, layered resolution, config files and tables, the gitignore guard,
  and the environment, TOML and CLI templates -- passing every conformance
  fixture of spec version 1.
