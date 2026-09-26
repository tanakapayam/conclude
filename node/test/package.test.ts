/**
 * The shape of package.json: what the package points at is built, packing builds
 * it, and the version, the changelog and the private flag agree. (`npm run smoke`
 * proves it dynamically by packing from a tree with no build output.)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

const NODE = new URL("../", import.meta.url);
const pkg = JSON.parse(readFileSync(new URL("package.json", NODE), "utf8")) as {
  version: string;
  private?: boolean;
  main: string;
  types: string;
  files: string[];
  exports: Record<string, { types: string; default: string } | string>;
  scripts: Record<string, string>;
};
const changelog = readFileSync(new URL("CHANGELOG.md", NODE), "utf8");

describe("package.json", () => {
  test("everything it points at is under dist/, which ships", () => {
    const root = pkg.exports["."];
    assert.ok(typeof root === "object");
    for (const target of [pkg.main, pkg.types, root.types, root.default]) {
      assert.match(target, /^\.\/dist\//, target);
    }
    assert.ok(pkg.files.includes("dist"));
  });

  test("packing builds first, so a manual `npm publish` cannot ship without dist/", () => {
    assert.match(pkg.scripts["prepack"] ?? "", /npm run build/);
  });

  test("the version has a dated changelog entry, and the newest entry is this version", () => {
    assert.match(changelog, new RegExp(`^## \\[${pkg.version.replaceAll(".", "\\.")}\\] - \\d{4}-\\d{2}-\\d{2}`, "m"));
    const newest = /^## \[([^\]]+)\]/m.exec(changelog.replace(/^## \[Unreleased\][^\n]*\n/m, ""));
    assert.equal(newest?.[1], pkg.version);
  });

  test("a version that was ever published is marked as such and is never reused", () => {
    // 0.1.0 went out without its build output; npm never lets a version be published twice.
    assert.notEqual(pkg.version, "0.1.0");
    assert.match(changelog, /^## \[0\.1\.0\] - 2026-09-20 \[YANKED\]/m);
  });
});
