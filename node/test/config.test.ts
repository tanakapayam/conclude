/** The high-level API: defineConfig and everything hanging off it. */

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, describe, test } from "node:test";

import {
  AUTO,
  CastError,
  ConfigFileError,
  ConfigTableError,
  bool,
  defineConfig,
  float,
  int,
  list,
  str,
  toCanonicalKey,
} from "../src/index.ts";
import type { ConfigOptions, Declarations } from "../src/index.ts";

const scratch: string[] = [];
function tempDir(): string {
  const path = mkdtempSync(join(tmpdir(), "conclude-config-"));
  scratch.push(path);
  return path;
}
after(() => {
  for (const path of scratch) rmSync(path, { recursive: true, force: true });
});

function write(root: string, relative: string, content: string): string {
  const path = join(root, relative);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, "utf8");
  return path;
}

/** A working tree where `.git` exists and the given names are gitignored. */
function repo(files: Record<string, string> = {}, ignored = ""): string {
  const root = tempDir();
  mkdirSync(join(root, ".git"));
  if (ignored) write(root, ".gitignore", ignored);
  for (const [name, content] of Object.entries(files)) write(root, name, content);
  return root;
}

/** Options with every file source switched off, so a test opts in to exactly what it exercises. */
function isolated<S extends Declarations>(
  name: string,
  settings: S,
  extra: Partial<ConfigOptions<S>> = {},
): ConfigOptions<S> {
  return { name, settings, userConfigPath: null, projectConfigPath: null, ...extra } as ConfigOptions<S>;
}

const SETTINGS = {
  host: "localhost",
  port: int(8080),
  debug: false,
  tags: list(),
  ratio: float(0.5),
  filterCol: str(),
};

// --- declaring settings ----------------------------------------------------------------

describe("declaring settings", () => {
  test("resolved values are typed from the declarations", () => {
    const config = defineConfig(isolated("t", SETTINGS));
    const resolved = config.resolve({ environ: {} });
    const host: string = resolved.host;
    const port: number = resolved.port;
    const debug: boolean = resolved.debug;
    const tags: string[] | null = resolved.tags;
    const filterCol: string | null = resolved.filterCol;
    assert.deepEqual(
      { host, port, debug, tags, ratio: resolved.ratio, filterCol },
      { host: "localhost", port: 8080, debug: false, tags: null, ratio: 0.5, filterCol: null },
    );
    // @ts-expect-error -- a setting that was never declared
    void resolved.nope;
    // @ts-expect-error -- host is a string, never null
    const notNull: null = resolved.host;
    void notNull;
  });

  test("a bare number is a compile error and a runtime error", () => {
    assert.throws(
      // @ts-expect-error -- numbers must say int() or float()
      () => defineConfig({ name: "t", settings: { port: 8080 } }),
      /declare numbers with int\(\) or float\(\), e\.g\. port: int\(8080\)/,
    );
  });

  test("helpers with no default declare an unset setting", () => {
    const config = defineConfig(isolated("t", { a: bool(), b: int(), c: float(), d: str(), e: list() }));
    assert.deepEqual(config.resolve({ environ: {} }), { a: null, b: null, c: null, d: null, e: null });
  });

  test("helpers validate their defaults", () => {
    assert.throws(() => int(Number.NaN), TypeError);
    assert.throws(() => float(Number.POSITIVE_INFINITY), TypeError);
    assert.throws(() => bool("yes" as never), TypeError);
    assert.throws(() => str(3 as never), TypeError);
    assert.throws(() => list([1] as never), TypeError);
  });

  test("keys are mapped to snake_case for files, the environment and flags", () => {
    assert.equal(toCanonicalKey("filterCol"), "filter_col");
    assert.equal(toCanonicalKey("apiURL"), "api_url");
    assert.equal(toCanonicalKey("HTTPServer"), "http_server");
    assert.equal(toCanonicalKey("already_snake"), "already_snake");
    assert.equal(toCanonicalKey("x1Y"), "x1_y");
  });

  test("two keys that map to the same name are rejected", () => {
    assert.throws(() => defineConfig({ name: "t", settings: { fooBar: "a", foo_bar: "b" } }), /both "foo_bar"/);
  });

  test("a key must be an identifier", () => {
    assert.throws(() => defineConfig({ name: "t", settings: { "not-valid": "a" } }), /must be an identifier/);
  });

  test("the name must not be empty, and envVars must name declared settings", () => {
    assert.throws(() => defineConfig({ name: "", settings: {} }), /name must be/);
    assert.throws(
      // @ts-expect-error -- "missing" is not a declared setting
      () => defineConfig({ name: "t", settings: { a: "x" }, envVars: { missing: "X" } }),
      /not a declared setting/,
    );
  });

  test("envVarNames shows the variable each setting reads", () => {
    const config = defineConfig(isolated("my-app", { filterCol: "x", port: int(1) }, { envVars: { port: "PORT" } }));
    assert.deepEqual(config.envVarNames, { filterCol: "MY_APP_FILTER_COL", port: "PORT" });
  });
});

