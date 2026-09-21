/**
 * Runs the language-neutral conformance fixtures in ../spec against this
 * implementation. Each block is a small adapter from a fixture file to the
 * TypeScript API; tests/test_spec.py does the same for the Python package.
 */

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, describe, test } from "node:test";

import {
  CastError,
  ConcludeError,
  ConfigFileError,
  ConfigTableError,
  cast,
  checkGuard,
  cliFlagName,
  configKeyName,
  envVarName,
  defineConfig,
  formatCli,
  formatEnv,
  formatInvocation,
  formatToml,
  loadConfigFiles,
  loadDotenv,
  matchesGitIgnoreRules,
  parseConfigTable,
  resolve,
  resolveConfigTable,
} from "../src/index.ts";
import type { Setting, SettingType, TemplateOptions } from "../src/index.ts";

const SPEC = new URL("../../spec/", import.meta.url);
const SPEC_VERSION = 1;

interface Fixture<Case> {
  spec_version: number;
  description: string;
  cases: Case[];
}

function load<Case>(name: string): Fixture<Case> {
  const fixture = JSON.parse(readFileSync(new URL(name, SPEC), "utf8")) as Fixture<Case>;
  assert.equal(fixture.spec_version, SPEC_VERSION, `${name} spec_version`);
  return fixture;
}

const scratch: string[] = [];
function tempDir(): string {
  const path = mkdtempSync(join(tmpdir(), "conclude-spec-"));
  scratch.push(path);
  return path;
}
after(() => {
  for (const path of scratch) rmSync(path, { recursive: true, force: true });
});

/** Write a `files` mapping into `root` (a key ending in `/` is a directory). */
function buildTree(root: string, files: Record<string, string | null>): void {
  for (const [relative, content] of Object.entries(files)) {
    const path = join(root, relative.replace(/\/$/, ""));
    if (relative.endsWith("/")) {
      mkdirSync(path, { recursive: true });
    } else {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, content ?? "", "utf8");
    }
  }
}

// --- naming --------------------------------------------------------------------------

describe("naming.json", () => {
  interface Case { name: string; app: string; key: string; env_var: string; cli_flag: string; config_key: string }
  for (const c of load<Case>("naming.json").cases) {
    test(c.name, () => {
      assert.equal(envVarName(c.app, c.key), c.env_var);
      assert.equal(cliFlagName(c.key), c.cli_flag);
      assert.equal(configKeyName(c.key), c.config_key);
    });
  }
});

// --- casters -------------------------------------------------------------------------

describe("casters.json", () => {
  interface Case { name: string; type: SettingType; input: unknown; output?: unknown; error?: boolean }
  for (const c of load<Case>("casters.json").cases) {
    test(c.name, () => {
      if (c.error) assert.throws(() => cast(c.type, c.input), CastError);
      else assert.deepEqual(cast(c.type, c.input), c.output);
    });
  }
});

// --- dotenv --------------------------------------------------------------------------

describe("dotenv.json", () => {
  interface Case { name: string; text: string; expect: Record<string, string> }
  for (const c of load<Case>("dotenv.json").cases) {
    test(c.name, () => {
      const path = join(tempDir(), ".env");
      writeFileSync(path, Buffer.from(c.text, "utf8"));
      assert.deepEqual(loadDotenv(path), c.expect);
    });
  }
});

// --- merge ---------------------------------------------------------------------------

describe("merge.json", () => {
  interface Case {
    name: string;
    settings: Setting[];
    layers: { config?: Record<string, unknown>; env?: Record<string, unknown>; developer?: Record<string, unknown>; cli?: Record<string, unknown> };
    expect?: Record<string, unknown>;
    error?: boolean;
  }
  for (const c of load<Case>("merge.json").cases) {
    test(c.name, () => {
      if (c.error) assert.throws(() => resolve(c.settings, c.layers), CastError);
      else assert.deepEqual(resolve(c.settings, c.layers), c.expect);
    });
  }
});

// --- config files --------------------------------------------------------------------

interface LayerFiles {
  system?: string;
  user?: string;
  project?: string;
  siblings?: Record<string, string>;
}

