# @tanakapayam/conclude

The TypeScript / Node.js implementation of [conclude](https://github.com/tanakapayam/conclude#readme).

A setting that can come from a flag, an environment variable, or a config
file usually gets written down three times: a flag, an environment variable,
and a config-file key -- each with its own name, its own type conversion, and
its own copy of the default. conclude has you write it once: declare your
settings as defaults, and it derives the rest and resolves every layer into one
typed settings object.

> **Status: early (0.x).** The package is complete enough to use and passes every
> conformance fixture in
> [`spec/`](https://github.com/tanakapayam/conclude/blob/main/spec/README.md) -- the same fixtures the
> [Python package](https://pypi.org/project/conclude/) passes -- but the API may still
> change between minor versions. The one Python feature not ported yet is
> `--print-invocation`. (0.1.0 was published without its build output and cannot be
> imported; use 0.1.1 or newer.)

```
npm install @tanakapayam/conclude
npm install ignore   # optional: only for the gitignore check (developer file, strict .env)
```

```ts
import { defineConfig, int, list } from "@tanakapayam/conclude";

const config = defineConfig({
  name: "myapp",
  settings: {
    host: "localhost",
    port: int(8080),
    debug: false,
    tags: list(), // unset by default, but still a list when set
  },
});

const { cli } = config.parseArgs();
console.log(config.resolve({ cli }));
```

```
$ MYAPP_PORT=9000 node app.ts --debug --tags a,b
{ host: 'localhost', port: 9000, debug: true, tags: [ 'a', 'b' ] }
```

That one declaration gave you the flags (`--host`, `--port`, `--debug`,
`--tags`), the environment variables (`MYAPP_HOST`, `MYAPP_PORT`, ...), the
config-file keys (a `[myapp]` table in `~/.config/myapp/config.toml` or
`./.config.toml`), a caster for each, and a fully typed result -- `settings.port`
is a `number`, `settings.tags` a `string[] | null`.

## The layers

```
defaults < system < user < project < env < developer < CLI
```

The user and project config files are on by default; the system file, a `.env`
fallback, and a private, gitignored developer file that beats the environment
are opt-in. `config.describeSources()` reports which are in play, and
`config.formatEnv()`, `formatToml()` and `formatCli()` generate templates from
the same declaration.

## Documentation

- [Guide](https://github.com/tanakapayam/conclude/blob/main/docs/node/guide.md) -- builds a small CLI, `remind`, one idea at a time.
- [Reference](https://github.com/tanakapayam/conclude/blob/main/docs/node/reference.md) -- every option, method and function.
- [The concept](https://github.com/tanakapayam/conclude/blob/main/docs/concept.md) -- the language-neutral behavior this package follows.
- [Changelog](https://github.com/tanakapayam/conclude/blob/main/node/CHANGELOG.md).

## Requirements

Node.js 22.12 or newer (an ESM package that `require()` can also load). One
runtime dependency, `smol-toml`, for TOML. The gitignore check (the developer
file, or a `.env` you require to be gitignored) uses the optional peer
dependency `ignore`; without it those features report a setup error rather than
silently skipping the check.

## Development

```
npm ci
npm run typecheck
npm test             # the shared conformance fixtures, the API tests, and the docs
npm run build
npm run smoke        # packs the package and checks the tarball from the outside
```

Sources are TypeScript run directly by Node's type stripping, so they use only
erasable syntax (no enums, namespaces or parameter properties).

## License

MIT.
