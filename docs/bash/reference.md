# conclude for Bash: reference

Every public function, with its arguments and exit status. For how they fit
together, read the [guide](guide.md) first.

Conventions used throughout:

- **`OUTVAR`, `RESOLVEDVAR`, ... are variable *names*.** A function that
  returns text or several values fills the variable you name, in your scope.
  For an associative-array parameter, declare it first (`declare -A vars`).
  Never name one `_cd_...`: those are the library's own internal namerefs.
- **Nothing here changes your shell options** or defines anything outside the
  `conclude_`/`_conclude_` function and `CONCLUDE`/`_CONCLUDE_` variable
  namespaces. `scripts/smoke.sh` checks that on every release.
- `CONCLUDE_VERSION` holds the version of the file.
- Everything needs Bash 5.3+; the file returns non-zero from `source` on an
  older Bash.

## Declaring and resolving

### `conclude_init APP`

Starts `APP`, or restarts it: any settings previously declared for that name are
forgotten. Returns 0.

### `conclude_define APP KEY TYPE [DEFAULT]`

Declares one setting. `TYPE` is `str`, `int`, `float`, `bool` or `list`.
`DEFAULT` is text in the form a user would type (`8080`, `false`, `a,b`).
**Omitting `DEFAULT` (three arguments) means no default; passing `""` (four
arguments) means a default of the empty string.** Settings are remembered in
declaration order.

### `conclude_resolve APP [options] -- ARGS...`

Resolves every setting of `APP` and fills the global associative array
`CONCLUDE` (`CONCLUDE[key]`, `""` for unset; a list is one item per line) and
exports `${APP}_${KEY}` for each (see `conclude_env_var_name`). Returns 0, or 1
if any layer's value fails to cast, a config file is malformed, or an argument
matches no setting; on failure nothing is exported.

Precedence, lowest to highest: defaults, user config, project config (and its
siblings), environment, developer config, command line.

| Option                  | Meaning                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| `--user-config PATH`    | user config file (default `~/.config/APP/config.toml`)                   |
| `--project-config PATH` | project config file (default `./.config.toml`)                           |
| `--no-siblings`         | do not also read `.config.*.toml` beside the project file                |
| `--table PART`          | table to read; repeat for a second level (at most two). Default: `[APP]` |
| `--developer-file PATH` | opt into the developer layer, read from `PATH` while it is guarded       |

Arguments after `--`: `--key value`, `--key=value`, or a bare `--key` for a
bool. A bool given a value (`--debug=false`) is an error. `--flag` names come
from `conclude_cli_flag_name`.

`conclude_resolve` exports its results, so a second call in the same shell sees
them as environment-layer values.

### `conclude_merge_layers TYPESVAR OUTVAR LAYERVAR...`

The merge itself, for when you build your own layers. `TYPESVAR` is an
associative array of key to type; each `LAYERVAR` is an associative array of key
to raw text, lowest priority first. A key that is *present* in a layer (even with
an empty value) is an opinion; an absent key is not. Every layer is cast, even
one a later layer overrides. `OUTVAR` receives every key `TYPESVAR` declares
(`""` if nothing set it). Returns 0, or 1 if any value fails to cast.

## Names

| Function                        | Result                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `conclude_cli_flag_name KEY`    | `filter_col` -> `--filter-col`                                                                                     |
| `conclude_env_var_name APP KEY` | `remind`, `retries` -> `REMIND_RETRIES`. Punctuation in either part becomes `_`; a leading digit gets a `_` prefix |
| `conclude_config_key_name KEY`  | `KEY` itself                                                                                                       |

All three print the name on stdout.

## Casting

### `conclude_cast TYPE VALUE`

Casts text to `TYPE`, printing the canonical form. Exit status is how you tell
"no value" from "a value":

| Status | Meaning                                             | Output                                               |
| -----: | --------------------------------------------------- | ---------------------------------------------------- |
|      0 | cast succeeded                                      | the value (a list: one item per line, possibly none) |
|      1 | `VALUE` is not valid for `TYPE`                     | nothing; message on stderr                           |
|      2 | unset (the empty string, for every type but `bool`) | nothing                                              |

