# conclude (Bash)

Declare your defaults once. Conclude derives the interfaces through which
those settings can be configured: the environment variable, the config-file
key, the CLI flag, the type cast, and layered resolution across every source.

This is the Bash implementation of [conclude](https://github.com/tanakapayam/conclude):
one file you `source` at the top of a script. It follows the same
[concept](https://github.com/tanakapayam/conclude/blob/main/docs/concept.md) as the
[Python](https://pypi.org/project/conclude/) and
[Node.js](https://www.npmjs.com/package/@tanakapayam/conclude) packages and passes
the same [shared conformance fixtures](https://github.com/tanakapayam/conclude/blob/main/spec/README.md).
It is not a line-by-line port: it is written the way a Bash library should
be, with no Python, Node, `jq` or `yq` anywhere in it.

## Requirements

- **Bash 5.3 or newer.** The file refuses to load on anything older.
- Coreutils, and `awk` (used only to parse a fractional or scientific-notation
  number, which Bash cannot do).
- `git`, only if you use the developer-config layer or a guarded `.env`
  (the "is this file gitignored?" check is `git check-ignore`).

## Install

Download the one file from a release and check it:

```sh
version=0.1.0
base=https://github.com/tanakapayam/conclude/releases/download/bash-v$version
curl -fsSLO "$base/conclude.sh"
curl -fsSLO "$base/conclude.sh.sha256"
sha256sum -c conclude.sh.sha256
```

(Use the versioned URL, not `releases/latest`: "latest" is the newest release of
the whole repository, whichever language it was for.)

Put it next to your script, or in a directory of your choosing, and source it:

```sh
source ./conclude.sh
# or, with Bash 5.3's `source -p`, from a directory you keep libraries in:
source -p "$HOME/.local/lib/bash" conclude.sh
```

## Quickstart

```bash
#!/usr/bin/env bash
set -euo pipefail
source ./conclude.sh

conclude_init myapp
conclude_define myapp host str localhost
conclude_define myapp port int 8080
conclude_define myapp debug bool false
conclude_define myapp tags list "a,b"
conclude_define myapp filter_col str          # no default: unset until given

conclude_resolve myapp -- "$@"                # CLI > env > config > defaults

echo "listening on ${CONCLUDE[host]}:${CONCLUDE[port]}"
[[ ${CONCLUDE[debug]} == true ]] && echo "debug is on"
mapfile -t tags <<<"${CONCLUDE[tags]}"        # a list is one item per line
```

Every setting is now available three ways: in the `CONCLUDE` associative array,
as an exported variable (`MYAPP_HOST`, `MYAPP_PORT`, ...), and, from each
`conclude_define`, as all of these for free:

| Setting `filter_col` of app `myapp` | Derived name |
| ----------------------------------- | ------------ |
| CLI flag                            | `--filter-col VALUE` or `--filter-col=VALUE` (a bare `--debug` for a bool, `--no-debug` to turn it off) |
| Environment variable                | `MYAPP_FILTER_COL` |
| Config-file key                     | `filter_col` under `[myapp]` |

Precedence, lowest to highest: **defaults, user config
(`$XDG_CONFIG_HOME/myapp/config.toml`, falling back to
`~/.config/myapp/config.toml`), project config (`./.config.toml`, then its
`.config.*.toml` siblings in name order), environment, developer config, CLI.**

Then generate what you would otherwise write by hand:

```bash
conclude_format_env  myapp out; printf '%s\n' "$out"    # MYAPP_HOST=localhost ...
conclude_format_toml myapp out; printf '%s\n' "$out"    # [myapp] / host = "localhost" ...
conclude_format_cli  myapp out; printf '%s\n' "$out"    # --host <HOST>  (default: localhost) ...
conclude_describe_sources myapp out --user "$HOME/.config/myapp/config.toml"
```

## Things worth knowing before you rely on it

- **A list is a comma-separated string going in and one item per line coming
  out.** An empty list and an unset one are both `""`.
- **`conclude_resolve` exports every setting.** Calling it a second time in the
  same shell reads the first call's values back as its environment layer.
- **Config files use a deliberately small TOML subset**: `[table]` headers,
  and `key = value` where the value is a quoted string, `true`/`false`, or a
  number. Anything else (arrays, inline tables, dates, multi-line strings)
  anywhere in the file, even under a key you never declared, makes the file
  malformed and the resolve fail rather than be silently misread.
- **Values are captured with `$(...)`, which drops trailing newlines.** A
  setting whose value legitimately ends in a newline will lose it if you
  capture it that way; read it from `CONCLUDE` directly.
- Locale-independent by construction: the library forces `LC_CTYPE=C.UTF-8`
  inside the functions that walk characters, so `café` is four characters
  whether or not your locale is UTF-8.
- **A personal control file**, `$XDG_CONFIG_HOME/conclude/control.toml`
  (falling back to `~/.config/conclude/control.toml`), can supply or override
  `--developer-file`'s path for every conclude-based Bash script on your
  machine -- see `conclude_resolve_developer_file` in the
  [reference](https://github.com/tanakapayam/conclude/blob/main/docs/bash/reference.md).
  It's only ever consulted once an app has already opted into the developer
  layer.

## Documentation

- [Guide](https://github.com/tanakapayam/conclude/blob/main/docs/bash/guide.md): how the layers, types, config files, the developer layer and the templates fit together.
- [Reference](https://github.com/tanakapayam/conclude/blob/main/docs/bash/reference.md): every function, its arguments and exit codes.
- [Concept](https://github.com/tanakapayam/conclude/blob/main/docs/concept.md): the language-neutral idea, precedence rules and formats.

## Development

```sh
cd bash
scripts/smoke.sh                # packaging safeguards on the one file
shellcheck src/conclude.sh
bats test/                      # needs bats-core and jq; reads ../spec/*.json
```

Releasing is described in [RELEASING.md](RELEASING.md).

## License

MIT -- see [LICENSE](LICENSE).