// --- layers -----------------------------------------------------------------------------

describe("resolving", () => {
  test("the environment is read by derived name, cast, and beats a config file", () => {
    const root = tempDir();
    const project = write(root, ".config.toml", "[t]\nport = 1\nfilter_col = 'from-file'\n");
    const config = defineConfig(isolated("t", SETTINGS, { projectConfigPath: project, projectAuxPattern: null }));
    const environ = { T_PORT: "9000", T_DEBUG: "yes", T_TAGS: "a, b", T_FILTER_COL: undefined };
    assert.deepEqual(config.resolve({ environ }), {
      host: "localhost",
      port: 9000,
      debug: true,
      tags: ["a", "b"],
      ratio: 0.5,
      filterCol: "from-file",
    });
  });

  test("the CLI beats everything, keyed by the declared name", () => {
    const config = defineConfig(isolated("t", SETTINGS));
    const resolved = config.resolve({ environ: { T_PORT: "9000" }, cli: { port: 7, filterCol: "x", host: undefined } });
    assert.equal(resolved.port, 7);
    assert.equal(resolved.filterCol, "x");
    assert.equal(resolved.host, "localhost");
  });

  test("config files are keyed by the snake_case name, and merge system < user < project < siblings", () => {
    const root = tempDir();
    const system = write(root, "system.toml", "[t]\nfilter_col = 'sys'\nport = 2\n");
    const user = write(root, "user.toml", "[t]\nport = 3\n");
    const project = write(root, "proj/.config.toml", "[t]\nport = 4\n");
    write(root, "proj/.config.b.toml", "[t]\nratio = 0.25\n");
    const config = defineConfig({
      name: "t",
      settings: SETTINGS,
      systemConfigPath: system,
      userConfigPath: user,
      projectConfigPath: project,
    });
    const resolved = config.resolve({ environ: {} });
    assert.equal(resolved.filterCol, "sys");
    assert.equal(resolved.port, 4);
    assert.equal(resolved.ratio, 0.25);
  });

  test("the projectAuxPattern can switch siblings off", () => {
    const root = tempDir();
    const project = write(root, ".config.toml", "[t]\nport = 4\n");
    write(root, ".config.b.toml", "[t]\nport = 5\n");
    assert.equal(defineConfig(isolated("t", SETTINGS, { projectConfigPath: project })).resolve({ environ: {} }).port, 5);
    const off = defineConfig(isolated("t", SETTINGS, { projectConfigPath: project, projectAuxPattern: null }));
    assert.equal(off.resolve({ environ: {} }).port, 4);
  });

  test("a positional shorthand picks a table, and an explicit selection wins", () => {
    const root = tempDir();
    const project = write(root, ".config.toml", "[t]\nport = 1\n[mom]\nport = 2\n[t.deck]\nport = 3\n");
    const config = defineConfig(isolated("t", SETTINGS, { projectConfigPath: project, projectAuxPattern: null }));
    assert.equal(config.resolve({ environ: {} }).port, 1);
    assert.equal(config.resolve({ environ: {}, shorthand: "mom" }).port, 2);
    assert.equal(config.resolve({ environ: {}, shorthand: "deck" }).port, 3);
    assert.equal(config.resolve({ environ: {}, shorthand: "mom", configValue: "t.deck" }).port, 3);
    assert.throws(() => config.resolve({ environ: {}, configValue: "a..b" }), ConfigTableError);
  });

  test("a cast failure names the problem", () => {
    const config = defineConfig(isolated("t", SETTINGS));
    assert.throws(() => config.resolve({ environ: { T_PORT: "abc" } }), CastError);
  });

  test("a malformed config file is a loud error", () => {
    const root = tempDir();
    const project = write(root, ".config.toml", "not [valid");
    const config = defineConfig(isolated("t", SETTINGS, { projectConfigPath: project }));
    assert.throws(() => config.resolve({ environ: {} }), ConfigFileError);
  });

  test("the user and project files are on by default, at the conventional places", () => {
    const config = defineConfig({ name: "myapp", settings: SETTINGS });
    const rows = config.describeSources({}).split("\n");
    assert.equal(rows[2], `  user config       ${join(homedir(), ".config", "myapp", "config.toml")}`);
    assert.equal(rows[3], "  project config    .config.toml, .config.*.toml");
    assert.equal(defineConfig({ name: "myapp", settings: SETTINGS, userConfigPath: AUTO }).describeSources({}), config.describeSources({}));
  });
});

