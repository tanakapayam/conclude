# conclude

Write your settings down once, as a set of defaults, and derive everything
else -- the environment variable, the config-file key, the CLI flag, the
caster, and layered resolution across every source -- once per language.
The idea, precedence rules and file formats are defined a single time, in
[the concept document](https://github.com/tanakapayam/conclude/blob/main/docs/concept.md);
each language below is a separate package that implements it and is held to
the same [shared conformance fixtures](https://github.com/tanakapayam/conclude/blob/main/spec/README.md).

| | |
| --- | --- |
| **Python** | [`conclude` on PyPI](https://pypi.org/project/conclude/) -- [source](python/), [guide](https://github.com/tanakapayam/conclude/blob/main/docs/python/guide.md), [reference](https://github.com/tanakapayam/conclude/blob/main/docs/python/reference.md) |
| **Node.js / TypeScript** | [`@tanakapayam/conclude` on npm](https://www.npmjs.com/package/@tanakapayam/conclude) -- [source](node/), [guide](https://github.com/tanakapayam/conclude/blob/main/docs/node/guide.md), [reference](https://github.com/tanakapayam/conclude/blob/main/docs/node/reference.md) |

Each package has its own README with an install command and a quickstart --
start there for the language you're using. This top-level page is about the
project as a whole.

## Layout

```
conclude/
├── docs/
│   ├── concept.md      # the idea, precedence rules and formats -- language-neutral
│   ├── python/          # guide, reference, comparison -- Python-specific
│   └── node/            # guide, reference -- Node-specific
├── spec/                # shared conformance fixtures every implementation passes
├── python/               # the Python package (its own README, CHANGELOG, RELEASING.md)
├── node/                 # the Node.js / TypeScript package (ditto)
└── .github/workflows/    # python-ci.yml / python-publish.yml, node-ci.yml / node-publish.yml
```

Each language directory is self-contained: its own dependency lockfile, its
own test runner, its own release process (`<language>/RELEASING.md`), and its
own CI and publish workflows (`.github/workflows/<language>-*.yml`). The
things that are genuinely shared -- what conclude *is*, and the fixtures that
pin its behavior down -- live at the top level instead of inside any one
package.

## Contributing

Adding a setting, a layer, or changing behavior starts in
[`docs/concept.md`](https://github.com/tanakapayam/conclude/blob/main/docs/concept.md)
and [`spec/`](https://github.com/tanakapayam/conclude/blob/main/spec/README.md):
say what changed there first, then bring every language's implementation and
tests up to it. A change that only touches one language's own API (not its
behavior) stays inside that language's directory.

## License

MIT -- see [LICENSE](https://github.com/tanakapayam/conclude/blob/main/LICENSE).
