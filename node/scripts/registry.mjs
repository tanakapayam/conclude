#!/usr/bin/env node
// Registry helpers for the release pipeline (.github/workflows/node-publish.yml).
//
//   node scripts/registry.mjs integrity <tarball>
//       print the tarball's npm-style integrity (sha512-<base64>)
//   node scripts/registry.mjs publish-if-absent <tarball> --registry <url> [--tag <tag>]
//       publish the tarball unless the registry already has that exact name@version
//       with the same content (a re-run); refuse if the version exists with different content
//   node scripts/registry.mjs verify --package <name> --version <v> --registry <url>
//         [--integrity <sha512-...>] [--expect-provenance] [--attempts N] [--delay SECONDS]
//       install name@version from the registry into a fresh project, check the integrity
//       (and, if asked, that npm recorded a provenance attestation), and check the package
//       actually works (import and require)
//
// Authentication is whatever npm is already configured with (for GitHub Packages, the
// NODE_AUTH_TOKEN that actions/setup-node wires into .npmrc). Nothing here needs a token
// for anonymous registries.

import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";

export function integrityOf(path) {
  return `sha512-${createHash("sha512").update(readFileSync(path)).digest("base64")}`;
}

export function manifestOf(tarball) {
  return JSON.parse(execFileSync("tar", ["-xOzf", tarball, "package/package.json"], { encoding: "utf8" }));
}

/** `dist.integrity` of name@version on the registry, or `null` if the registry does not have it. */
export function registryIntegrity(name, version, registry) {
  const result = spawnSync(npm, ["view", `${name}@${version}`, "dist.integrity", "--registry", registry], { encoding: "utf8" });
  if (result.status === 0 && result.stdout.trim() !== "") return result.stdout.trim();
  if (/E404|404 Not Found|is not in this registry/i.test(result.stderr + result.stdout)) return null;
  if (result.status === 0) return null;
  throw new Error(`could not ask ${registry} about ${name}@${version}:\n${result.stderr || result.stdout}`);
}

/** Whether npm recorded a provenance attestation for name@version on the registry. */
export function hasProvenance(name, version, registry) {
  const result = spawnSync(npm, ["view", `${name}@${version}`, "dist.attestations", "--json", "--registry", registry], { encoding: "utf8" });
  if (result.status !== 0 || result.stdout.trim() === "") return false;
  return Boolean(JSON.parse(result.stdout).provenance);
}

function output(values) {
  console.log(JSON.stringify(values));
  if (process.env.GITHUB_OUTPUT) {
    for (const [key, value] of Object.entries(values)) appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${value}\n`);
  }
}

export function publishIfAbsent(tarball, registry, tag) {
  const { name, version } = manifestOf(tarball);
  const local = integrityOf(tarball);
  const existing = registryIntegrity(name, version, registry);
  let action;
  if (existing === null) {
    execFileSync(npm, ["publish", tarball, "--registry", registry, ...(tag ? ["--tag", tag] : [])], { stdio: "inherit" });
    action = "published";
    const stored = registryIntegrity(name, version, registry);
    if (stored !== local) {
      throw new Error(`${registry} now serves ${name}@${version} with integrity ${stored}, not the tarball's ${local}`);
    }
  } else if (existing === local) {
    action = "already-staged";
  } else {
    throw new Error(
      `${name}@${version} already exists on ${registry} with different content (${existing}, not ${local}); ` +
        "bump the version -- a published version can never be replaced",
    );
  }
  return { name, version, integrity: local, action };
}

/** The import and require checks a working package must pass, run against an installed copy. */
export function checkInstalled(project, name) {
  const run = (args) => {
    const result = spawnSync(process.execPath, args, { cwd: project, encoding: "utf8" });
    if (result.status !== 0) throw new Error(`the installed package failed:\n${result.stderr}`);
    return result.stdout.trim();
  };
  run([
    "--input-type=module",
    "-e",
    `
    import { defineConfig, formatEnv, resolve, envVarName, int } from ${JSON.stringify(name)};
    const settings = [{ key: "port", type: "int", default: 8080 }, { key: "debug", type: "bool", default: false }];
    const resolved = resolve(settings, { env: { port: "9000" }, cli: { debug: true } });
    if (resolved.port !== 9000 || resolved.debug !== true) throw new Error("resolve() gave " + JSON.stringify(resolved));
    if (envVarName("my-app", "foo_bar") !== "MY_APP_FOO_BAR") throw new Error("envVarName");
    if (!formatEnv(settings, { appName: "myapp" }).startsWith("MYAPP_PORT=8080")) throw new Error("formatEnv");
    const config = defineConfig({ name: "myapp", settings: { retryLimit: int(3), debug: false }, userConfigPath: null, projectConfigPath: null });
    const out = config.resolve({ environ: { MYAPP_RETRY_LIMIT: "5" }, cli: { debug: true } });
    if (out.retryLimit !== 5 || out.debug !== true) throw new Error("defineConfig().resolve() gave " + JSON.stringify(out));
    if (config.formatInvocation(out, { prog: "myapp" }) !== "myapp --retry-limit=5 --debug") throw new Error("formatInvocation");
    console.log("ESM import ok");
  `,
  ]);
  run([
    "-e",
    `
    const { resolve } = require(${JSON.stringify(name)});
    const out = resolve([{ key: "n", type: "int", default: 1 }], { env: { n: "2" } });
    if (out.n !== 2) throw new Error("require() gave " + JSON.stringify(out));
  `,
  ]);
}