// --- the .env fallback ---------------------------------------------------------------------

describe("the .env fallback", () => {
  test("it is off by default and sits beneath the real environment", () => {
    const root = tempDir();
    const dotenv = write(root, ".env", "T_PORT=1\nT_HOST=from-dotenv\n");
    assert.equal(defineConfig(isolated("t", SETTINGS)).resolve({ environ: {} }).host, "localhost");
    const config = defineConfig(isolated("t", SETTINGS, { dotenvPath: dotenv }));
    const resolved = config.resolve({ environ: { T_PORT: "9000" } });
    assert.equal(resolved.host, "from-dotenv");
    assert.equal(resolved.port, 9000);
  });

  test("required to be gitignored, it is read only when it is", () => {
    const ignored = repo({ ".env": "T_HOST=secret\n" }, ".env\n");
    const notIgnored = repo({ ".env": "T_HOST=secret\n" }, "other\n");
    const active = defineConfig(isolated("t", SETTINGS, { dotenvPath: join(ignored, ".env"), dotenvRequireGitignored: true }));
    const inactive = defineConfig(isolated("t", SETTINGS, { dotenvPath: join(notIgnored, ".env"), dotenvRequireGitignored: true }));
    assert.equal(active.resolve({ environ: {} }).host, "secret");
    assert.equal(inactive.resolve({ environ: {} }).host, "localhost");
    assert.equal(active.dotenvStatus().state, "active");
    assert.equal(inactive.dotenvStatus().reason, "not covered by .gitignore");
    assert.match(inactive.describeSources({}), /\.env file {5}.*\.env -- inactive \(not covered by \.gitignore\)/);
  });
});

// --- the developer layer ------------------------------------------------------------------

function developerRepo(developerFile: string, fileContent: string, ignored = ""): { root: string; manifest: string } {
  const root = repo(
    { "package.json": JSON.stringify({ name: "x", conclude: { developer: { config: developerFile } } }), [developerFile]: fileContent },
    ignored,
  );
  return { root, manifest: join(root, "package.json") };
}

