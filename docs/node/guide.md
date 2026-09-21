# Guide (Node.js)

This guide builds one small tool, `remind`, from nothing up to a realistic
full-featured command, one idea per section. It is the TypeScript counterpart
of the [Python guide](../guide.md); the behavior underneath is the same and is
defined once in [the concept](../concept.md). For every function and option,
see the [reference](reference.md).

Blocks that start with `// run` are complete programs; the output shown under
each is what they print.

## 1. The bare minimum

`remind` is a reminder tool. You write down each setting once -- its name and
its starting value -- and `defineConfig` derives everything else:

```ts
// run
import { defineConfig, int, str } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: {
    message: str(),      // no default: starts out unset
    delay: int(0),       // minutes from now
    channel: "email",    // a string default
    repeat: false,       // a boolean default
    retries: int(3),
  },
});

const settings = config.resolve({
  environ: { REMIND_DELAY: "30", REMIND_MESSAGE: "stand up" },
});
console.log(settings);
```

```
{
  message: 'stand up',
  delay: 30,
  channel: 'email',
  repeat: false,
  retries: 3
}
```

`resolve()` reads the real environment (`process.env`) unless you hand it one,
as here. The result is typed from the declarations: `settings.delay` is a
`number`, `settings.channel` a `string`, `settings.message` a `string | null`.

A `boolean`, `string` or `string[]` default is enough on its own. Numbers are
the exception: JavaScript cannot tell `3` from `3.0`, so you say which you
mean with `int()` or `float()` (a bare `retries: 3` is a compile error). The
same helpers with no argument -- `str()`, `int()`, `list()`, `bool()` --
declare a setting of that type that starts out unset.

## 2. What was derived

The same declaration gave every layer its name for each setting. Keys are
written in `camelCase` in your code and become `snake_case` everywhere else, so
one config file or `.env` works for every implementation of conclude:

```ts
// run
import { defineConfig, int, str } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { message: str(), retryLimit: int(3), replyTo: str() },
});

console.log(config.envVarNames);
console.log(config.cliOptions());
```

```
{
  message: 'REMIND_MESSAGE',
  retryLimit: 'REMIND_RETRY_LIMIT',
  replyTo: 'REMIND_REPLY_TO'
}
{
  message: { type: 'string' },
  'retry-limit': { type: 'string' },
  'reply-to': { type: 'string' }
}
```

So `retryLimit` is the environment variable `REMIND_RETRY_LIMIT`, the config
key `retry_limit`, and the flag `--retry-limit`. Where the derived environment
variable is not what you want, name it: `envVars: { replyTo: "REPLY_TO" }`.

## 3. Layers

Every source has a fixed priority, lowest to highest:

```
defaults < system < user < project < env < developer < CLI
```

`resolve()` merges them, casting each value as it lands. The environment (and
the values `parseArgs` hands back) are text, and a value you build yourself may
already be a number, so `REMIND_RETRIES=5` and `retries: 5` both arrive as the
number `5`; an unparseable value (`REMIND_RETRIES=lots`) throws a `CastError`.
A layer with no opinion about a setting simply leaves it out.

```ts
// run
import { defineConfig, int } from "@tanakapayam/conclude";

const config = defineConfig({ name: "remind", settings: { retries: int(3) } });

console.log(config.resolve({ environ: {} }).retries);
console.log(config.resolve({ environ: { REMIND_RETRIES: "5" } }).retries);
console.log(config.resolve({ environ: { REMIND_RETRIES: "5" }, cli: { retries: 9 } }).retries);
```

```
3
5
9
```

## 4. Config files

The user file `~/.config/remind/config.toml` and the project file
`./.config.toml` are read automatically, along with any `./.config.*.toml`
siblings (sorted by name, each beating the project file). A setting lives in a
table named after the app:

```toml
# ./.config.toml
[remind]
channel = "slack"
retries = 5

[remind.work]
channel = "teams"
```

`[remind.work]` is a *child* table: it inherits everything in `[remind]` and
overrides what it sets. Pick one with an explicit selection -- say, from a
`--config` flag -- or with a positional shorthand, which is looked up as a table
name in the files themselves:

```ts
const settings = config.resolve({ shorthand: "work" });            // [remind.work]
const same = config.resolve({ configValue: "remind.work" });       // explicit
```

Only keys that a setting declares are read, a missing table contributes
nothing, and a file that is not valid TOML throws a `ConfigFileError` naming
it. Each file source can be moved or switched off:

