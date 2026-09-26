// Exercises the staging mechanics of the release pipeline against a local registry:
// publish, publish again (an idempotent re-run), refuse a changed tarball under the same
// version, and install back from the registry. Needs REHEARSAL_REGISTRY, e.g. a local
// Verdaccio started with scripts/verdaccio.yaml:
//
//   npx verdaccio@6.10.4 --config scripts/verdaccio.yaml --listen 127.0.0.1:4873 &
//   REHEARSAL_REGISTRY=http://127.0.0.1:4873 npm run rehearse

import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { integrityOf, manifestOf } from "./registry.mjs";

const registry = process.env.REHEARSAL_REGISTRY;
if (!registry) {
  console.error("REHEARSAL_REGISTRY is not set: start a local registry first (see the header of this file).");
  process.exit(2);
}

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const scratch = mkdtempSync(join(tmpdir(), "conclude-rehearsal-"));

// npm will not publish without credentials, even to a registry that would let anyone in: register
// a throwaway user and hand npm its token through a private npmrc that the child processes inherit.
const base = registry.replace(/\/$/, "");
const user = `rehearsal-${Date.now()}`;
const registration = await fetch(`${base}/-/user/org.couchdb.user:${user}`, {
  method: "PUT",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ name: user, password: "rehearsal-password", email: `${user}@example.com`, type: "user" }),
});
assert.ok(registration.ok, `could not register a user on ${base}: ${registration.status}`);
const { token } = await registration.json();
const npmrc = join(scratch, "npmrc");
writeFileSync(npmrc, `//${base.replace(/^https?:\/\//, "")}/:_authToken=${token}\n`);
process.env.NPM_CONFIG_USERCONFIG = npmrc;
const registryScript = new URL("./registry.mjs", import.meta.url).pathname;

const run = (...args) => spawnSync(process.execPath, [registryScript, ...args], { encoding: "utf8" });
const last = (text) => JSON.parse(text.trim().split("\n").filter((line) => line.startsWith("{")).pop());

/** Re-pack an unpacked package with a change applied (no scripts: there is nothing to build here). */
function repack(tarball, name, change) {
  const dir = join(scratch, name);
  execFileSync("mkdir", ["-p", dir]);
  execFileSync("tar", ["-xzf", tarball, "-C", dir]);
  change(join(dir, "package"));
  const [packed] = JSON.parse(execFileSync(npm, ["pack", join(dir, "package"), "--ignore-scripts", "--json", "--pack-destination", scratch], { encoding: "utf8" }));
  return join(scratch, packed.filename);
}

try {
  // The real thing: pack the package (its `prepack` builds it).
  const [packed] = JSON.parse(execFileSync(npm, ["pack", "--json", "--pack-destination", scratch], { encoding: "utf8" }));
  const base = join(scratch, packed.filename);

  // Like a manual staging run, give the rehearsal a version of its own.
  const version = `${manifestOf(base).version}-rehearsal.${Date.now()}`;
  const staged = repack(base, "staged", (dir) => {
    const path = join(dir, "package.json");
    const manifest = JSON.parse(readFileSync(path, "utf8"));
    writeFileSync(path, JSON.stringify({ ...manifest, version }, null, 2));
  });
  const { name } = manifestOf(staged);
  const integrity = integrityOf(staged);

  const first = run("publish-if-absent", staged, "--registry", registry);
  assert.equal(first.status, 0, first.stderr);
  assert.equal(last(first.stdout).action, "published");
  assert.equal(last(first.stdout).integrity, integrity);
  console.log(`staged ${name}@${version}`);

  const again = run("publish-if-absent", staged, "--registry", registry);
  assert.equal(again.status, 0, again.stderr);
  assert.equal(last(again.stdout).action, "already-staged");
  console.log("a re-run is a no-op");

  const tampered = repack(staged, "tampered", (dir) => writeFileSync(join(dir, "README.md"), "# changed\n"));
  const refused = run("publish-if-absent", tampered, "--registry", registry);
  assert.notEqual(refused.status, 0, "a changed tarball under the same version must be refused");
  assert.match(refused.stderr, /different content/);
  console.log("a changed tarball under the same version is refused");

  const verified = run("verify", "--package", name, "--version", version, "--registry", registry, "--integrity", integrity);
  assert.equal(verified.status, 0, verified.stderr);
  assert.equal(last(verified.stdout).integrity, integrity);
  console.log("installed back from the registry and checked");

  const wrong = run("verify", "--package", name, "--version", version, "--registry", registry, "--integrity", "sha512-nope");
  assert.notEqual(wrong.status, 0, "a wrong integrity must fail verification");
  console.log("a wrong integrity fails verification");

  const noProvenance = run("verify", "--package", name, "--version", version, "--registry", registry, "--expect-provenance");
  assert.notEqual(noProvenance.status, 0, "a package without provenance must fail --expect-provenance");
  console.log("a missing provenance attestation is caught");
  console.log("rehearsal ok");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
