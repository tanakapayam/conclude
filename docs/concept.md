# The conclude concept

conclude is one idea, implemented once per language: **write your settings
down once, as a set of defaults, and derive everything else.** This
document is the language-neutral statement of that idea -- what a
conforming implementation does, independent of syntax. The Python package
is the reference implementation ([guide](guide.md), [reference](reference.md));
other implementations follow this document and pass the conformance
fixtures in [`spec/`](../spec/README.md).

This is **concept version 1**, which is **spec version 1** of the fixtures
(the Python package 1.0.x implements it). The words "must" and "may" are
meant literally: a conforming implementation does what "must" says, and
anything a sentence does not require is up to the implementation.

## 1. The idea

A setting that can come from a flag, an environment variable, or a config
file usually gets written down three times, each with its own name, its own
type conversion, and its own copy of the default. conclude takes one
declaration -- a name, a type and a starting value -- and derives:

1. **the interfaces**: the environment variable, the config-file key, the
   CLI flag, and the caster that turns a raw value from any of them into the
   right type;
2. **the resolution**: a fixed, layered precedence that merges every source
   into one settings object; and
3. **the documentation**: templates and reports generated from the same
   declaration, so they cannot drift from it.

## 2. Vocabulary

- A **setting** is a *key*, a *declared type* and a *default*.
- A **key** is an identifier. Its canonical form is `snake_case`.
- The **declared types** are `bool`, `int`, `float`, `str` and `list`.
- A **default** is a value of the declared type, or **unset** (written
  `null` in the fixtures): an *optional* setting declares its type but
  starts out without a value.
- A **layer** is a source of raw values; a **raw value** is what the layer
  gave (environment values are always text; config-file values are whatever
  TOML gave; CLI values arrive already parsed).
- **No opinion** means a layer says nothing about a key. It is expressed by
  the key being absent or `null`, and never overrides a lower layer.

Settings are ordered (declaration order): generated templates keep it.

## 3. Declaring settings

| Token | Meaning | Casts to |
| --- | --- | --- |
| `bool` | a flag | true or false |
| `int` | a number that prints as a whole number when it is one | an integer, or a fraction if that is what was given |
| `float` | a number | a number |
| `str` | text | text, or unset |
| `list` | a list of text items | a list of text, or unset |

The declared type -- not the runtime shape of the default -- decides the
caster and how a default is rendered in a template. A language that can
infer the type from the default (Python) may do so; one that cannot tell `3`
from `3.0` (JavaScript) must let the author say it.

## 4. Names (`naming.json`)

- **Config key**: the key itself.
- **Environment variable**: the application name and the key, each with
  every character outside `0-9`, `A-Z`, `a-z` and `_` replaced by `_`,
  joined with `_` and upper-cased (ASCII); a name that would start with a
  digit gets a leading `_`. `("my-app", "foo_bar")` is `MY_APP_FOO_BAR`. A
  setting may override its name.
- **CLI flag**: `--` and the key with `_` replaced by `-`; case is kept.
  `filter_col` is `--filter-col`.

Two application names that differ only in which non-identifier character
they use sanitize to the same prefix; that is a known, accepted limit.

## 5. Casting (`casters.json`)

Every layer's value passes through the caster for its setting's declared
type. A caster either returns a value, returns **unset**, or fails with an
error; it never guesses.

- **`bool`**: a true boolean passes through. Anything else is turned into
  text, trimmed and lower-cased: `1 true yes on y` are true, `0 false no off
  n` are false, and empty text is false. Any other text is an error (so the
  typo `tru` is caught, not treated as false).
- **`int`**: `null` and empty text are unset. A number is itself (a whole
  number stays whole). Text is trimmed, then read as an integer -- optionally
  with a redundant all-zero decimal part (`5`, `5.0`, `5.00`) -- or else as a
  decimal or exponent number (`1.5`, `1e3`), which is returned as an integer
  when it is whole. Anything else, including text that is only whitespace and
  hexadecimal text, is an error.
- **`float`**: `null` and empty text are unset; otherwise the trimmed value
  must be a decimal or exponent number (`0.5`, `.5`, `5.`, `1e-2`), else an
  error.
- **`str`**: `null` and empty text are unset; anything else becomes text,
  untouched (no trimming).
- **`list`**: `null` and empty text are unset. A list has each item turned
  into trimmed text, dropping empty ones. Text is split on commas the same
  way, so `a,,b,` is `["a", "b"]` and `,` is an empty list.

## 6. Layers and precedence (`merge.json`)

From lowest to highest priority:

```
defaults < system < user < project < env < developer < CLI
```

`system`, `user` and `project` are config files (section 7); `env` is the
process environment, with an optional `.env` file beneath it (section 8);
`developer` is a private local file (section 10).

