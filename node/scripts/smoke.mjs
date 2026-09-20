// Packs the package, installs the tarball into a scratch project, and checks
// it from the outside: what ships, that it imports (ESM and CommonJS), and
// that the optional `ignore` dependency behaves as documented.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { checkInstalled } from "./registry.mjs";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const run = (command, args, options = {}) =>
  execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], ...options });

const scratch = mkdtempSync(join(tmpdir(), "conclude-smoke-"));
try {
  // 1. What ships. Start with no build output at all: packing must build it itself (the
  //    `prepack` script), because `npm publish` from a fresh checkout runs nothing else.
  rmSync("dist", { recursive: true, force: true });
  const [packed] = JSON.parse(run(npm, ["pack", "--json", "--pack-destination", scratch]));
  const shipped = packed.files.map((file) => file.path);
  for (const path of shipped) {
    assert.ok(
      path === "package.json" || /^(README|LICENSE|CHANGELOG)(\.md)?$/.test(path) || path.startsWith("dist/"),
      `unexpected file in the package: ${path}`,
    );
  }
  for (const required of ["package.json", "README.md", "LICENSE", "CHANGELOG.md", "dist/index.js", "dist/index.d.ts"]) {
    assert.ok(shipped.includes(required), `missing from the package: ${required}`);
  }
  console.log(`packed ${packed.name}@${packed.version}: ${shipped.length} files`);

  // 2. Install it into a fresh project.
  const project = join(scratch, "project");
  mkdirSync(project);
  writeFileSync(join(project, "package.json"), JSON.stringify({ name: "smoke", private: true, type: "module" }));
  run(npm, ["install", join(scratch, packed.filename), "--no-audit", "--no-fund"], { cwd: project });

  checkInstalled(project, "@tanakapayam/conclude");
  console.log("ESM import ok");
  console.log("CommonJS require ok");

  // 3. The gitignore check: a setup error without `ignore`, working with it.
  const repo = join(scratch, "repo");
  mkdirSync(join(repo, ".git"), { recursive: true });
  writeFileSync(join(repo, ".gitignore"), "private.toml\n");
  writeFileSync(join(repo, "private.toml"), "");
  const guard = (expected) => `
    import { checkGuard } from "@tanakapayam/conclude";
    const r = checkGuard(${JSON.stringify(join(repo, "private.toml"))}, { environ: {} });
    console.log(JSON.stringify(r));
    if (r.active !== ${expected}) process.exit(1);
  `;
  const without = JSON.parse(run(process.execPath, ["--input-type=module", "-e", guard(false)], { cwd: project }).trim());
  assert.equal(without.setupError, true, "without `ignore`, the guard must report a setup error");
  assert.match(without.reason, /npm install ignore/);
  console.log("guard without `ignore`: setup error, as documented");

  // The high-level API raises it (rather than skipping the file) when a guarded file needs the check.
  const strictDotenv = `
    import { defineConfig } from "@tanakapayam/conclude";
    const config = defineConfig({
      name: "smoke", settings: { a: "x" }, userConfigPath: null, projectConfigPath: null,
      dotenvPath: ${JSON.stringify(join(repo, ".gitignored.env"))}, dotenvRequireGitignored: true,
    });
    try { config.resolve({ environ: {} }); console.log("no error"); }
    catch (error) { console.log(error.name); }
    console.log(config.describeSources({}).includes("inactive") ? "describeSources reports it" : "describeSources missed it");
  `;
  writeFileSync(join(repo, ".gitignore"), "private.toml\n.gitignored.env\n");
  writeFileSync(join(repo, ".gitignored.env"), "SMOKE_A=y\n");
  const strict = run(process.execPath, ["--input-type=module", "-e", strictDotenv], { cwd: project }).trim().split("\n");
  assert.equal(strict[0], "SetupError", "defineConfig must throw SetupError when a guarded .env cannot be checked");
  assert.equal(strict[1], "describeSources reports it");
  console.log("defineConfig without `ignore`: SetupError, and describeSources still reports it");

  run(npm, ["install", "ignore", "--no-audit", "--no-fund"], { cwd: project });
  const withIgnore = JSON.parse(run(process.execPath, ["--input-type=module", "-e", guard(true)], { cwd: project }).trim());
  assert.equal(withIgnore.active, true);
  console.log("guard with `ignore`: active");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
