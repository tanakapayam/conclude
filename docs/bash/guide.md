# conclude for Bash: guide

We'll build `remind`, a small command-line reminder tool, and grow it one
capability at a time. Everything below is a real transcript against the
library -- copy any of it into a script and it will do exactly what's shown.
For the shape of each function, see the [reference](reference.md); for the
idea itself, and the rules every language-conclude shares, see the
[concept document](../concept.md).

## 1. The bare minimum

```bash
#!/usr/bin/env bash
set -euo pipefail
source ./conclude.sh

conclude_init remind
conclude_define remind message str
conclude_define remind delay int 0

conclude_resolve remind -- "$@"

declare -p CONCLUDE
```

```console
$ ./remind.sh --message "Take out the trash" --delay 30
declare -A CONCLUDE=([message]="Take out the trash" [delay]="30" )
```

`conclude_init` starts an app. Each `conclude_define` adds one setting: a
key, a type, and an optional default -- `message` has none, so it's `""`
until something sets it. `conclude_resolve` does the rest: it reads `"$@"`
for `--message`/`--delay`, checks `MESSAGE`/`DELAY`... except it doesn't,
quite -- it checks `REMIND_MESSAGE` and `REMIND_DELAY`, because every
setting's env var is prefixed with the app's own name, so two conclude-based
tools in the same shell never collide. `CONCLUDE[delay]` is `"30"`, not `30`
-- everything in Bash is text, but `conclude_cast` has already checked that
it *parses* as an int.

## 2. More settings, and where each one comes from

```bash
conclude_define remind message str
conclude_define remind delay int 0
conclude_define remind channel str
conclude_define remind repeat bool false
conclude_define remind retries int 3

conclude_resolve remind -- "$@"
```

Five settings, four different sources at once:

```console
$ printf '[remind]\nretries = 5\n' > .config.toml
$ REMIND_CHANNEL=slack ./remind.sh --message "Stand up" --delay 5
message=Stand up
delay=5
channel=slack
repeat=false
retries=5
```

`message` and `delay` came from the command line, `channel` from the
environment, `retries` from `./.config.toml`, and `repeat` from its own
declared default -- nobody said anything about it. That's the whole point:
**defaults < user config < project config < environment < developer config
< CLI**, low to highest, and a setting only has to come from wherever it's
convenient for that particular run.

A `bool` is on with a bare flag and otherwise off -- there's no `--repeat
false`; leaving the flag out is how you get `false`. And two things that are
easy to get backwards: **an empty value is still an opinion.** `REMIND_DELAY=`
(set, but empty) casts to "unset" and overrides a config file's delay; a
`REMIND_DELAY` that was never set does not. And **every layer is cast, even
one that loses.** A stray `retries = "many"` sitting forgotten in a config
file fails the whole resolve even the day you finally pass `--retries 5` on
the command line -- conclude would rather you fix the file than wonder later
why a value it never showed you was silently ignored.

## 3. When a setting needs its own parsing

There's no hook here for a custom caster -- no per-key override the way the
Python and Node packages have. If `--delay` should also take `2h` or `30m`,
declare it `str` and do the arithmetic yourself, right after resolving:

```bash
cast_duration() {
  local text=$1
  [[ -z $text ]] && { printf ''; return 0; }
  if [[ $text == *h ]]; then printf '%d' "$(( ${text%h} * 60 ))"
  elif [[ $text == *m ]]; then printf '%d' "${text%m}"
  else printf '%d' "$text"
  fi
}

conclude_define remind delay str 0   # str: cast_duration does the real casting
conclude_resolve remind -- "$@"
CONCLUDE[delay]=$(cast_duration "${CONCLUDE[delay]}")
```

```console
$ ./remind.sh --message hi --delay 2h
delay in minutes: 120
$ ./remind.sh --message hi --delay 30m
delay in minutes: 30
```

It's one line, and it composes with every layer for free -- `2h` works
whether it came from the CLI, `REMIND_DELAY`, or a config file, because
`conclude_resolve` never knew `delay` was anything but text.

## 4. A positional shorthand, and a table per recipient

Real reminders go to people, and each person might want their own channel and
retry count without a `[remind.mom]`/`[remind.dana]` maze. `conclude`'s table
selection is built for exactly this, but in Bash it's a couple of lines you
write yourself rather than a constructor argument:

```bash
recipient=$1; shift