1. Layers are merged from lowest to highest, key by key, each value cast as
   it lands; a higher layer replaces a lower one outright (lists are
   replaced, not concatenated).
2. A `null` (or absent) value is *no opinion*. An **empty string is a
   value**: it is cast like any other, so `""` overrides a lower layer and
   resolves to unset for `int`, `str` and `list`, and to false for `bool`.
   To have no opinion, leave the key out.
3. Keys that no setting declares are ignored, so a file or an environment can
   carry unrelated keys.
4. Defaults are cast too, and every declared key is present in the result;
   optional settings that nothing set are `null`.
5. A cast failure is an error wherever the bad value came from -- even in a
   layer that a higher one would have overridden.
6. Whether a still-unset setting is acceptable is the application's concern,
   not the merge's.

## 7. Config files (`config_layers.json`, `config_tables.json`)

| Layer | Location | On by default? |
| --- | --- | --- |
| system | `/etc/<name>/config.toml` | no (opt-in) |
| user | `~/.config/<name>/config.toml` | yes |
| project | `./.config.toml` | yes |
| project siblings | `./.config.*.toml`, sorted by name | yes (the pattern is configurable; it can be switched off alone) |

The files are merged key by key in that order, so a key set in a later file
wins; each source may be switched off, and a missing file contributes
nothing.

Files are TOML. A setting lives in a **table** named after the application
(or another chosen name). A table path has one or two levels, written
`PARENT` or `PARENT.CHILD`; with two, the parent table supplies shared
values and the child table overrides them. Only keys that a setting declares
are read. A missing table, or a name that is not a table, contributes
nothing; a file that is not valid TOML is a loud error that names the file.

**Choosing the table.** An explicit selection (a flag, or its environment
variable) wins outright. Otherwise a bare positional *shorthand* is looked
up in the files themselves -- across every file and sibling, as a union: a
top-level `[SHORTHAND]` table wins, then a nested `[<name>.SHORTHAND]`,
else the application's own table. Text with an empty part (`a..b`, `a.`,
`.a`) or more than two levels is an error, not a spelling of something else.

## 8. The `.env` file (`dotenv.json`)

An opt-in **fallback beneath the real environment**: a variable that is
actually set in the process always wins, and the file only supplies the rest.
Its keys are environment variable names.

The file is UTF-8 on every platform, and a leading byte-order mark is
ignored. One variable per line: `NAME=value`, with an optional leading
`export `; blank lines and lines starting with `#` are skipped, as are lines
without an `=`. The key and the value are trimmed, only the first `=`
separates them, and a later duplicate wins. A value wrapped in matching
quotes has them removed: single quotes are literal, double quotes also decode
`\n`, `\t`, `\r`, `\\` and `\"` (any other backslash sequence is left as
written). Not supported, on purpose: multi-line values, inline comments, and
`${VAR}` interpolation.

An application may require the file to pass the gitignore guard (section 9)
before it is read; if it fails, nothing is read from it.

## 9. The gitignore guard (`guard.json`, `gitignore.json`)

A file that beats -- or quietly backstops -- the environment must never come
from somewhere it shouldn't: a fresh clone, a CI checkout, a deployed image.
"Inside a git working tree, and ignored by it" is the practical proxy for
"this is somebody's private local file", and it can be checked without a
`git` executable.

The checks run in this order and the first failure is the **reason**:

1. **Kill switch**: if a kill-switch variable is configured and the real
   environment sets it (trimmed, case-insensitive) to `0`, `off`, `false` or
   `no`: `disabled by <VAR>=<value>` (the trimmed value, as written).
2. The file does not exist: `file not found`.
3. It is not inside a git working tree -- no ancestor directory holds a
   `.git` (a directory, or a file, as in a worktree or submodule):
   `not inside a git working tree`.
4. No ignore rule matches it: `not covered by .gitignore`.
5. Otherwise the file is **active**.

The kill switch is a control knob, not a setting: it is read only from the
real environment, and it is checked first so it also avoids needing the
matcher.

**Matching the rules.** The rules are the `.gitignore` files from the
repository root down to the file's directory, plus the repository's
`.git/info/exclude`. Nearer `.gitignore` files override farther ones, and
`info/exclude` has the lowest priority; within a file the last matching
pattern wins (so `!pattern` un-ignores); and an ignored directory ignores
everything beneath it, whatever the files inside say. The global
`core.excludesFile` is not consulted, and the check looks at patterns, not
at git's index -- a *tracked* file that matches a pattern still counts as
ignored. Both limits fail closed except that last one.

If the matching capability is unavailable (an optional dependency that is not
installed), that is a **setup error**, reported as such rather than as an
ordinary inactive file -- see the quiet-versus-loud rule below.