- `bool`: `true`/`yes`/`on`/`y`/`1` and `false`/`no`/`off`/`n`/`0`, case
  insensitive, surrounding whitespace ignored. **The empty string is `false`**,
  never status 2.
- `int` and `float` behave identically: a whole number prints with no decimal
  part, a fraction prints as itself, `1e3` prints `1000`, hexadecimal is an error,
  and whitespace-only text is an error (only truly empty text is status 2).
- `list`: split on commas, each item trimmed, empty items dropped. `,` alone is
  an empty list (status 0, no output), not unset.

### `conclude_decode_backslash_escapes TEXT`

Decodes `\n \t \r \\ \"` left to right and leaves every other character,
including other backslash sequences and non-ASCII text, untouched.

## Reading files

### `conclude_parse_dotenv TEXT OUTVAR` / `conclude_load_dotenv PATH OUTVAR`

Parse a `.env` dialect into the associative array `OUTVAR`. Never `source`s.
`conclude_load_dotenv` leaves `OUTVAR` empty and returns 0 if `PATH` is not a
file.

### `conclude_read_config_table TEXT OUTVAR TABLE1 [TABLE2]`

Reads `[TABLE1]` from TOML text into `OUTVAR` as raw, uncast text; with `TABLE2`,
`[TABLE1.TABLE2]` is layered over it key by key. Returns 1 if the text has a
malformed line anywhere (an array, inline table, date or multi-line string counts
as malformed), whichever table it is in.

### `conclude_load_config_file PATH OUTVAR TABLE1 [TABLE2]`

`conclude_read_config_table` on a file; a missing file gives an empty `OUTVAR`
and status 0.

### `conclude_cast_table_values TYPESVAR RAWVAR OUTVAR`

Casts a raw table to its declared types, dropping undeclared keys and unset
results. Returns 1 if a declared key fails to cast.

### `conclude_parse_table_selection VALUE DEFAULT_TABLE OUTVAR`

Turns `PARENT` or `PARENT.CHILD` into a one- or two-element array in `OUTVAR`
(empty `VALUE` gives `DEFAULT_TABLE`). Returns 1 for a leading, trailing or
doubled dot, or more than two levels.

### `conclude_resolve_table_selection CONFIG_VALUE SHORTHAND DEFAULT_TABLE OUTVAR [-- TEXT...]`

Chooses a table: an explicit `CONFIG_VALUE` wins; otherwise `SHORTHAND` is looked
for as a top-level `[SHORTHAND]`, then as `[DEFAULT_TABLE.SHORTHAND]`, in any of
the `TEXT...` documents; otherwise `DEFAULT_TABLE`.

### `conclude_toml_has_table TEXT TABLE_PATH`, `conclude_glob_match NAME PATTERN`

Status 0 if `TEXT` has a `[TABLE_PATH]` header (dot-joined path), or if `NAME`
matches the shell glob `PATTERN`.

## The guard

### `conclude_check_guard TARGET KILL_SWITCH_VAR ACTIVE_VAR REASON_VAR`

Never fails. Sets `ACTIVE_VAR` to `true` or `false` and `REASON_VAR` to why not.
Checked in order, first failure wins:

1. `KILL_SWITCH_VAR` (a variable *name*, or `""` for none) is set to
   `off`, `0`, `false` or `no` (any case, trimmed): `disabled by NAME=value`
2. `TARGET` is not a file: `file not found`
3. no `.git` file or directory at or above it: `not inside a git working tree`
4. `git check-ignore --no-index` does not ignore it: `not covered by .gitignore`

### `conclude_dotenv_status PATH REQUIRE_GITIGNORED OUTVAR`

`OUTVAR` becomes `disabled` (empty `PATH`), `PATH` (unguarded),
`PATH -- active (gitignored)` or `PATH -- inactive (REASON)`. `REQUIRE_GITIGNORED`
is `true` or `false`.