function writeLayerFiles(root: string, files: LayerFiles) {
  const paths = { system: join(root, "system.toml"), user: join(root, "user.toml"), project: join(root, "proj", ".config.toml") };
  mkdirSync(join(root, "proj"));
  for (const layer of ["system", "user", "project"] as const) {
    const text = files[layer];
    if (text !== undefined) writeFileSync(paths[layer], text, "utf8");
  }
  for (const [name, text] of Object.entries(files.siblings ?? {})) {
    writeFileSync(join(root, "proj", name), text, "utf8");
  }
  return paths;
}

describe("config_layers.json", () => {
  interface Case {
    name: string;
    settings: Setting[];
    table_path: string[];
    files: LayerFiles;
    aux_pattern?: string | null;
    expect?: Record<string, unknown>;
    error?: boolean;
  }
  for (const c of load<Case>("config_layers.json").cases) {
    test(c.name, () => {
      const paths = writeLayerFiles(tempDir(), c.files);
      const run = () =>
        loadConfigFiles(
          { ...paths, ...("aux_pattern" in c ? { auxPattern: c.aux_pattern ?? null } : {}) },
          c.settings,
          c.table_path,
        );
      if (c.error) assert.throws(run, ConfigFileError);
      else assert.deepEqual(run(), c.expect);
    });
  }
});

describe("config_tables.json", () => {
  interface Case {
    name: string;
    op: "parse" | "resolve";
    value?: string | null;
    default_table: string;
    config_value?: string | null;
    shorthand?: string | null;
    files?: LayerFiles;
    aux_pattern?: string | null;
    expect?: string[];
    error?: boolean;
  }
  for (const c of load<Case>("config_tables.json").cases) {
    test(c.name, () => {
      if (c.op === "parse") {
        if (c.error) assert.throws(() => parseConfigTable(c.value, c.default_table), ConfigTableError);
        else assert.deepEqual(parseConfigTable(c.value, c.default_table), c.expect);
        return;
      }
      const paths = writeLayerFiles(tempDir(), c.files ?? {});
      assert.deepEqual(
        resolveConfigTable({
          ...paths,
          configValue: c.config_value ?? null,
          shorthand: c.shorthand ?? null,
          defaultTable: c.default_table,
          ...("aux_pattern" in c ? { auxPattern: c.aux_pattern ?? null } : {}),
        }),
        c.expect,
      );
    });
  }
});

// --- templates -----------------------------------------------------------------------

describe("templates.json", () => {
  interface Case {
    name: string;
    app: string;
    settings: Setting[];
    options?: {
      skip?: string[];
      defaults?: Record<string, never>;
      env_vars?: Record<string, string>;
      table?: string | string[];
      header?: boolean;
      metavars?: Record<string, string | string[]>;
    };
    expect: { env?: string; toml?: string; cli?: string };
  }
  for (const c of load<Case>("templates.json").cases) {
    test(c.name, () => {
      const o = c.options ?? {};
      const options: TemplateOptions = {
        appName: c.app,
        ...(o.skip ? { skip: o.skip } : {}),
        ...(o.defaults ? { defaults: o.defaults } : {}),
        ...(o.env_vars ? { envVars: o.env_vars } : {}),
        ...(o.table !== undefined ? { table: o.table } : {}),
        ...(o.header !== undefined ? { header: o.header } : {}),
        ...(o.metavars ? { metavars: o.metavars } : {}),
      };
      if (c.expect.env !== undefined) assert.equal(formatEnv(c.settings, options), c.expect.env);
      if (c.expect.toml !== undefined) assert.equal(formatToml(c.settings, options), c.expect.toml);
      if (c.expect.cli !== undefined) assert.equal(formatCli(c.settings, options), c.expect.cli);
    });
  }
});

// --- gitignore and the guard ---------------------------------------------------------

describe("gitignore.json", () => {
  interface Case { name: string; files: Record<string, string>; paths: { path: string; ignored: boolean }[] }
  for (const c of load<Case>("gitignore.json").cases) {
    for (const entry of c.paths) {
      test(`${c.name}: ${entry.path}`, () => {
        const root = tempDir();
        buildTree(root, { ".git/": null, ...c.files });
        const target = join(root, entry.path);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, "");
        assert.equal(matchesGitIgnoreRules(root, target), entry.ignored);
      });
    }
  }
});