## 10. The developer layer

An opt-in, private, project-local file that sits **above the environment**
and below the CLI. Environment variables are process-wide and can leak
between projects; a file whose location the project decides is scoped to
exactly the project it belongs to, so it wins over ambient state.

- **Where it is declared** is a per-ecosystem *manifest binding* (section
  14): the committed project manifest names the file, relative to the
  manifest's directory.
- **Format follows the name.** A name ending in `.toml` is TOML, read with
  the same tables as any config file (section 7). Any other name (say
  `.env.local`) is dotenv (section 8), keyed by the application's
  environment variable names, so the same private file can serve other tools;
  dotenv has no tables, and an empty value is cast like an empty environment
  variable (section 6), not skipped.
- **The guard is mandatory** (section 9), with a kill switch named after the
  application: `<APP>_DEVELOPER_CONFIG`, using the environment naming of
  section 4.

The layer is always in one of four states, which reports show verbatim:

| State | Meaning |
| --- | --- |
| `not opted in` | the application never asked for the layer |
| `not configured` | opted in, but the manifest names no file |
| `configured, inactive` | a file is named but a guard check failed; the reason says which |
| `configured, active` | the file is read |

An `.env` file held to the guard reports `disabled` (no path), `active` or
`inactive` in the same spirit (for example `.env -- active (gitignored)` or
`.env -- inactive (not covered by .gitignore)`); without the guard it is
simply `active` whenever it has a path.

**Quiet for ordinary situations, loud for broken setups.** Every state above
is ordinary -- a teammate who has not made their file yet, a CI run, a
deploy -- so an inactive layer contributes nothing and raises nothing;
reports say why. Two things are setup errors and raise: the missing matching
capability (section 9), and an *active* file that is not valid TOML. Status
and report calls never raise.

## 11. Generated templates and invocations (`templates.json`, `invocation.json`)

Every template renders the same declared settings, in order, with their
defaults; options can skip settings, replace a default with the *effective*
one, rename an environment variable, choose the TOML table (or drop its
header), and rename a CLI metavar.

A default's **plain text** is: `true` or `false` for a `bool`; the items
joined with `,` for a `list`; a `float` with a decimal point even when whole
(`3.0`); otherwise the value's text. A setting with no default has no plain
text and renders as a placeholder.

**Environment template**: one `NAME=value` line per setting, or `# NAME=` for
an unset one. The value is written bare if it consists only of letters,
digits and `_` (from any script) and the punctuation `. / : @ % + , -`
(that is, `[\w./:@%+,-]*`, so the empty string is bare); otherwise in single
quotes if it holds no `'` and no newline, tab or carriage return; otherwise in
double quotes with `\\`, `\"`, `\n`, `\t` and `\r` escaped.

**TOML template**: a `[table]` header (the application name by default; a
name that is not a bare key -- `A-Za-z0-9_-` -- is quoted), then one
`key = value` line per setting with native values: `true`/`false`, numbers, a
list as `["a", "b"]`, and text as a double-quoted string in which `\`, `"`,
newline, tab and carriage return are escaped as `\\`, `\"`, `\n`, `\t`, `\r`
and every other control character (U+0000-U+001F and U+007F) as `\uXXXX` with
upper-case hexadecimal. An unset setting is `# key =`. An empty table path
means no header.

**CLI reference**: one line per flag. A `bool` is the bare flag; any other
setting is the flag and `<METAVAR>` (the key upper-cased, or the override).
Each line ends with `(default: text)`, where an unset default reads `none`,
an empty text reads `""`, and the flag column is padded to the widest so the
`(default:` parts align, with one space after it.

**Reproducing a run.** The inverse of resolving: given a resolved configuration,
a standalone command line that gets back to it with no environment variables,
config files or shorthand -- what a `--print-invocation` flag prints. Settings
are visited in declaration order, and each is written as `--flag=value` (a bare
`--flag` for a `bool` that is on) unless it is left out. A setting is left out
when it equals its default -- omitting a flag already reproduces its default, and
this covers every setting automatically -- when it is a `bool` that is off (there
is no flag to turn one off), when its value is unset, or when the caller skips it
(`skip` beats `alwaysInclude`, which forces a setting that equals its default to
be written). `compareDefaults` replaces what counts as each setting's default for
one call, for a setting whose effective default is substituted after resolving.
The program name, if given, comes first. Values are POSIX shell-quoted: bare if
every character is a letter or digit from ASCII, or one of `_ @ % + = : , . / -`,
otherwise in single quotes with each `'` written as `'"'"'` (so non-ASCII letters
are quoted, and an empty text is `''`); a list is its items joined with `,`, then
quoted; a `float` keeps its decimal point (`3.0`).

## 12. Reports (`sources.json`)

