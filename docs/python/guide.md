# Guide

This guide builds one small tool, `remind`, from nothing up to a
realistic full-featured CLI -- each section adds one idea on top of
the last. For the one-page overview, see the
[README](https://github.com/tanakapayam/conclude#readme); for every
class, method and module, see the [reference](reference.md).

## 1. The bare minimum

`remind` is going to be a command-line reminder tool. It starts with
one required setting and one with a real default:

```python
import conclude

DEFAULTS = {
    "message": conclude.opt(str),  # required in practice -- no sensible default
    "delay": 0,                    # minutes from now; 0 = immediately
}

app = conclude.App("remind", DEFAULTS)

parser = app.build_arg_parser(prog="remind")
namespace = parser.parse_args()
cli = {k: v for k, v in vars(namespace).items() if v is not None}

settings = app.resolve(cli)
print(settings)
```

```
$ python remind.py --message="Take out the trash" --delay=30
{'delay': 30, 'message': 'Take out the trash'}
```

That's the whole setup -- one dict. From it, `app` already knows:

- **CLI flags**: `--message`, `--delay`
- **Env vars**: `REMIND_MESSAGE`, `REMIND_DELAY`
- **Config-file keys**: `message`, `delay`, read from a `[remind]` table
- **Casters**: a string cast for `message` (from `opt(str)`), an int
  cast for `delay` (from its plain `0` default)

`conclude.opt(type)` is the one thing you have to remember: a setting
that starts out unset (`None`) can't tell inference what type it
should become once it *is* set, so `opt(str)`/`opt(int)`/`opt(list)`
say that explicitly. A setting with an actual starting value (`0`,
`False`, `"normal"`) needs no such wrapper -- its own type is enough.

## 2. More settings, and where each layer actually applies

Real tools have more than two settings, and the whole point of the
four layers is that any of them can supply a value:

```python
DEFAULTS = {
    "message": conclude.opt(str),
    "delay": 0,
    "channel": conclude.opt(str),   # "email", "slack", "sms" -- unset = ask interactively
    "repeat": False,                # keep reminding until acknowledged
    "retries": 3,
}
app = conclude.App("remind", DEFAULTS)
```

Now all four layers are live at once:

```
$ export REMIND_CHANNEL=slack
$ cat .config.toml
[remind]
retries = 5

$ python remind.py --message="Stand up" --delay=5
{'delay': 5, 'repeat': False, 'retries': 5, 'channel': 'slack', 'message': 'Stand up'}
```

`channel` came from the environment variable, `retries` came from
`./.config.toml`'s `[remind]` table, `repeat` fell all the way through
to its hardcoded default, and `message`/`delay` came from the CLI
flags -- which, being the highest-priority layer, would have won even
if the other three had also set them.

## 3. When inference isn't quite enough: casters and formatters

Say `--delay` should accept `"2h"` or `"30m"`, not just a bare number
of minutes. That's a real setting-specific parsing rule inference has
no way to guess, so write it as a caster -- and, if you also want
`--print-invocation` ([section 5](#5-debugging-and-documentation---print-invocation)) to print it back out the same way
rather than as a bare number of minutes, a matching formatter:

```python
def cast_duration(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("h"):
        return int(text[:-1]) * 60
    if text.endswith("m"):
        return int(text[:-1])
    return int(text)

def format_duration(value):
    return f"{value // 60}h" if value % 60 == 0 else f"{value}m"

app = conclude.App(
    "remind",
    DEFAULTS,
    casters={"delay": cast_duration},
    formatters={"delay": format_duration},
)
```

Every other setting's caster/formatter is still fully inferred --
`casters=`/`formatters=` only override the keys you actually name.
`--delay=2h`, `REMIND_DELAY=2h`, and a config file's `delay = "2h"`
now all resolve to `120`.

## 4. A positional shorthand + per-recipient config tables

`remind mom` should be shorthand for "use whatever's configured for
mom" -- a `[mom]` table in a config file supplying `channel`, maybe a
different `retries`, without repeating `--channel=sms` every time.
This needs a hand-built parser (a positional argument isn't part of
`defaults`, so there's nothing to infer it from), but every *setting*
flag is still added automatically:

```python
import argparse

parser = argparse.ArgumentParser(prog="remind")
parser.add_argument("recipient", nargs="?", default=None)
app.add_arguments(parser)
namespace = parser.parse_args()
cli = {k: v for k, v in vars(namespace).items() if v is not None}

table_path = app.resolve_config_table(shorthand_value=namespace.recipient)
config_file = app.load_config_files(table_path)
settings = app.resolve(cli, config_file=config_file)
```

With this in `.config.toml`:

```toml
[mom]
channel = "sms"
retries = 10
```

`remind mom --message="Call Sunday"` resolves `channel` and `retries`
from `[mom]`, same as if you'd typed `--channel=sms --retries=10`
yourself -- and `remind mom --channel=email` still lets the CLI flag
win outright, same as any other layer conflict.

## 5. Debugging and documentation: `--print-invocation`

However a run's settings actually got resolved -- some flags, some env
vars, someone else's `[mom]` table, whatever -- `format_invocation`
renders the one standalone command line that reproduces it, with
every default omitted (there's nothing to gain by spelling out a
setting that's just sitting at its default):

```python
app.add_print_invocation_argument(parser)
namespace = parser.parse_args()
...
if namespace.print_invocation:
    print(app.format_invocation(settings, prog="remind", skip={"recipient"}))
```

```
$ python remind.py mom --message="Call Sunday" --print-invocation
remind --message='Call Sunday' --channel=sms --retries=10

$ REMIND_CHANNEL=slack python remind.py mom --message="Call Sunday" --print-invocation
remind --message='Call Sunday' --channel=slack --retries=10
```

`--channel` tracks whichever layer actually won: `mom`'s own config
table the first time, the environment variable overriding it (env
outranks a config file) the second -- without you having to mentally
re-run the precedence chain yourself. That's the actual debugging
value here: whatever produced a confusing resolved setting, the tool
hands you back the one command that reproduces it exactly, ready to
paste into a bug report or a script.

## 6. Local development: a `.env` file

For a setting you'd rather not type or export every time locally,
drop a `.env` file next to where you run the tool:

```
# .env
REMIND_CHANNEL=slack
REMIND_RETRIES=1
```

...and opt in to reading it, by passing `dotenv_path=conclude.AUTO`
when constructing `App`:

```python
app = conclude.App("remind", DEFAULTS, dotenv_path=conclude.AUTO)
```

This source is off by default (as is the system config file, [section 7](#7-machine-wide-defaults-a-system-config-file)): reading an arbitrary local file looking for environment-variable-shaped
values is exactly the kind of thing that shouldn't happen just because
nobody thought about it -- a `.env` full of real credentials sitting in a directory
conclude read from unconditionally would be an easy way to leak them.
`AUTO` means "yes, use the conventional `./.env`, on purpose."

Once enabled, `app.load_env()` (which `app.resolve()` calls
automatically when you don't load the env layer yourself) reads
`./.env` as a fallback for anything not actually exported in the real
environment -- a real `export REMIND_CHANNEL=...` in your shell, or
one injected by whatever deploys this tool for real, always wins over
a leftover `.env` file. Pass a specific `Path` instead of `AUTO` for a
non-conventional filename, or leave `dotenv_path` unset (the default)
to skip this layer entirely.

### Making `.env` strict

A committed `.env` of non-secret local defaults is common, and that is
what the plain option assumes. If yours holds private values instead,
hold it to the same standard as the developer file
([section 8](#8-a-private-developer-config-file)) with
`dotenv_require_gitignored=True`:

```python
app = conclude.App(
    "remind",
    DEFAULTS,
    dotenv_path=conclude.AUTO,
    dotenv_require_gitignored=True,
)
```

Now `./.env` is read only if it exists, sits inside a git working
tree, and is ignored by it -- the same guard [section 8](#8-a-private-developer-config-file) explains, with
the same optional dependency (`pip install 'conclude[gitignore]'`).
Otherwise it is skipped quietly, and `describe_sources()` says which
case it is:

| The `.env file` row says      | Meaning                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `disabled`                    | no `dotenv_path` (the default)                                                 |
| `.env`                        | opted in, no guard requested: read if it exists                                |
| `.env -- active (gitignored)` | guard requested, and passed                                                    |
| `.env -- inactive (<why>)`    | guard requested, and failed: file not found, not inside a git working tree, or not covered by .gitignore |

The quiet-versus-loud rule is the developer file's too: the one thing
that raises is an `ImportError` when the file needs the ignore check
and `pathspec` isn't installed. `app.dotenv_status()` returns the same
information as data (a `DotenvStatus`) and never raises.

Two honest notes. It gates *reading*, not committing: an un-ignored
`.env` simply stops loading, which is a nudge more than a wall. And if
all you need is private local values, the developer file does that
already -- and beats the environment -- so a strict `.env` earns its
place when the file is shared with other tools that read it too
(docker compose, direnv, IDE run configurations). It stays *below* the
real environment either way.

## 7. Machine-wide defaults: a system config file

Say `remind` gets installed on a shared machine and the admin wants
every user's default `channel` to be `slack` without touching anyone's
home directory. Drop a config file in the conventional system-wide
location:

```toml
# /etc/remind/config.toml
[remind]
channel = "slack"
retries = 5
```

...and opt in to reading it, the same way as `.env`, by passing
`config_system_path=conclude.AUTO`:

```python
app = conclude.App("remind", DEFAULTS, config_system_path=conclude.AUTO)
```

`AUTO` resolves to `/etc/<name>/config.toml` (here,
`/etc/remind/config.toml`); pass a specific `Path` instead for a
non-conventional location.

The system file sits *right above the hardcoded defaults* and below
everything else, so any user can still override it, key by key:

```
defaults < system < user < project < env < developer < CLI
```

A user's `~/.config/remind/config.toml` setting `retries = 2` wins
over the system file's `retries = 5`, while `channel` still comes from
`/etc`. A `[mom]`-style shorthand table ([section 4](#4-a-positional-shorthand--per-recipient-config-tables)) defined in the
system file is found too, same as one in any other config file.

Like `.env`, this is off unless you opt in: a machine-wide file
silently changing a program's behavior for every user on the box is a
decision about the program, not something that should happen because
nobody thought about it. (`/etc/...` is a POSIX convention -- on
Windows the conventional path simply won't exist, so nothing is read;
pass your own `Path` there.)

## 8. A private developer config file

Say you're working on `remind` and want reminders printed to the
console instead of sent to Slack -- but your shell has
`REMIND_CHANNEL=slack` exported from some other project, or a
teammate's setup script. (A local `DATABASE_URL` is the classic
version of this.) That's the trouble with environment variables:
they're process-wide and leak between projects. A file whose location
the *project* decides doesn't.

> Environment variables are process-wide and can accidentally leak
> between projects. The developer configuration is project-scoped and
> therefore takes precedence over ambient environment state. Use the
> CLI for a one-off override.

So there's one more layer, above the environment and below the CLI:

```
defaults < system < user < project < env < developer < CLI
```

| Layer     | Source                                                   | Scope                                    |
| --------- | -------------------------------------------------------- | ---------------------------------------- |
| defaults  | your `defaults` dict                                     | the library/application                  |
| system    | `/etc/<name>/config.toml` (opt-in)                       | machine-wide defaults                    |
| user      | `~/.config/<name>/config.toml`                           | the user's persistent preferences        |
| project   | `./.config.toml`, `./.config.*.toml`                     | shared project configuration             |
| env       | environment variables (+ opt-in `.env` fallback)         | ambient process state                    |
| developer | file named in `pyproject.toml` (opt-in, must be ignored) | project-local, private developer config  |
| CLI       | flags                                                    | one invocation                           |

Three pieces set it up. The committed `pyproject.toml` says where a
developer's private file lives (relative to that `pyproject.toml`):

```toml
[tool.conclude.developer]
config = ".remind.local.toml"
```

`.gitignore` keeps it private -- this is required, not a nicety
(below):

```
.remind.local.toml
```

And the file itself -- TOML is the default -- has the same `[table]`
layout as any other config file (`app.format_toml()` from [section 10](#10-generating-docs-and-templates) writes the skeleton):

```toml
[remind]
channel = "console"
```

The app opts in, and installs the one optional dependency the ignore
check needs (`pathspec`, pure Python -- the same one a strict `.env`
uses):

```python
app = conclude.App("remind", DEFAULTS, pyproject_path=conclude.AUTO)
```

```
pip install 'conclude[gitignore]'
```

Now `REMIND_CHANNEL=slack` in the shell no longer matters inside this
project, and `remind --channel=email` still wins for a one-off.

**TOML or dotenv.** The file's format follows its name: a name ending
in `.toml` is TOML, as above, and anything else -- only `.toml` is
TOML -- is dotenv, the same syntax as `.env`. Point `pyproject.toml`
at a `.env.local` and the layer reads that instead:

```toml
[tool.conclude.developer]
config = ".env.local"
```

```
# .env.local (gitignored)
REMIND_CHANNEL=console
```

The point is sharing. A value that docker compose, direnv or your
IDE's run configuration also needs can live in one gitignored file
instead of two (Compose reads `.env` on its own; for `.env.local` you
point it there with `env_file:` or `--env-file`). The keys are the
environment variable names `app.resolved_env_vars` gives --
`REMIND_CHANNEL` by default, or a bare `DATABASE_URL` if you gave that
setting `env_vars={"database_url": "DATABASE_URL"}` -- and
`app.format_env()` ([section 10](#10-generating-docs-and-templates)) writes the skeleton, as `format_toml()`
does for TOML. Between them, the two formats fill in the whole grid:

| Format | Below the environment                               | Above the environment                    |
| ------ | --------------------------------------------------- | ---------------------------------------- |
| TOML   | the system, user and project files ([section 2](#2-more-settings-and-where-each-layer-actually-applies), [section 7](#7-machine-wide-defaults-a-system-config-file)) | the developer file (this section)        |
| dotenv | `.env` ([section 6](#6-local-development-a-env-file))                                    | the developer file, as `.env.local`      |

Everything else about the layer is unchanged -- the same guard, the
same kill switch, the same quiet-versus-loud rules -- with three things
to know about the dotenv format:

- **There are no tables.** Dotenv has none, so a `[mom]`-style
  shorthand table ([section 4](#4-a-positional-shorthand--per-recipient-config-tables)) doesn't apply to it: the file's variables
  apply to every invocation.
- **Values are raw strings**, cast like any other layer's, and an empty
  value (`REMIND_RETRIES=`) is cast like an empty environment variable,
  not skipped. Leave a line out, or comment it out as `format_env()`
  does for an unset setting, to have no opinion.
- **It beats the real environment, which most other readers of a
  `.env`-style file don't.** With a stale `export REMIND_CHANNEL=slack`
  in your shell, `remind` uses the file's `console`, while a tool that
  lets the shell win may use `slack` from the very same file. That is
  the point of this layer, and the reason to keep stray exports out of
  your shell.

**When it applies.** A file that beats the environment must never come
from somewhere it shouldn't -- a fresh clone, a CI checkout, a deployed
image -- so it is deliberately hard to switch on by accident. Five
checks run in order, and the first one that fails stops there and the
layer contributes nothing:

```
opted in? ──────────────────────────────────────────── no  ──▶ not opted in
   │ yes
pyproject sets tool.conclude.developer.config? ─────── no  ──▶ not configured
   │ yes
kill switch (<APP>_DEVELOPER_CONFIG=off) set? ──────── yes ──▶ configured, inactive
   │ no
file exists? ───────────────────────────────────────── no  ──▶ configured, inactive
   │ yes
inside a git tree AND covered by its ignore rules? ─── no  ──▶ configured, inactive
   │ yes
   ▼
configured, active
```

**Quiet, and the two things that are not.** Every check in that flow
fails *quietly* -- no exception, no warning -- because each is an
ordinary situation: a teammate who hasn't made their file yet, a CI
run, a deploy. Two situations are different. They are setup errors that
only a developer can fix, and a quiet skip would hide them behind "why
isn't my file being used?", so they raise:

| Raises            | When                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------------------------------ |
| `ImportError`     | the file is named, exists, and is in a git tree -- so the ignore check must run -- but `pathspec` is missing |
| `ConfigFileError` | the file is active (all five checks passed) but isn't valid TOML                                             |

Both messages name the file, and the `ImportError` also tells you what
to install -- or that `<APP>_DEVELOPER_CONFIG=off` skips the file
instead, since the kill switch is checked before `pathspec` is ever
needed. They come from `resolve()` / `load_developer_config()`.
`describe_sources()` and `developer_status()` never raise: for the
missing-`pathspec` case they report it in the `inactive (...)` reason
instead, so `--help` still works.

The same four states, as `describe_sources()` reports them in `--help`
(the reason is always spelled out for the inactive case, since "why
isn't my local file being used?" is the obvious question):

| It says                                | Meaning                                                  |
| -------------------------------------- | -------------------------------------------------------- |
| `not opted in`                         | the app never passed `pyproject_path=`                   |
| `not configured (...)`                 | opted in, but `pyproject.toml` names no file             |
| `<file> -- configured, inactive (...)` | named, but a check above failed -- the reason says which |
| `<file> -- configured, active`         | read, and beating the environment                        |

```
$ remind --help
...
  developer config  .remind.local.toml -- configured, inactive (not covered by .gitignore)
```

`app.developer_status()` returns the same thing as data (a
`DeveloperStatus` with `.state`, `.path`, `.reason`) for an app that
wants a `--diagnose` flag, and never raises.

A few details worth knowing:

- **The ignore check is git's own rules, in Python.** It reads the
  `.gitignore` files from the repository root down to the file's
  directory plus `.git/info/exclude`, with nearer files overriding
  farther ones and an ignored directory ignoring everything in it --
  checked against real `git check-ignore` in the test suite. Two
  limits: the global `core.excludesFile` isn't consulted (the file just
  stays inactive), and it's pattern matching rather than git's index,
  so a *tracked* file that matches a pattern (`git add -f`) still
  counts as ignored.
- **A file outside a git working tree is inactive**, as is one that
  doesn't exist yet -- so copying a project without its `.git` (a
  tarball, or an image whose `.dockerignore` leaves `.git` out) leaves
  the layer off.
- **Docker images are the one leak to watch.** `.dockerignore` is
  separate from `.gitignore`, so `COPY . .` will happily copy a
  developer's ignored file into an image, where it would then beat the
  real environment. List the file in `.dockerignore`, and/or set the
  kill switch `REMIND_DEVELOPER_CONFIG=off` (`0`/`false`/`no` work too)
  in deployments. The switch is read from the real environment only --
  it's a control knob, not a setting, so no `.env` file or config layer
  can carry it.
- **`pathspec` is only imported when it's needed.** Not opted in, not
  configured, kill switch set, no such file, no git tree -- none of
  those touch it, so a production install without the extra is
  unaffected unless a developer file is genuinely sitting there.
- **Shorthand tables:** if you choose a config table yourself ([section 4](#4-a-positional-shorthand--per-recipient-config-tables)), hand the developer layer the same one --
  `app.resolve(cli, config_file=app.load_config_files(table_path),
  developer=app.load_developer_config(table_path))`.

## 9. Turning off a source, and telling the user

Say `remind` should never read a project-local `.config.toml` --
maybe it only ever runs from a fixed install location, and a stray
`.config.toml` left over from testing would be a footgun, not a
feature. Disable it in the constructor, the same way `.env` is off
unless you opt in:

```python
app = conclude.App("remind", DEFAULTS, config_cwd_path=None)
```

Now `[remind]`/`[mom]` tables are only ever read from
`~/.config/remind/config.toml` (plus the system file, if you opted in
to that) -- a `./.config.toml` sitting in the
current directory is invisible to this app entirely, whether or not
one happens to exist.

The project file's *siblings* are a separate, quieter default: any
`.config.<something>.toml` next to `./.config.toml` is merged in too
(sorted by name, each beating the plain file), which is what lets a
pile of self-contained tables live in a file of their own -- and also
means a stray `.config.backup.toml` silently joins the merge. Keep the
project file but drop the sibling search with
`config_cwd_aux_pattern=None`, or narrow it to your own pattern
(`config_cwd_aux_pattern=".config.local.toml"`). `describe_sources()`
lists the pattern in its `project config` row, so it's never a secret.

**A note on trust.** Project config is read from the current directory,
so a tool run inside a directory someone else controls -- a fresh
clone, an unpacked download -- reads *that* directory's `.config.toml`
and its siblings. That is the usual trade for per-project settings, and
it's why every way to turn it off is one `None` away. (The developer
layer, [section 8](#8-a-private-developer-config-file), is deliberately stricter: it only applies to a file
git is ignoring, which a clone can't ship.)

Whether a source like this is even active is a fact about how the
*program* was built, not about any one run's resolved values -- so it
belongs in `--help`, not `--print-invocation` (which reports resolved
settings, not the layering topology that produced them).
`describe_sources()` renders exactly that, ready to drop into an
`epilog` -- note the `RawDescriptionHelpFormatter`, needed so argparse
doesn't re-wrap and mangle the aligned columns:

```python
parser = argparse.ArgumentParser(
    prog="remind",
    epilog=app.describe_sources(),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
```

```
$ remind --help
...
config sources:
  system config     disabled
  user config       /Users/payam/.config/remind/config.toml
  project config    disabled
  .env file         disabled
  developer config  not opted in
```

(Sources are listed lowest priority first. `system config` and
`.env file` show `disabled` here because this `App` never opted in
with `config_system_path=conclude.AUTO` ([section 7](#7-machine-wide-defaults-a-system-config-file)) or
`dotenv_path=conclude.AUTO` ([section 6](#6-local-development-a-env-file)). Add those and they read
`/etc/remind/config.toml` and `./.env` here too. The developer layer
is never just on or off, so its row always says which of four states
it is in -- see [section 8](#8-a-private-developer-config-file).)

## 10. Generating docs and templates

The same `defaults` dict that drives every layer can also *write about*
them. `App` has four `format_*` methods, one per direction:

| Method                | Purpose                                        |
| --------------------- | ---------------------------------------------- |
| `format_invocation()` | Reproduce a resolved configuration             |
| `format_env()`        | Generate an environment configuration template |
| `format_toml()`       | Generate a TOML configuration template         |
| `format_cli()`        | Generate a CLI/documentation template          |

`format_invocation()` ([section 5](#5-debugging-and-documentation---print-invocation)) takes a *resolved* settings dict and
prints the command line that reproduces it. The other three take
nothing: they render every setting's name in one layer next to its
default value -- ready to paste into a `.env` file, a config file, or
the README -- so there's no hand-written example config to drift out
of date the next time a setting is added:

```
                    defaults
                       │
                       ▼
                   inference
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
       ENV            TOML           CLI
        │              │              │
        ▼              ▼              ▼
   format_env()  format_toml()   format_cli()
```

With `remind`'s `DEFAULTS` from [section 2](#2-more-settings-and-where-each-layer-actually-applies):

```python
print(app.format_env())
```

```
# REMIND_MESSAGE=
REMIND_DELAY=0
# REMIND_CHANNEL=
REMIND_REPEAT=false
REMIND_RETRIES=3
```

```python
print(app.format_toml())
```

```
[remind]
# message =
delay = 0
# channel =
repeat = false
retries = 3
```

```python
print(app.format_cli())
```

```
--message <MESSAGE> (default: none)
--delay <DELAY>     (default: 0)
--channel <CHANNEL> (default: none)
--repeat            (default: false)
--retries <RETRIES> (default: 3)
```

A few things worth knowing:

- **Names come from the same place as everywhere else.** The env var
  names are `resolved_env_vars` (so an `env_vars=` override shows up),
  the TOML header is the app's `[default_table]` (pass `table="mom"` or
  `table=["remind", "mom"]` for another, or `header=False` for just the
  key lines), and the CLI lines are exactly the flags `add_arguments`
  adds -- a bool is a bare flag, everything else shows its `<METAVAR>`
  (pass the same `overrides=` you gave `add_arguments` if you renamed
  one).
- **No default means a placeholder.** A setting that starts out unset
  (`opt(str)` and friends) is a commented-out `# NAME=` / `# key =`
  line in the env and TOML templates -- fill it in and uncomment it --
  and `(default: none)` in the CLI reference.
- **The output is real syntax, and round-trips.** `format_env()` is
  valid `.env` syntax (a value is quoted only when it has to be) and
  `format_toml()` is valid TOML with native values (`3`, `false`,
  `["a", "b"]`). Write either to a file and the layer reads back
  exactly the defaults.
- **Custom formatters are respected.** A setting with a `formatters=`
  entry ([section 3](#3-when-inference-isnt-quite-enough-casters-and-formatters)) renders through it, so `delay = "2h"`-style
  settings show the text their caster actually expects. Nothing else
  needs a formatter: unlike `format_invocation()`, these never raise
  for a type inference doesn't know.
- **Show the *effective* default when it differs.** If your app
  substitutes a fallback after `resolve()` (an `opt(str)` that becomes
  a hardcoded constant when still `None`), pass
  `defaults={"channel": "slack"}` and the templates show that instead
  -- merged over `defaults`, for this call only. `skip=` leaves
  settings out, same as `format_invocation()`.

## 11. Putting it together

The full `remind` from every section above, minus the duration
caster/formatter (all four still inferred where they aren't shown):

```python
import argparse
import conclude

DEFAULTS = {
    "message": conclude.opt(str),
    "delay": 0,
    "channel": conclude.opt(str),
    "repeat": False,
    "retries": 3,
}
app = conclude.App(
    "remind",
    DEFAULTS,
    dotenv_path=conclude.AUTO,
    config_system_path=conclude.AUTO,
    pyproject_path=conclude.AUTO,
)

parser = argparse.ArgumentParser(
    prog="remind",
    epilog=app.describe_sources(),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("recipient", nargs="?", default=None)
parser.add_argument("--config", default=None, metavar="PARENT[.CHILD]")
app.add_arguments(parser)
app.add_print_invocation_argument(parser)
namespace = parser.parse_args()
cli = {k: v for k, v in vars(namespace).items() if v is not None}

table_path = app.resolve_config_table(config_value=cli.get("config"), shorthand_value=namespace.recipient)
settings = app.resolve(
    cli,
    config_file=app.load_config_files(table_path),
    developer=app.load_developer_config(table_path),
)

if namespace.print_invocation:
    print(app.format_invocation(settings, prog="remind", skip={"recipient"}))
else:
    send_reminder(**settings)  # your own code from here
```