function sleep(seconds) {
  spawnSync(process.execPath, ["-e", `setTimeout(() => {}, ${Math.round(seconds * 1000)})`]);
}

export function verify({ name, version, registry, integrity, expectProvenance = false, attempts = 1, delay = 10 }) {
  const scratch = mkdtempSync(join(tmpdir(), "conclude-verify-"));
  try {
    const project = join(scratch, "project");
    mkdirSync(project);
    writeFileSync(join(project, "package.json"), JSON.stringify({ name: "verify", private: true, type: "module" }));
    // Map only the package's scope to the registry: its dependencies still come from the default one.
    const scope = name.startsWith("@") ? name.split("/")[0] : null;
    const host = registry.replace(/^https?:/, "").replace(/\/?$/, "/");
    const npmrc = [scope ? `${scope}:registry=${registry}` : `registry=${registry}`];
    if (process.env.NODE_AUTH_TOKEN) npmrc.push(`${host}:_authToken=${process.env.NODE_AUTH_TOKEN}`);
    writeFileSync(join(project, ".npmrc"), `${npmrc.join("\n")}\n`);

    let lastError;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        rmSync(join(project, "node_modules"), { recursive: true, force: true });
        execFileSync(npm, ["install", `${name}@${version}`, "--no-audit", "--no-fund"], { cwd: project, stdio: ["ignore", "pipe", "pipe"] });
        const lock = JSON.parse(readFileSync(join(project, "package-lock.json"), "utf8"));
        const entry = lock.packages[`node_modules/${name}`];
        if (!entry) throw new Error(`${name} is not in the installed tree`);
        if (integrity && entry.integrity !== integrity) {
          throw new Error(`installed ${name}@${version} has integrity ${entry.integrity}, expected ${integrity}`);
        }
        const installed = JSON.parse(readFileSync(join(project, "node_modules", ...name.split("/"), "package.json"), "utf8"));
        if (installed.version !== version) throw new Error(`installed version ${installed.version}, expected ${version}`);
        if (expectProvenance && !hasProvenance(name, version, registry)) {
          throw new Error(`${name}@${version} has no provenance attestation`);
        }
        checkInstalled(project, name);
        return { name, version, integrity: entry.integrity, registry };
      } catch (error) {
        lastError = error;
        if (attempt < attempts) {
          console.error(`attempt ${attempt}/${attempts} failed (${String(error.message).split("\n")[0]}); retrying in ${delay}s`);
          sleep(delay);
        }
      }
    }
    throw lastError;
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

function parse(argv) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) flags[key] = true;
      else {
        flags[key] = next;
        i += 1;
      }
    } else positional.push(arg);
  }
  return { positional, flags };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [command, ...rest] = process.argv.slice(2);
  const { positional, flags } = parse(rest);
  try {
    if (command === "integrity") {
      console.log(integrityOf(positional[0]));
    } else if (command === "publish-if-absent") {
      output(publishIfAbsent(positional[0], flags.registry, flags.tag === true ? undefined : flags.tag));
    } else if (command === "verify") {
      const result = verify({
        name: flags.package,
        version: flags.version,
        registry: flags.registry,
        integrity: typeof flags.integrity === "string" ? flags.integrity : undefined,
        expectProvenance: flags["expect-provenance"] === true,
        attempts: Number(flags.attempts ?? 1),
        delay: Number(flags.delay ?? 10),
      });
      output({ verified: true, ...result });
    } else {
      console.error("usage: registry.mjs integrity|publish-if-absent|verify ... (see the header of this file)");
      process.exit(2);
    }
  } catch (error) {
    console.error(`::error::${String(error.message).split("\n")[0]}`);
    console.error(error.message);
    process.exit(1);
  }
}