A report of the sources in play, for a `--help` epilog, is a header line
`config sources:` and then one row per source, lowest priority first:

```
config sources:
  system config     disabled
  user config       /home/me/.config/myapp/config.toml
  project config    .config.toml, .config.*.toml
  .env file         disabled
  developer config  not opted in
```

Each row is two spaces, the label padded to the longest label
(`developer config`), two more spaces, and the value. The value of the
config-file rows is the path, or `disabled` when that source is switched off;
the project row also lists the sibling pattern (in the same directory as the
project file) unless siblings are off. The `.env` row is `disabled`, its path
(when no guard is required), or -- for a guarded file --
`<path> -- active (gitignored)` or `<path> -- inactive (<reason>)`. The
developer row is one of the four states of section 10, with the guard's reason
for an inactive file.

## 13. Conformance

An implementation conforms to spec version 1 when it passes every fixture in
[`spec/`](../spec/README.md). The fixtures are data, not code; each
implementation writes a small adapter from a fixture file to its own API.

| Fixture | Sections | What it covers |
| --- | --- | --- |
| `naming.json` | 4 | environment variable, flag and key names |
| `casters.json` | 3, 5 | casting for every declared type |
| `dotenv.json` | 8 | the `.env` dialect |
| `merge.json` | 6 | precedence, no-opinion, empty values, errors |
| `config_layers.json` | 7 | merging system, user, project and sibling files; tables |
| `config_tables.json` | 7 | table selection and the positional shorthand |
| `templates.json` | 11 | the environment, TOML and CLI templates |
| `invocation.json` | 11 | reproducing a resolved configuration as a command line |
| `gitignore.json` | 9 | rule matching, judged by real `git` |
| `guard.json` | 9 | the guard's checks and reasons |
| `sources.json` | 10, 12 | the report of which sources are in play |

Not yet covered by fixtures: how each binding reads its manifest (section 10;
the wording of a `not configured` reason is binding-specific), and how a
language exposes flags to its CLI parser.

## 14. What varies by language

| Concern | Python (reference) | TypeScript ([`node/`](../node/README.md)) |
| --- | --- | --- |
| Declaring settings | a dict of defaults; `opt(type)` for an unset one | an object of defaults, with `int()`, `float()`, `str()`, ... for numbers and unset settings |
| Type inference | the default's runtime type | the default's runtime type, plus explicit `int` and `float` (D2) |
| Key style in the API | `snake_case` | `camelCase`, converted (D1) |
| Manifest binding | `pyproject.toml`, `[tool.conclude.developer] config = "..."` | `package.json`, `"conclude": { "developer": { "config": "..." } }` (D3) |
| CLI | builds `argparse` flags | flag definitions in `node:util.parseArgs`' shape, plus a thin `parseArgs` wrapper (D4) |
| TOML | standard library | a small dependency (D5) |
| Gitignore matching | the optional `pathspec` extra | an optional dependency (D5) |

**Decisions for other bindings.** The TypeScript package follows all five (its
[guide](node/guide.md) and [reference](node/reference.md) show how):

- **D1: canonical names in files and the environment.** Config-file keys and
  environment variable names use the canonical `snake_case` of section 4, so
  one config file or `.env` serves every implementation; a binding's API may
  use its own casing and converts (`filterCol` is `filter_col`).
- **D2: numeric kinds are explicit** where the language cannot distinguish
  them, and templates render per declared kind (section 11).
- **D3: each ecosystem uses its own manifest** to name the developer file;
  in a repository with several, they may name the same file.
- **D4: no bundled CLI parser.** The binding exposes derived flag
  definitions rather than owning the command line.
- **D5: dependencies are minimal.** A TOML parser is required; gitignore
  matching is optional, and its absence is a setup error (section 9).

## 15. Implementation-defined

The fixtures deliberately say nothing about these; implementations may differ
and should document what they do:

- integers beyond 2^53, `inf` and `nan`, underscores or non-ASCII digits in
  numerals, and how a native boolean is cast by `int` or `str`;
- line breaks other than `\n`, `\r\n` and `\r` in a `.env` file;
- how a very small or very large `float` is written (exponent form) in a
  template;
- reproducing a run for a `bool` whose default is true (there is no flag to turn
  it off, so it cannot be reproduced), and for a non-`bool` setting whose
  resolved value is unset while its default is not (Python writes `None`; the
  TypeScript binding leaves it out);
- a default of empty text on a `str` setting when it is *resolved* (the
  template shows it; the merge casts it to unset);
- what a boolean, a list or another non-text value does when cast to `str`,
  and what a boolean does when cast to `int` or `float` (Python converts;
  the TypeScript binding rejects them);
- the wording of the manifest-related reasons (`not configured`), and of
  errors.