declare -a table
conclude_resolve_table_selection "" "$recipient" remind table \
  -- "$(cat .config.toml 2>/dev/null)"

declare -a table_opts=()
for part in "${table[@]}"; do table_opts+=(--table "$part"); done

conclude_resolve remind "${table_opts[@]}" -- "$@"
```

```console
$ printf '[mom]\nchannel = "sms"\nretries = 10\n' > .config.toml
$ ./remind.sh mom --message "Call Sunday"
message=Call Sunday
channel=sms
retries=10
$ ./remind.sh mom --message "Call Sunday" --channel email
message=Call Sunday
channel=email
retries=10
```

`mom` names a top-level `[mom]` table directly; if there were only a
`[remind.mom]`, the same shorthand would find that instead. Either way, a flag
on the actual command line still wins -- the table only supplies what nothing
more specific said.

## 5. Reproducing a run

Once a run is layered across four or five sources, "what did it actually
decide?" stops being obvious. `conclude_format_invocation` turns a resolved
run back into the command line that would reproduce it:

```bash
print_invocation=0
args=()
for a in "$@"; do
  if [[ $a == --print-invocation ]]; then print_invocation=1; else args+=("$a"); fi
done

conclude_resolve remind "${table_opts[@]}" -- "${args[@]}"

if ((print_invocation)); then
  conclude_format_invocation remind CONCLUDE out --prog remind
  echo "$out"
fi
```

```console
$ ./remind.sh mom --message="Call Sunday" --print-invocation
remind --message='Call Sunday' --channel=sms --retries=10
$ REMIND_CHANNEL=slack ./remind.sh mom --message="Call Sunday" --print-invocation
remind --message='Call Sunday' --channel=slack --retries=10
```

`channel` tracks whichever source actually won -- `sms` from the table in the
first run, `slack` from the environment in the second -- while `retries`
stays `10` either way, because nothing overrode the table for it. A setting
equal to its default, and an off `bool`, are never printed at all: this is
meant to be pasted somewhere as a record of the *decisions* a run made, not a
restatement of everything conclude knows about.

## 6. Local development: a `.env` file

`conclude_resolve` does not read a `.env` for you -- unlike the Python and
Node packages, where it's a constructor flag, here it's two lines, because
"parse it" and "let it win" are separably useful:

```bash
declare -A dotenv_vars=()
conclude_load_dotenv .env dotenv_vars
for name in "${!dotenv_vars[@]}"; do
  [[ -v $name ]] || export "${name}=${dotenv_vars[$name]}"
done

conclude_resolve remind -- "$@"
```

```console
$ printf 'REMIND_CHANNEL=slack\nREMIND_RETRIES=1\n' > .env
$ ./remind.sh --message hi
channel=slack
retries=1
$ REMIND_CHANNEL=console ./remind.sh --message hi     # a real export still wins
channel=console
retries=1
```

`conclude_load_dotenv` never `source`s the file -- a line like
`A=$(rm -rf ~)` is just text to it, the same as every other value. The
`[[ -v $name ]] ||` guard is what makes this a *fallback*: a `.env` value
only fills in a variable nothing has actually exported, so a real
`REMIND_CHANNEL` in your shell still wins, exactly as if `.env` weren't
there.

## 7. Machine-wide defaults: build the layer yourself

The system-config file (`/etc/remind/config.toml`) isn't wired into
`conclude_resolve` either. Reaching for it is rare enough, and the pieces to
build it are already public, so here they are used directly instead of
behind a flag:

```bash
declare -A types=() defaults=()
for key in message channel retries; do
  types[$key]=${_CONCLUDE_TYPES["remind:$key"]}
  [[ -v _CONCLUDE_DEFAULTS["remind:$key"] ]] && defaults[$key]=${_CONCLUDE_DEFAULTS["remind:$key"]}
done

declare -A system=(); conclude_load_config_file /etc/remind/config.toml system remind
declare -A user=();   conclude_load_config_file "$HOME/.config/remind/config.toml" user remind
declare -A env=()
for key in "${!types[@]}"; do
  name=$(conclude_env_var_name remind "$key")
  [[ -v $name ]] && env[$key]=${!name}
done

