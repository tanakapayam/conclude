# Reference (Node.js)

Everything is exported from `@tanakapayam/conclude` (an ESM package that
Node's `require()` can also load). For a walkthrough, see the [guide](guide.md);
for the behavior every implementation shares, [the concept](../concept.md).

## `defineConfig`

`defineConfig(options)` takes a `ConfigOptions`, declares the settings, and returns a `Config`. It
validates the declarations immediately (an invalid key, two keys that map to the
same name, a bare number) and throws a `TypeError`.

| Option | Default | Meaning |
| --- | --- | --- |
| `name` | required | The application name: the environment variable prefix, the default TOML table, and the default file locations. |
| `settings` | required | The declarations: each value is a default, or a `int()`/`float()`/`bool()`/`str()`/`list()` spec. |
| `envVars` | none | Environment variable names, by declared key, where the derived one is not wanted. |
| `defaultTable` | `name` | The TOML table config files are read from. |
| `userConfigPath` | `AUTO` | `~/.config/<name>/config.toml`. On by default; `null` turns it off. |
| `projectConfigPath` | `.config.toml` | The project-local file. On by default; `null` turns it off, and its siblings with it. |
| `projectAuxPattern` | `.config.*.toml` | Sibling files merged after the project file, sorted by name; `null` drops just those. |
| `systemConfigPath` | off | `AUTO` for `/etc/<name>/config.toml`, or a path. The lowest-priority file. |
| `dotenvPath` | off | `AUTO` for `./.env`, or a path. The `.env` fallback beneath the real environment. |
| `dotenvRequireGitignored` | `false` | Read `.env` only if it is gitignored (needs the optional `ignore` package). |
| `manifestPath` | off | `AUTO` for `./package.json`, or a path. Opts in to the developer layer. |

`AUTO` is a unique symbol meaning "use the conventional path"; it is distinct
from leaving an option out and from `null`. A `PathOption` is a path string,
`AUTO`, or `null`.

## Declaring settings

| Name | Purpose |
| --- | --- |
| `bool(default?)` | A flag. |
| `int(default?)` | A number that is an integer when whole (a fraction is accepted). |
| `float(default?)` | A number; a whole default is written `3.0` in templates. |
| `str(default?)` | Text. |
| `list(default?)` | A list of text items. |

With no argument a helper declares a setting of that type that starts out unset,
and its resolved type includes `null`. A `boolean`, `string` or `string[]` is
shorthand for `bool()`, `str()` and `list()`; a bare number is not allowed.

The types describe the result: `Spec<T>` is what a helper returns, `Declared` is
what one setting may be, `Declarations` is the whole `settings` object, `ValueOf`
is the value one declaration resolves to, and `Resolved` maps a `Declarations`
type to the resolved settings. `toCanonicalKey("filterCol")` is `"filter_col"`,
the `snake_case` form used in config files, the environment and flags.

## `Config`

| Member | Purpose |
| --- | --- |
| `name` | The application name. |
| `envVarNames` | The environment variable each setting reads, by declared key. |
| `resolve(options?)` | Merge every layer -- `defaults < system < user < project < env < developer < CLI` -- into one typed object. |
| `developerStatus(environ?)` | Where the developer layer stands, and why. Never throws. |
| `dotenvStatus()` | Where the `.env` fallback stands, and why. Never throws. |
| `describeSources(environ?)` | Which sources are in play, lowest priority first, for `--help`. |
| `formatEnv(options?)` | An environment-variable template with the defaults filled in. |
| `formatToml(options?)` | A config-file template. |
| `formatCli(options?)` | A CLI reference, one aligned line per flag. |
| `formatInvocation(resolved, options?)` | A standalone command line that reproduces resolved settings (what a `--print-invocation` flag prints). |
| `cliOptions()` | The derived flags in the shape `util.parseArgs` takes (`retryLimit` is `retry-limit`). |
| `parseArgs(argv?, extra?)` | Parse arguments with `util.parseArgs`: the derived flags plus `extra.options`. |

`resolve(options?)` takes a `ResolveOptions`:

| Field | Meaning |
| --- | --- |
| `cli` | Parsed CLI values, by declared key; `undefined` or `null` is no opinion. |
| `environ` | Where to read the environment (default `process.env`). |
| `configValue` | An explicit table selection, `PARENT` or `PARENT.CHILD`. |
| `shorthand` | A positional shorthand, looked up as a table in the config files. |

The template methods take a `FormatOptions` (`skip`: settings to leave out;
`defaults`: effective defaults to show instead), and `formatToml` also a
`TomlFormatOptions` (`table`: a name, a path, or `[]` for none; `header`: `false`
drops it), `formatCli` a `CliFormatOptions` (`metavars`: overrides, a list makes
several). All of them use the declared names. `formatInvocation` takes an `InvocationFormatOptions`: `prog` (the program name, written first), `alwaysInclude` (settings to write even when they equal their default), `skip` (settings to leave out; it beats `alwaysInclude`) and `compareDefaults` (effective defaults for this call, merged over the declared ones). `parseArgs` returns a `ParsedArgs`:
`cli` (the setting flags that were given, by declared key), `values` (everything
`util.parseArgs` parsed) and `positionals`.

## Statuses

`developerStatus()` returns a `DeveloperStatus`: `state` (a `DeveloperState`:
`not opted in`, `not configured`, `configured, inactive` or `configured, active`),
`path`, `reason`, `setupError` (the optional `ignore` package is missing),
`format` (`"toml"` or `"dotenv"`, by the file's name -- see `developerFileFormat`)
and `active`. `dotenvStatus()` returns a `DotenvStatus`: `state` (a
`DotenvState`: `disabled`, `active` or `inactive`), `path`, `reason`, `guarded`,
`setupError` and `active`.

## Errors

Every error conclude raises on purpose is a `ConcludeError`:

- `CastError` -- a value does not cast to its setting's type.
- `ConfigFileError` -- a config file is not valid TOML (for the developer file the
  message starts with `developer config file`).
- `ConfigTableError` -- a table selection is malformed (`a..b`, `a.b.c`).
- `SetupError` -- the optional `ignore` package is needed and not installed.

## Building blocks

`defineConfig` is built from plain functions over plain data, mirroring the
concept; they are exported for anyone who wants to assemble the layers by hand.
A `Setting` is `{ key, type, default }` with a canonical key; a `SettingType` is
one of `bool`, `int`, `float`, `str`, `list`; a `SettingValue` is what one can
hold; a `Layer` is raw values by key; `ResolvedValues` is the merged result by
canonical key.

| Area | Functions and types |
| --- | --- |
| Names | `envVarName(app, key)`, `cliFlagName(key)`, `configKeyName(key)` |
| Casting | `cast(type, value)`, `castBool`, `castNumber`, `castStr`, `castList`, `decodeBackslashEscapes` |
| `.env` | `parseDotenv(text)`, `loadDotenv(path)` |
| Layering | `resolve(settings, layers)` with `Layers` (`config`, `env`, `developer`, `cli`) |
| Config files | `loadConfigFiles(files, settings, tablePath)`, `loadConfigFile`, `loadRawToml`, `parseConfigTable`, `resolveConfigTable`, `tableExists`, `auxConfigPaths`, `DEFAULT_AUX_PATTERN`, with `ConfigFiles` and `TableSelection` |
| Guard | `checkGuard(path, options)` with `GuardOptions` and `GuardResult`, `matchesGitIgnoreRules(root, target)` |
| Rendering | `envValue`, `plainText`, `tomlKey`, `tomlString`, `tomlValue` |
| Templates | `formatEnv(settings, options)`, `formatToml`, `formatCli`, with `TemplateOptions` |
| Invocations | `formatInvocation(settings, resolved, options)` with `InvocationOptions` (its `compareDefaults` *replaces* the declared defaults), `shellQuote(text)` |

The gitignore guard never runs `git`: `matchesGitIgnoreRules` evaluates the
`.gitignore` files and `.git/info/exclude` itself, using the optional `ignore`
package.

## Requirements

Node.js 24 or newer. One runtime dependency, `smol-toml`, for TOML. The
optional peer dependency `ignore` is needed only for the gitignore check (the
developer file, or a `.env` held to `dotenvRequireGitignored`).