### `conclude_developer_status APP FILE_PATH OPTED_IN OUTVAR`

`OUTVAR` becomes `not opted in`, `not configured`, `FILE -- configured, active`,
or `FILE -- configured, inactive (REASON)`. The kill switch is
`conclude_env_var_name APP developer_config`, e.g. `MYAPP_DEVELOPER_CONFIG`.

### `conclude_describe_sources APP OUTVAR [options]`

A multi-line report of the sources an app checks, for `--help` output.

| Option                                           | Meaning                                      |
| ------------------------------------------------ | -------------------------------------------- |
| `--system PATH`, `--user PATH`, `--project PATH` | config paths (omit for `disabled`)           |
| `--aux PATTERN`                                  | sibling pattern shown after the project path |
| `--dotenv PATH`, `--dotenv-require-gitignored`   | the `.env` fallback                          |
| `--developer-opted-in`, `--developer-file PATH`  | the developer layer                          |

## Templates

All read the app's declared settings only. `--skip a,b` leaves settings out;
`--default KEY=VALUE` (repeatable) overrides what is shown as a default.

| Function                          | Extra options                                               |
| --------------------------------- | ----------------------------------------------------------- |
| `conclude_format_env APP OUTVAR`  | `--env-var KEY=NAME` (repeatable)                           |
| `conclude_format_toml APP OUTVAR` | `--table PART` (repeatable; default `[APP]`), `--no-header` |
| `conclude_format_cli APP OUTVAR`  | `--metavar KEY=NAME[,NAME2...]` (repeatable)                |

### `conclude_format_env_value TEXT`

`TEXT` as the right of a `NAME=value` line that `conclude_parse_dotenv` reads
back exactly: bare if it is only word characters and `./:@%+,-`, else
single-quoted, else double-quoted with escapes (when it has a `'` or a newline,
tab or carriage return).

### `conclude_format_invocation APP RESOLVEDVAR OUTVAR [options]`

A POSIX-shell-quoted command line reproducing a resolved run.
`RESOLVEDVAR` is an associative array such as `CONCLUDE`.

| Option                        | Meaning                                              |
| ----------------------------- | ---------------------------------------------------- |
| `--prog NAME`                 | leading program name                                 |
| `--skip a,b`                  | leave settings out                                   |
| `--always-include a,b`        | write these even when equal to their default         |
| `--compare-default KEY=VALUE` | compare against this instead of the declared default |

A setting equal to its default is left out, and an off bool is never written.
Quoting is ASCII-only (`café` is quoted).

### `conclude_format_help APP OUTVAR [options]`

A full `--help`/`-h` screen: a usage line, every setting from
`conclude_format_cli`, and the config sources from
`conclude_describe_sources`. A convenience over those two, not a
replacement -- call them directly instead if this shape doesn't fit.

| Option                      | Meaning                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `--prog NAME`               | program name in the usage line (default: `APP`)                                                              |
| `--usage TEXT`              | replaces `[options]` after the program name                                                                  |
| `--before TEXT`             | inserted between the usage line and the flags                                                                |
| `--after TEXT`              | inserted after the flags, before the sources block                                                           |
| `--no-sources`              | leave the config-sources block out entirely                                                                  |
| `--skip a,b`                | settings to leave out of the flag list                                                                       |
| `--sources-args -- ARGS...` | forwarded verbatim to `conclude_describe_sources`; must be last, since it consumes the rest of the arguments |

`conclude_resolve`'s `--help-flag` (see above) is the opt-in convenience
built on this: off by default, so `-h`/`--help` mean nothing until asked
for. When given, `-h`/`--help` anywhere in `conclude_resolve`'s `ARGS...`
prints this function's text and returns 2 -- distinct from 0 (success)
and 1 (error) -- without touching `CONCLUDE` or exporting anything.
`--help-prog`/`--help-usage`/`--help-before`/`--help-after`/
`--help-sources-args` forward to the options above.