```ts
defineConfig({
  name: "remind",
  settings: { channel: "email" },
  userConfigPath: "/srv/remind/user.toml", // or null to turn it off
  projectConfigPath: null,                 // off, and its siblings with it
  projectAuxPattern: null,                 // keep the project file, drop the siblings
});
```

A stray `.config.backup.toml` next to the project file silently joins the merge
-- that is what the sibling search does -- and project config is read from the
current directory, so a tool run inside a directory someone else controls (a
fresh clone, an unpacked download) reads *that* directory's files. Both are one
`null` away from off.

A machine-wide file is off by default: `systemConfigPath: AUTO` opts in to
`/etc/remind/config.toml`, the lowest-priority file.

## 5. The command line

conclude derives the flags but does not own your command line.
`config.parseArgs()` is a thin wrapper over Node's own `util.parseArgs`: the
derived flags, plus any options of your own, and it maps the values back to your
declared names:

```ts
// run
import { defineConfig, int } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { channel: "email", repeat: false, retries: int(3) },
});

const { cli, positionals, values } = config.parseArgs(
  ["work", "--repeat", "--retries", "5", "--config", "remind.work"],
  { options: { config: { type: "string" } } },
);
console.log(cli, positionals, values.config);

const settings = config.resolve({ environ: {}, cli, shorthand: positionals[0] ?? null });
console.log(settings.repeat, settings.retries);
```

```
{ repeat: true, retries: '5' } [ 'work' ] remind.work
true 5
```

A boolean flag is bare (`--repeat`); every other flag takes a value; a flag you
did not pass is no opinion, so the layer below decides. To use another parser
(commander, yargs, ...), take `config.cliOptions()` -- the derived flags in
`parseArgs`' shape -- or just build the `cli` object yourself.

## 6. A `.env` file

`.env` is an opt-in fallback beneath the real environment: a variable that is
actually set always wins, and the file supplies the rest. It is off by default
(committing a `.env` of non-secret local defaults is common; reading arbitrary
files for secrets should never happen by accident):

```ts
defineConfig({ name: "remind", settings: { channel: "email" }, dotenvPath: AUTO }); // ./.env
```