describe("guard.json", () => {
  interface Case {
    name: string;
    files: Record<string, string | null>;
    target: string;
    kill_switch_var?: string;
    env?: Record<string, string>;
    expect: { active: boolean; reason: string | null };
  }
  for (const c of load<Case>("guard.json").cases) {
    test(c.name, () => {
      const root = tempDir();
      buildTree(root, c.files);
      const result = checkGuard(join(root, c.target), {
        killSwitchVar: c.kill_switch_var ?? null,
        environ: c.env ?? {},
      });
      assert.deepEqual({ active: result.active, reason: result.reason }, c.expect);
      assert.equal(result.setupError, false);
    });
  }
});

describe("invocation.json", () => {
  interface Case {
    name: string;
    settings: Setting[];
    resolved: Record<string, unknown>;
    options?: { prog?: string; always_include?: string[]; skip?: string[]; compare_defaults?: Record<string, never> };
    expect: string;
  }
  for (const c of load<Case>("invocation.json").cases) {
    test(c.name, () => {
      const o = c.options ?? {};
      assert.equal(
        formatInvocation(c.settings, c.resolved, {
          ...(o.prog !== undefined ? { prog: o.prog } : {}),
          ...(o.always_include ? { alwaysInclude: o.always_include } : {}),
          ...(o.skip ? { skip: o.skip } : {}),
          ...(o.compare_defaults ? { compareDefaults: o.compare_defaults } : {}),
        }),
        c.expect,
      );
    });
  }
});

describe("sources.json", () => {
  interface Case {
    name: string;
    app: string;
    options: {
      system: string | null;
      user: string | null;
      project: string | null;
      aux: string | null;
      dotenv: { path: string | null; require_gitignored: boolean };
      developer: { file: string } | null;
    };
    files?: Record<string, string | null>;
    env?: Record<string, string>;
    expect: string;
  }
  for (const c of load<Case>("sources.json").cases) {
    test(c.name, () => {
      const root = tempDir();
      const fill = (value: string | null): string | null => (value === null ? null : value.replaceAll("{root}", root));
      buildTree(root, c.files ?? {});
      let manifestPath: string | null = null;
      if (c.options.developer !== null) {
        manifestPath = join(root, "package.json");
        writeFileSync(manifestPath, JSON.stringify({ conclude: { developer: { config: c.options.developer.file } } }));
      }
      const config = defineConfig({
        name: c.app,
        settings: { a: "x" },
        systemConfigPath: fill(c.options.system),
        userConfigPath: fill(c.options.user),
        projectConfigPath: fill(c.options.project),
        projectAuxPattern: c.options.aux,
        dotenvPath: fill(c.options.dotenv.path),
        dotenvRequireGitignored: c.options.dotenv.require_gitignored,
        manifestPath,
      });
      assert.equal(config.describeSources(c.env ?? {}), c.expect.replaceAll("{root}", root));
    });
  }
});

// --- the fixtures and this harness stay in step --------------------------------------

describe("the fixture set", () => {
  const RUN_HERE = [
    "casters.json",
    "config_layers.json",
    "config_tables.json",
    "dotenv.json",
    "gitignore.json",
    "guard.json",
    "invocation.json",
    "merge.json",
    "naming.json",
    "sources.json",
    "templates.json",
  ];

  test("every fixture file is run by this module", () => {
    const files = readdirSync(SPEC).filter((name) => name.endsWith(".json")).sort();
    assert.deepEqual(files, RUN_HERE);
  });

  test("case names are unique within a file", () => {
    for (const name of RUN_HERE) {
      const names = load<{ name: string }>(name).cases.map((c) => c.name);
      assert.equal(new Set(names).size, names.length, name);
    }
  });

  test("errors the library raises on purpose share one base class", () => {
    assert.throws(() => cast("bool", "maybe"), ConcludeError);
  });
});