describe("the developer layer", () => {
  test("it is off unless the app opts in", () => {
    const { root } = developerRepo(".developer.toml", "[t]\nport = 6\n", ".developer.toml\n");
    const config = defineConfig(isolated("t", SETTINGS));
    assert.equal(config.developerStatus({}).state, "not opted in");
    assert.equal(config.resolve({ environ: {} }).port, 8080);
    void root;
  });

  test("a gitignored TOML file beats the environment and loses to the CLI", () => {
    const { manifest } = developerRepo(".developer.toml", "[t]\nport = 6\nfilter_col = 'dev'\n", ".developer.toml\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest }));
    assert.equal(config.developerStatus({}).state, "configured, active");
    const environ = { T_PORT: "5", T_FILTER_COL: "env" };
    const resolved = config.resolve({ environ });
    assert.equal(resolved.port, 6);
    assert.equal(resolved.filterCol, "dev");
    assert.equal(config.resolve({ environ, cli: { port: 7 } }).port, 7);
  });

  test("a dotenv file is keyed by the environment variable names", () => {
    const { manifest } = developerRepo(".env.local", "T_PORT=8\nUNRELATED=1\n", ".env.local\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest }));
    assert.equal(config.developerStatus({}).format, "dotenv");
    assert.equal(config.resolve({ environ: { T_PORT: "5" } }).port, 8);
  });

  test("a dotenv developer file can use unprefixed names via envVars", () => {
    const { manifest } = developerRepo(".env.local", "PORT=8\nT_PORT=1\n", ".env.local\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest, envVars: { port: "PORT" } }));
    assert.equal(config.resolve({ environ: {} }).port, 8);
  });

  test("it stays inactive, with the reason, unless the file is gitignored", () => {
    const { manifest } = developerRepo(".developer.toml", "[t]\nport = 6\n", "other\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest }));
    const status = config.developerStatus({});
    assert.equal(status.state, "configured, inactive");
    assert.equal(status.reason, "not covered by .gitignore");
    assert.equal(config.resolve({ environ: {} }).port, 8080);
  });

  test("the kill switch is <NAME>_DEVELOPER_CONFIG", () => {
    const { manifest } = developerRepo(".developer.toml", "[t]\nport = 6\n", ".developer.toml\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest }));
    const environ = { T_DEVELOPER_CONFIG: "off" };
    assert.equal(config.developerStatus(environ).reason, "disabled by T_DEVELOPER_CONFIG=off");
    assert.equal(config.resolve({ environ }).port, 8080);
  });

  test("the manifest's own problems are reported quietly", () => {
    const root = tempDir();
    const options = (path: string) => defineConfig(isolated("t", SETTINGS, { manifestPath: path }));
    assert.match(options(join(root, "none.json")).developerStatus({}).reason ?? "", /^no .*none\.json$/);
    const bad = write(root, "bad.json", "{ not json");
    assert.match(options(bad).developerStatus({}).reason ?? "", /is not readable JSON$/);
    const plain = write(root, "plain.json", "{}");
    assert.match(options(plain).developerStatus({}).reason ?? "", /^no conclude\.developer\.config in /);
    const wrong = write(root, "wrong.json", JSON.stringify({ conclude: { developer: { config: 5 } } }));
    assert.equal(options(wrong).developerStatus({}).reason, "conclude.developer.config must be a non-empty string");
    for (const path of [join(root, "none.json"), bad, plain, wrong]) {
      assert.equal(options(path).developerStatus({}).state, "not configured");
      assert.equal(options(path).resolve({ environ: {} }).port, 8080); // quiet
    }
  });

  test("an active file that is not valid TOML names itself", () => {
    const { manifest } = developerRepo(".developer.toml", "not [valid", ".developer.toml\n");
    const config = defineConfig(isolated("t", SETTINGS, { manifestPath: manifest }));
    assert.throws(() => config.resolve({ environ: {} }), (error: unknown) => {
      assert.ok(error instanceof ConfigFileError);
      assert.match(error.message, /^developer config file .*\.developer\.toml/);
      return true;
    });
  });
});

// --- describing sources -------------------------------------------------------------------

describe("describeSources", () => {
  test("lists every source, lowest priority first, in aligned columns", () => {
    const { manifest, root } = developerRepo(".developer.toml", "", ".developer.toml\n");
    const config = defineConfig({
      name: "t",
      settings: SETTINGS,
      systemConfigPath: "/etc/t/config.toml",
      userConfigPath: "/home/u/.config/t/config.toml",
      projectConfigPath: ".config.toml",
      dotenvPath: ".env",
      manifestPath: manifest,
    });
    assert.equal(
      config.describeSources({}),
      [
        "config sources:",
        "  system config     /etc/t/config.toml",
        "  user config       /home/u/.config/t/config.toml",
        "  project config    .config.toml, .config.*.toml",
        "  .env file         .env",
        `  developer config  ${join(root, ".developer.toml")} -- configured, active`,
      ].join("\n"),
    );
  });

  test("shows what is switched off", () => {
    const config = defineConfig(isolated("t", SETTINGS));
    assert.equal(
      config.describeSources({}),
      [
        "config sources:",
        "  system config     disabled",
        "  user config       disabled",
        "  project config    disabled",
        "  .env file         disabled",
        "  developer config  not opted in",
      ].join("\n"),
    );
  });
});

// --- templates --------------------------------------------------------------------------------

describe("templates", () => {
  const config = defineConfig(isolated("myapp", { filterCol: "x", port: int(8080), debug: false, tags: list() }));

  test("names follow the snake_case rule", () => {
    assert.equal(config.formatEnv(), "MYAPP_FILTER_COL=x\nMYAPP_PORT=8080\nMYAPP_DEBUG=false\n# MYAPP_TAGS=");
    assert.equal(config.formatToml(), '[myapp]\nfilter_col = "x"\nport = 8080\ndebug = false\n# tags =');
    assert.equal(
      config.formatCli(),
      [
        "--filter-col <FILTER_COL> (default: x)",
        "--port <PORT>             (default: 8080)",
        "--debug                   (default: false)",
        "--tags <TAGS>             (default: none)",
      ].join("\n"),
    );
  });

  test("options use the declared names", () => {
    assert.equal(config.formatEnv({ skip: ["filterCol", "tags"], defaults: { port: 1 } }), "MYAPP_PORT=1\nMYAPP_DEBUG=false");
    assert.equal(config.formatToml({ skip: ["filterCol", "port", "debug", "tags"], table: ["myapp", "deck"] }), "[myapp.deck]");
    assert.equal(config.formatToml({ header: false, skip: ["port", "debug", "tags"] }), 'filter_col = "x"');
    assert.equal(
      config.formatCli({ skip: ["port", "debug", "tags"], metavars: { filterCol: "COL" } }),
      "--filter-col <COL> (default: x)",
    );
  });

  test("the TOML header defaults to defaultTable", () => {
    const custom = defineConfig(isolated("myapp", { a: "x" }, { defaultTable: "other" }));
    assert.equal(custom.formatToml(), '[other]\na = "x"');
  });
});

// --- the command line -------------------------------------------------------------------------

describe("the command line", () => {
  const config = defineConfig(isolated("t", { filterCol: "x", port: int(8080), debug: false }));

  test("cliOptions is the derived flags, in util.parseArgs shape", () => {
    assert.deepEqual(config.cliOptions(), {
      "filter-col": { type: "string" },
      port: { type: "string" },
      debug: { type: "boolean" },
    });
  });

  test("parseArgs maps flags back to the declared keys, and keeps positionals and extra options", () => {
    const parsed = config.parseArgs(["mom", "--filter-col", "a", "--debug", "--config", "t.deck"], {
      options: { config: { type: "string" } },
    });
    assert.deepEqual(parsed.cli, { filterCol: "a", debug: true });
    assert.deepEqual(parsed.positionals, ["mom"]);
    assert.equal(parsed.values["config"], "t.deck");
    const resolved = config.resolve({ environ: {}, cli: parsed.cli, shorthand: parsed.positionals[0] ?? null });
    assert.equal(resolved.filterCol, "a");
    assert.equal(resolved.debug, true);
  });

  test("flags that were not given are no opinion", () => {
    assert.deepEqual(config.parseArgs([]).cli, {});
    assert.equal(config.resolve({ environ: { T_PORT: "5" }, cli: config.parseArgs([]).cli }).port, 5);
  });

  test("an unknown flag is an error", () => {
    assert.throws(() => config.parseArgs(["--nope"]), { code: "ERR_PARSE_ARGS_UNKNOWN_OPTION" });
  });
});