The dialect is deliberately small (see the [concept](../concept.md#8-the-env-file-dotenvjson)):
`NAME=value`, an optional `export`, `#` comments, single or double quotes
(double quotes decode `\n`, `\t`, `\r`, `\\` and `\"`), UTF-8 with an optional
byte-order mark. No multi-line values, inline comments, or `${VAR}` expansion.

If the file holds private values, require it to be gitignored:

```ts
defineConfig({ /* ... */ dotenvPath: AUTO, dotenvRequireGitignored: true });
```

Now `.env` is read only if it exists, sits in a git working tree, and is
ignored by it -- the same guard as the developer file (next section), needing
the same optional dependency (`npm install ignore`). Otherwise it is skipped
quietly, and `describeSources()` (section 8) says why. It gates *reading*, not
committing.

## 7. A private developer file

Environment variables are process-wide and leak between projects; a file whose
location the *project* decides does not. The developer layer is a private,
gitignored file that sits **above the environment**:

```json
// package.json (committed)
{
  "conclude": { "developer": { "config": ".developer.toml" } }
}
```

```
# .gitignore
.developer.toml
```

```toml
# .developer.toml (private)
[remind]
channel = "console"
```

```ts
defineConfig({ name: "remind", settings: { channel: "email" }, manifestPath: AUTO }); // ./package.json
```

Now `REMIND_CHANNEL=slack` in your shell no longer matters inside this project,
and `--channel email` still wins for a one-off. The file's format follows its
name: `.toml` is TOML with the same tables as any config file; anything else is
dotenv, keyed by the environment variable names -- so a `.env.local` can also
serve docker compose or direnv. Dotenv has no tables, and, unlike almost every
other reader of a `.env`-style file, this layer beats the real environment.

Because a file that beats the environment must never come from somewhere it
shouldn't (a fresh clone, a CI checkout, a deployed image), it is used only
when *all* of these hold: the app opted in, `package.json` names a file, the
`REMIND_DEVELOPER_CONFIG` kill switch is not `off`, the file exists, it is in a
git working tree, and git's ignore rules cover it. Every other case is
*quiet* -- no exception, no warning -- and `config.developerStatus()` says
which:

| State | Meaning |
| --- | --- |
| `not opted in` | the app never set `manifestPath` |
| `not configured` | opted in, but `package.json` names no file |
| `configured, inactive` | named, but a check failed; the reason says which |
| `configured, active` | read, and beating the environment |

Two things are setup errors rather than states, and throw: a missing `ignore`
package when the check needs it (a `SetupError`), and an active file that is not
valid TOML (a `ConfigFileError`). `developerStatus()` and `describeSources()`
never throw.

Set `REMIND_DEVELOPER_CONFIG=off` in a deployment to skip the file even if one
is sitting there (a `.dockerignore` entry is the other half of that).

## 8. Telling the user where settings come from

`describeSources()` lists every source, lowest priority first, for a `--help`
epilog:

```ts
// run
import { defineConfig } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { channel: "email" },
  userConfigPath: "/home/me/.config/remind/config.toml",
});

console.log(config.describeSources({}));
```

```
config sources:
  system config     disabled
  user config       /home/me/.config/remind/config.toml
  project config    .config.toml, .config.*.toml
  .env file         disabled
  developer config  not opted in
```

## 9. Templates and documentation

The same declaration writes its own reference material, so an example config
can never drift from the settings:

```ts
// run
import { defineConfig, int, str } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { message: str(), delay: int(0), channel: "email", repeat: false },
});

console.log(config.formatEnv());
console.log();
console.log(config.formatToml());
console.log();
console.log(config.formatCli());
```

```
# REMIND_MESSAGE=
REMIND_DELAY=0
REMIND_CHANNEL=email
REMIND_REPEAT=false

[remind]
# message =
delay = 0
channel = "email"
repeat = false

--message <MESSAGE> (default: none)
--delay <DELAY>     (default: 0)
--channel <CHANNEL> (default: email)
--repeat            (default: false)
```

An unset setting is a commented-out placeholder; `skip`, `defaults` (an
effective default that differs from the declared one), `table`, `header` and
`metavars` adjust the output. `formatEnv()` is also the skeleton for a
dotenv developer file, and `formatToml({ header: false })` for a TOML one.

## 10. Putting it together

```ts
import { AUTO, defineConfig, int, str } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { message: str(), delay: int(0), channel: "email", repeat: false, retries: int(3) },
  dotenvPath: AUTO,
  dotenvRequireGitignored: true,
  manifestPath: AUTO,
});

const { cli, positionals, values } = config.parseArgs(process.argv.slice(2), {
  options: { config: { type: "string" }, help: { type: "boolean", short: "h" } },
});
if (values.help) {
  console.log(`usage: remind [recipient] [options]\n\n${config.formatCli()}\n\n${config.describeSources()}`);
  process.exit(0);
}

const settings = config.resolve({
  cli,
  configValue: typeof values.config === "string" ? values.config : null,
  shorthand: positionals[0] ?? null,
});
```

## 11. Reproducing a run

`formatInvocation(resolved)` is the inverse of `resolve()`: given resolved
settings, it renders a standalone command line that gets back to them with no
environment variables, config files or shorthand -- handy for debugging a
confusing setup, or turning one into a copy-pasteable command:

```ts
// run
import { defineConfig, int, list, str } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "remind",
  settings: { message: str(), delay: int(0), channel: "email", repeat: false, tags: list() },
  userConfigPath: null,
  projectConfigPath: null,
});

const settings = config.resolve({
  environ: { REMIND_MESSAGE: "stand up", REMIND_DELAY: "30", REMIND_REPEAT: "yes" },
});
console.log(config.formatInvocation(settings, { prog: "remind" }));
```

```
remind --message='stand up' --delay=30 --repeat
```

A setting that equals its default is left out (omitting the flag already
reproduces it), and so is a boolean that is off and anything unset; values are
POSIX shell-quoted. `alwaysInclude` forces a setting that equals its default to
be written, `skip` leaves one out (it beats `alwaysInclude`), and
`compareDefaults` says what counts as a setting's default for this call -- for a
setting whose real default is substituted after `resolve()`.

The conventional way to expose it is a `--print-invocation` flag of your own:

```ts
const { cli, values } = config.parseArgs(process.argv.slice(2), {
  options: { "print-invocation": { type: "boolean" } },
});
const settings = config.resolve({ cli });
if (values["print-invocation"]) {
  console.log(config.formatInvocation(settings, { prog: "remind" }));
  process.exit(0);
}
```

A boolean whose *default* is `true` cannot be reproduced this way -- there is no
flag to turn a boolean off -- so give such a setting a flag of your own.
