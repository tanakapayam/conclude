/**
 * Keeps the Node documentation honest: the README quickstart and every
 * `// run` block in the guide are executed against the source and must print
 * what the docs say, the reference covers every export, and every link and
 * anchor resolves.
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { after, describe, test } from "node:test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const NODE = join(ROOT, "node");
const INDEX = pathToFileURL(join(NODE, "src", "index.ts")).href;
const README = join(NODE, "README.md");
const GUIDE = join(ROOT, "docs", "node", "guide.md");
const REFERENCE = join(ROOT, "docs", "node", "reference.md");
const BASE_URL = "https://github.com/tanakapayam/conclude/blob/main/";

const read = (path: string): string => readFileSync(path, "utf8");

const scratch: string[] = [];
after(() => {
  for (const path of scratch) rmSync(path, { recursive: true, force: true });
});

function fencedBlocks(text: string): { lang: string; code: string }[] {
  return [...text.matchAll(/```(\w*)\n(.*?)```/gs)].map((m) => ({ lang: m[1] ?? "", code: m[2] ?? "" }));
}

/** Run a TypeScript program against the source, in an empty home and working directory. */
function runProgram(code: string, argv: string[] = [], env: Record<string, string> = {}): string {
  const dir = mkdtempSync(join(tmpdir(), "conclude-docs-"));
  scratch.push(dir);
  writeFileSync(join(dir, "app.ts"), code.replaceAll('"@tanakapayam/conclude"', JSON.stringify(INDEX)));
  const result = spawnSync(process.execPath, ["app.ts", ...argv], {
    cwd: dir,
    env: { PATH: process.env["PATH"] ?? "", HOME: dir, USERPROFILE: dir, ...env },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, `program failed:\n${code}\n${result.stderr}`);
  return result.stdout.replace(/\n$/, "");
}

describe("the README", () => {
  test("its quickstart runs and prints what the README says", () => {
    const blocks = fencedBlocks(read(README));
    const program = blocks.find((b) => b.lang === "ts");
    const shell = blocks.find((b) => b.code.startsWith("$ "));
    assert.ok(program && shell);
    const [commandLine = "", ...expected] = shell.code.trimEnd().split("\n");
    const tokens = commandLine.slice(2).split(/\s+/);
    const env: Record<string, string> = {};
    while (tokens[0]?.includes("=")) {
      const [key = "", value = ""] = (tokens.shift() ?? "").split("=");
      env[key] = value;
    }
    assert.deepEqual(tokens.slice(0, 2), ["node", "app.ts"]);
    assert.equal(runProgram(program.code, tokens.slice(2), env), expected.join("\n"));
  });

  test("its links are absolute, so they work on npm", () => {
    for (const [, target] of read(README).matchAll(/\]\(([^)\s]+)\)/g)) {
      assert.match(target ?? "", /^https?:\/\//);
    }
  });
});

describe("the guide", () => {
  const blocks = fencedBlocks(read(GUIDE));
  const runnable = blocks
    .map((block, index) => ({ block, next: blocks[index + 1] }))
    .filter(({ block }) => block.lang === "ts" && block.code.startsWith("// run\n"));

  test("it has runnable examples", () => {
    assert.ok(runnable.length >= 5);
  });

  for (const [index, { block, next }] of runnable.entries()) {
    test(`runnable block ${index + 1} prints what the guide says`, () => {
      assert.ok(next && next.lang === "", "a runnable block is followed by its output block");
      assert.equal(runProgram(block.code), next.code.replace(/\n$/, ""));
    });
  }
});

describe("the reference", () => {
  const codeSpans = [...read(REFERENCE).matchAll(/`([^`\n]+)`/g)].map((m) => m[1] ?? "");
  const mentioned = (name: string): boolean =>
    codeSpans.some((span) => new RegExp(`(?<![\\w.])${name}(?!\\w)`).test(span));

  test("it covers every export of the package", () => {
    const index = read(join(NODE, "src", "index.ts"));
    const names = [...index.matchAll(/export\s+(?:type\s+)?\{([^}]*)\}/g)].flatMap((m) =>
      (m[1] ?? "")
        .split(",")
        .map((part) => part.trim().split(/\s+as\s+/).pop() ?? "")
        .filter(Boolean),
    );
    assert.ok(names.length > 40);
    const missing = names.filter((name) => !mentioned(name));
    assert.deepEqual(missing, []);
  });

  test("it covers every option and every member of a Config", () => {
    const source = read(join(NODE, "src", "define.ts"));
    const body = (heading: string): string[] => {
      const start = source.indexOf(`export interface ${heading}`);
      const end = source.indexOf("\n}\n", start);
      return [...source.slice(start, end).matchAll(/^ {2}(?:readonly )?(\w+)[?(<:]/gm)].map((m) => m[1] ?? "");
    };
    const members = [...body("ConfigOptions"), ...body("ResolveOptions"), ...body("Config"), ...body("ParsedArgs"), ...body("FormatOptions"), ...body("TomlFormatOptions"), ...body("CliFormatOptions"), ...body("InvocationFormatOptions")];
    assert.ok(members.length > 25);
    assert.deepEqual(members.filter((name) => !mentioned(name)), []);
  });
});

describe("links and anchors", () => {
  const slug = (title: string): string => title.toLowerCase().trim().replace(/[^\p{L}\p{N}_\- ]/gu, "").replaceAll(" ", "-");
  const anchors = (path: string): Set<string> =>
    new Set([...read(path).replace(/```.*?```/gs, "").matchAll(/^#{1,6} (.+)$/gm)].map((m) => slug(m[1] ?? "")));

  for (const path of [README, GUIDE, REFERENCE]) {
    test(`every link in ${path.slice(ROOT.length + 1)} resolves`, () => {
      const text = read(path).replace(/```.*?```/gs, "");
      for (const [, raw = ""] of text.matchAll(/\]\(([^)\s]+)\)/g)) {
        if (/^(https?:|mailto:)/.test(raw) && !raw.startsWith(BASE_URL)) continue;
        const [target = "", anchor = ""] = raw.split("#");
        const file = raw.startsWith(BASE_URL) ? join(ROOT, target.slice(BASE_URL.length)) : target === "" ? path : resolve(dirname(path), target);
        assert.ok(existsSync(file), `${raw} -> ${file}`);
        if (anchor && file.endsWith(".md")) assert.ok(anchors(file).has(anchor), `${raw}: no such heading`);
      }
    });
  }
});
