/**
 * The gitignore guard: a check that a private, local file really is private
 * (docs/concept.md, section 9). It never runs `git`: it evaluates the ignore
 * rules itself with the optional `ignore` package.
 */

import { existsSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve, sep } from "node:path";

import { SetupError } from "./errors.ts";

const KILL_SWITCH_VALUES = new Set(["0", "off", "false", "no"]);

const SETUP_HINT =
  "the 'ignore' package is required to verify the file is gitignored -- npm install ignore";

interface IgnoreInstance {
  add(patterns: readonly string[]): IgnoreInstance;
  test(path: string): { readonly ignored: boolean; readonly unignored: boolean };
}
type IgnoreFactory = () => IgnoreInstance;

const require = createRequire(import.meta.url);

function loadIgnore(): IgnoreFactory {
  try {
    const module = require("ignore") as IgnoreFactory & { default?: IgnoreFactory };
    return module.default ?? module;
  } catch {
    throw new SetupError(SETUP_HINT);
  }
}

function readLines(path: string): string[] {
  try {
    return readFileSync(path, "utf8").split(/\r\n|\n|\r/);
  } catch {
    return [];
  }
}

function findGitRoot(start: string): string | null {
  for (let directory = start; ; directory = dirname(directory)) {
    if (existsSync(join(directory, ".git"))) return directory;
    if (dirname(directory) === directory) return null;
  }
}

/**
 * Whether the working tree's ignore rules match `target` (an absolute path
 * inside the working tree at `root`): the `.gitignore` files from `root` down
 * to the file's directory plus `.git/info/exclude`, nearer files overriding
 * farther ones, the last matching pattern in a file winning, and an ignored
 * directory ignoring everything beneath it. Throws `SetupError` if the
 * optional `ignore` package is not installed.
 */
export function matchesGitIgnoreRules(root: string, target: string): boolean {
  const ignore = loadIgnore();
  const parts = relative(root, target).split(sep);
  const specs = new Map<string, IgnoreInstance | null>();

  const specFor = (directoryParts: readonly string[]): IgnoreInstance | null => {
    const id = directoryParts.join("/");
    if (!specs.has(id)) {
      const lines = readLines(join(root, ...directoryParts, ".gitignore"));
      specs.set(id, lines.length > 0 ? ignore().add(lines) : null);
    }
    return specs.get(id) ?? null;
  };
  const excludeLines = readLines(join(root, ".git", "info", "exclude"));
  const excludeSpec = excludeLines.length > 0 ? ignore().add(excludeLines) : null;

  const decide = (pathParts: readonly string[], isDirectory: boolean): boolean => {
    // The nearest .gitignore with any matching pattern (ignore or negation) decides.
    for (let depth = pathParts.length - 1; depth >= 0; depth -= 1) {
      const spec = specFor(pathParts.slice(0, depth));
      if (spec === null) continue;
      const result = spec.test(pathParts.slice(depth).join("/") + (isDirectory ? "/" : ""));
      if (result.ignored) return true;
      if (result.unignored) return false;
    }
    if (excludeSpec !== null) {
      const result = excludeSpec.test(pathParts.join("/") + (isDirectory ? "/" : ""));
      if (result.ignored) return true;
      if (result.unignored) return false;
    }
    return false;
  };

  // Git never descends into an ignored directory, so nothing inside one can be re-included.
  for (let depth = 1; depth < parts.length; depth += 1) {
    if (decide(parts.slice(0, depth), true)) return true;
  }
  return decide(parts, false);
}

export interface GuardOptions {
  /** An environment variable that, set to off/0/false/no, deactivates the file. */
  readonly killSwitchVar?: string | null;
  /** Where to read the kill switch from (default: `process.env`). */
  readonly environ?: Readonly<Record<string, string | undefined>>;
  /** Completes the missing-`ignore` message with the way out. */
  readonly escapeHint?: string | null;
}

export interface GuardResult {
  /** Every check passed. */
  readonly active: boolean;
  /** Why not, in one short phrase. */
  readonly reason: string | null;
  /** The optional `ignore` package is missing: a setup problem, not an ordinary state. */
  readonly setupError: boolean;
}

/**
 * Whether `path` may be used: not switched off, existing, inside a git working
 * tree, and ignored by it. Never throws; the first failure is the reason.
 */
export function checkGuard(path: string, options: GuardOptions = {}): GuardResult {
  const environ = options.environ ?? process.env;
  const fail = (reason: string, setupError = false): GuardResult => ({
    active: false,
    reason,
    setupError,
  });

  const variable = options.killSwitchVar;
  if (variable) {
    const value = (environ[variable] ?? "").trim();
    if (KILL_SWITCH_VALUES.has(value.toLowerCase())) return fail(`disabled by ${variable}=${value}`);
  }

  if (!existsSync(path) || !statSync(path).isFile()) return fail("file not found");

  const absolute = resolve(path);
  const root = findGitRoot(dirname(absolute));
  if (root === null) return fail("not inside a git working tree");

  let ignored: boolean;
  try {
    ignored = matchesGitIgnoreRules(root, absolute);
  } catch (error) {
    if (!(error instanceof SetupError)) throw error;
    const escape = options.escapeHint ?? (variable ? `or set ${variable}=off to skip the file` : null);
    return fail(SETUP_HINT + (escape ? ` (${escape})` : ""), true);
  }
  if (!ignored) return fail("not covered by .gitignore");
  return { active: true, reason: null, setupError: false };
}