declare -A result=()
conclude_merge_layers types result defaults system user env
```

```console
$ cat /etc/remind/config.toml
[remind]
channel = "slack"
retries = 5
$ cat ~/.config/remind/config.toml
[remind]
retries = 2
$ ./remind.sh
message=
channel=slack
retries=2
```

`channel` falls all the way through to the machine-wide file since neither
`~/.config` nor the environment said anything; `retries` stops at the user
file. This is `conclude_resolve` with one layer added and the command line
left out entirely -- which is really the point of building it from pieces:
nothing here is special-cased, it's the same `conclude_merge_layers` call
`conclude_resolve` itself makes, just with a different guest list.

## 8. A private developer config file

The layer for a setting that should never reach version control -- your own
API token, a debug channel you don't want on every teammate's machine.
Because a file like that is only safe if it truly can't be committed, it
loads *only* while it passes a guard:

```bash
conclude_resolve remind --developer-file .remind.local.toml -- "$@"
```

```console
$ git init -q && echo '.remind.local.toml' > .gitignore
$ printf '[remind]\nchannel = "console"\n' > .remind.local.toml
$ REMIND_CHANNEL=slack ./remind.sh --message hi
channel=console
$ REMIND_CHANNEL=slack REMIND_DEVELOPER_CONFIG=off ./remind.sh --message hi
channel=slack
$ REMIND_CHANNEL=slack ./remind.sh --message hi --channel email
channel=email
```

The file beats a stray environment variable, `REMIND_DEVELOPER_CONFIG=off`
(or `0`/`false`/`no`) turns it off from anywhere, and the command line still
beats it regardless. If the file isn't gitignored, doesn't exist, or you're
not even inside a git repository, the layer is silently empty -- that's a
normal state (a fresh clone with no file yet), not something conclude warns
you about.

Unlike the Python package, there's no `pyproject.toml` lookup that finds this
file on its own -- `--developer-file` names it directly, every time. That's a
real, deliberate difference, not an oversight: the shared fixtures leave
*how* a file gets named up to each language, since "the ecosystem's manifest"
means something different everywhere, and Bash doesn't really have one.

## 9. A personal control file

Naming the file every time is fine for one tool, but if you write several
conclude-based scripts, you probably want to pick one name for your own
developer files and be done with it. `--developer-opt-in` says "I want the
developer layer, but I have no opinion about the path" -- which leaves it up
to a personal file, `~/.config/conclude/control.toml`:

```bash
conclude_resolve remind --developer-opt-in -- "$@"
```

```console
$ ./remind.sh --message hi      # no control.toml yet: falls back to .developer.toml
channel=
$ mkdir -p ~/.config/conclude
$ printf '[control.bash]\ndeveloper_file = ".remind.local.toml"\n' > ~/.config/conclude/control.toml
$ ./remind.sh --message hi
channel=console
```

`[control.bash]` is this one file's answer for every Bash-conclude script on
your machine -- `[control]` alone would do the same thing less specifically
(the two overlay exactly the way an app's own two-level config tables do).
By default this is only a *fallback*: an app that calls `--developer-file`
with its own path keeps that path regardless of what your control file says.
Setting `override = true` changes that -- your choice wins outright, even
over the app's:

```console
$ cat ~/.config/conclude/control.toml
[control.bash]
developer_file = ".app-choice.toml"
override = true
$ ./remind2.sh --message hi     # remind2.sh hardcodes --developer-file .remind.local.toml
channel=app-choice
```

One thing worth being deliberate about: `override` only ever decides *which*
file gets read, never *whether* the developer layer runs at all. A script
that calls plain `conclude_resolve remind -- "$@"` -- no `--developer-file`,
no `--developer-opt-in` -- never consults your control file, no matter what's
in it. Your personal settings can redirect a mechanism a script already opted
into; they can't switch one on behind its back.

## 10. Turning off a source, and telling the user

```bash
conclude_resolve remind --no-siblings -- "$@"
```

turns off the `.config.*.toml` siblings search next to the project file --
useful once you'd rather a team not accumulate five half-forgotten override
files. For the sources an app *does* check, `conclude_describe_sources`
writes them out as one block, meant for a `--help` epilogue:

```console
$ conclude_describe_sources remind out \
    --user "$HOME/.config/remind/config.toml" --project "$PWD/.config.toml"
$ echo "$out"
config sources:
  system config     disabled
  user config       /Users/payam/.config/remind/config.toml
  project config    /Users/payam/remind/.config.toml
  .env file         disabled
  developer config  not opted in
