/** Config files and table selection (docs/concept.md, section 7). */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join } from "node:path";

import { parse } from "smol-toml";

import { ConfigFileError, ConfigTableError } from "./errors.ts";
import type { Setting } from "./types.ts";

type Table = Record<string, unknown>;

/** The default pattern for sibling files next to the project config file. */
export const DEFAULT_AUX_PATTERN = ".config.*.toml";

function isFile(path: string): boolean {
  return existsSync(path) && statSync(path).isFile();
}

function isTable(value: unknown): value is Table {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** `"PARENT"` or `"PARENT.CHILD"` as a table path; nothing given is the default table. */
export function parseConfigTable(value: string | null | undefined, defaultTable: string): string[] {
  if (value === null || value === undefined || value === "") return [defaultTable];
  const parts = value.split(".");
  if (parts.length > 2 || parts.some((part) => part === "")) {
    throw new ConfigTableError(`config table must be PARENT or PARENT.CHILD, got "${value}"`);
  }
  return parts;
}

/** Whether `raw` has a table at `tablePath` (as opposed to nothing, or a plain value). */
export function tableExists(raw: Table, tablePath: readonly string[]): boolean {
  let node: unknown = raw;
  for (const part of tablePath) {
    if (!isTable(node) || !Object.hasOwn(node, part)) return false;
    node = node[part];
  }
  return isTable(node);
}

/** A file's parsed TOML, `{}` if it does not exist. Throws `ConfigFileError` if it is not valid. */
export function loadRawToml(path: string | null | undefined): Table {
  if (path === null || path === undefined || !isFile(path)) return {};
  try {
    return parse(readFileSync(path, "utf8")) as Table;
  } catch (error) {
    throw new ConfigFileError(`${path}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/** One file's settings from the selected table(s); only keys a setting declares are read. */
export function loadConfigFile(
  path: string | null | undefined,
  settings: readonly Setting[],
  tablePath: readonly string[],
): Table {
  if (path === null || path === undefined || !isFile(path)) return {};
  const raw = loadRawToml(path);
  const parent = raw[tablePath[0] ?? ""];
  if (!isTable(parent)) return {};
  const merged: Table = {};
  const take = (table: Table): void => {
    for (const { key } of settings) {
      if (Object.hasOwn(table, key)) merged[key] = table[key];
    }
  };
  take(parent);
  if (tablePath.length === 2) {
    const child = parent[tablePath[1] ?? ""];
    if (isTable(child)) take(child);
  }
  return merged;
}

function globToRegExp(pattern: string): RegExp {
  const source = Array.from(pattern, (ch) =>
    ch === "*" ? "[^/]*" : ch === "?" ? "[^/]" : ch.replace(/[.+^${}()|[\]\\]/g, "\\$&"),
  ).join("");
  return new RegExp(`^${source}$`, "u");
}

/** Sibling files next to `projectPath` matching `pattern`, sorted by name. */
export function auxConfigPaths(
  projectPath: string | null | undefined,
  pattern: string | null | undefined,
): string[] {
  if (projectPath === null || projectPath === undefined) return [];
  if (pattern === null || pattern === undefined) return [];
  const directory = dirname(projectPath);
  if (!existsSync(directory) || !statSync(directory).isDirectory()) return [];
  const matcher = globToRegExp(pattern);
  return readdirSync(directory)
    .filter((name) => matcher.test(name) && name !== basename(projectPath))
    .map((name) => join(directory, name))
    .filter(isFile)
    .sort();
}

export interface ConfigFiles {
  /** `/etc/<name>/config.toml`-style file: the lowest priority. */
  readonly system?: string | null;
  /** `~/.config/<name>/config.toml`-style file. */
  readonly user?: string | null;
  /** `./.config.toml`-style file; its siblings are merged after it. */
  readonly project?: string | null;
  /** Sibling pattern; `null` switches the sibling search off. */
  readonly auxPattern?: string | null;
}

/** Merge every config file, lowest priority first: system, user, project, siblings. */
export function loadConfigFiles(
  files: ConfigFiles,
  settings: readonly Setting[],
  tablePath: readonly string[],
): Table {
  const auxPattern = files.auxPattern === undefined ? DEFAULT_AUX_PATTERN : files.auxPattern;
  return {
    ...loadConfigFile(files.system, settings, tablePath),
    ...loadConfigFile(files.user, settings, tablePath),
    ...loadConfigFile(files.project, settings, tablePath),
    ...Object.assign({}, ...auxConfigPaths(files.project, auxPattern).map((path) => loadConfigFile(path, settings, tablePath))),
  };
}

export interface TableSelection extends ConfigFiles {
  /** An explicit selection (a flag or its env var); wins outright. */
  readonly configValue?: string | null;
  /** A bare positional value, looked up in the config files themselves. */
  readonly shorthand?: string | null;
  readonly defaultTable: string;
}

/** Choose the table(s) to read: an explicit selection, else the shorthand lookup, else the default. */
export function resolveConfigTable(selection: TableSelection): string[] {
  const { configValue, shorthand, defaultTable } = selection;
  if (configValue) return parseConfigTable(configValue, defaultTable);
  if (!shorthand) return [defaultTable];
  const auxPattern = selection.auxPattern === undefined ? DEFAULT_AUX_PATTERN : selection.auxPattern;
  const raws = [
    selection.project,
    selection.user,
    selection.system,
    ...auxConfigPaths(selection.project, auxPattern),
  ].map((path) => loadRawToml(path));
  if (raws.some((raw) => tableExists(raw, [shorthand]))) return [shorthand];
  if (raws.some((raw) => tableExists(raw, [defaultTable, shorthand]))) return [defaultTable, shorthand];
  return [defaultTable];
}