```

## 11. Generating the docs so they can't drift

Three more calls than you'd expect for a `.env.example`, a config template
and a `--help` listing, but every one of them is read straight off the same
`conclude_define` calls that drive resolution -- add a setting once, and all
three follow without being told to:

```console
$ conclude_format_env remind out;  echo "$out"
# REMIND_MESSAGE=
REMIND_DELAY=0
# REMIND_CHANNEL=
REMIND_REPEAT=false
REMIND_RETRIES=3

$ conclude_format_toml remind out; echo "$out"
[remind]
# message =
delay = 0
# channel =
repeat = false
retries = 3

$ conclude_format_cli remind out;  echo "$out"
--message <MESSAGE> (default: none)
--delay <DELAY>     (default: 0)
--channel <CHANNEL> (default: none)
--repeat            (default: false)
--retries <RETRIES> (default: 3)
```

A setting with no default -- `message`, `channel` -- comes out commented, so
copying the `.env` or TOML output gives a template to fill in, not a program
that silently runs with everything blank.

## 12. Help, for free -- and extending it

That last block is already most of a `--help` screen, so `conclude_resolve`
can assemble and print one itself -- opt in, since a tool with its own
positional arguments (like `remind`'s `RECIPIENT`) usually wants to say more
than the auto-generated part can:

```bash
conclude_resolve remind --help-flag \
  --help-usage "[options] [RECIPIENT]" \
  --help-before "remind: a command-line reminder tool." \
  --help-after "  RECIPIENT   who to remind (a config-table shorthand)" \
  --help-sources-args --user "$HOME/.config/remind/config.toml" \
  -- "$@"
status=$?
(( status == 2 )) && exit 0      # help was printed; nothing else ran
(( status != 0 )) && exit 1
```

```console
$ ./remind.sh --help
Usage: remind [options] [RECIPIENT]

remind: a command-line reminder tool.

Options:
--message <MESSAGE> (default: none)
--delay <DELAY>     (default: 0)
--channel <CHANNEL> (default: none)
--repeat            (default: false)
--retries <RETRIES> (default: 3)

  RECIPIENT   who to remind (a config-table shorthand)

config sources:
  system config     disabled
  user config       /home/payam/.config/remind/config.toml
  project config    disabled
  .env file         disabled
  developer config  not opted in
```

Until `--help-flag` is given, `-h`/`--help` mean nothing special -- an
unrecognized-argument error, same as any other typo -- so this never steals a
flag from a tool that wants `-h` to mean something of its own. `--help-flag`
is the convenience default; `conclude_format_help` underneath is the whole
mechanism, and it's just as usable directly, with the same `--before`/
`--after`/`--skip`/`--no-sources` options, for a caller that wants to parse
`-h` in its own loop, or print help somewhere other than stdout, or shape it
completely differently. Nothing here is the only way in.

## 13. Putting it together

```bash
#!/usr/bin/env bash
set -euo pipefail
source ./conclude.sh

conclude_init remind
conclude_define remind message str
conclude_define remind delay int 0
conclude_define remind channel str
conclude_define remind repeat bool false
conclude_define remind retries int 3

recipient=""
if [[ $# -gt 0 && $1 != --* && $1 != -h ]]; then
  recipient=$1
  shift
fi

print_invocation=0
args=()
for a in "$@"; do
  if [[ $a == --print-invocation ]]; then print_invocation=1; else args+=("$a"); fi
done

declare -a table
conclude_resolve_table_selection "" "$recipient" remind table \
  -- "$(cat .config.toml 2>/dev/null)"
declare -a table_opts=()
for part in "${table[@]}"; do table_opts+=(--table "$part"); done

conclude_resolve remind --help-flag \
  --help-usage "[options] [RECIPIENT]" \
  --help-before "remind: a command-line reminder tool." \
  "${table_opts[@]}" -- "${args[@]}"
status=$?
(( status == 2 )) && exit 0
(( status != 0 )) && exit 1

if ((print_invocation)); then
  conclude_format_invocation remind CONCLUDE out --prog remind
  echo "$out"
  exit 0
fi

echo "Reminding ${recipient:-you} on ${CONCLUDE[channel]:-the default channel}: ${CONCLUDE[message]}"
```

Fifteen lines of actual logic, five sources per setting, a table per
recipient, and a `--help` that can't fall out of sync with any of it --
because none of them are told about each other. They're all just reading the
same five `conclude_define` calls at the top.
