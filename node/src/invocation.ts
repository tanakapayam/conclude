/**
 * Reproducing a resolved configuration as a standalone command line
 * (docs/concept.md, section 11): the inverse of `resolve`, handy for a
 * `--print-invocation` flag.
 */

import { cliFlagName } from "./naming.ts";
import { plainText } from "./render.ts";
import type { Setting, SettingType, SettingValue } from "./types.ts";

const SAFE = /^[A-Za-z0-9_@%+=:,./-]+$/;

/** POSIX shell quoting: bare if every character is safe, else single-quoted (`'` becomes `'"'"'`). */
export function shellQuote(text: string): string {
  if (text === "") return "''";
  return SAFE.test(text) ? text : `'${text.replaceAll("'", `'"'"'`)}'`;
}

export interface InvocationOptions {
  /** The program name, written first. */
  readonly prog?: string;
  /** Keys to write even when they equal their default. */
  readonly alwaysInclude?: Iterable<string>;
  /** Keys to leave out entirely (this beats `alwaysInclude`). */
  readonly skip?: Iterable<string>;
  /** A complete map of what counts as each key's default; it replaces the declared defaults. */
  readonly compareDefaults?: Readonly<Record<string, SettingValue | null>>;
}

function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((item, i) => same(item, b[i]));
  return a === b;
}

/** The flag's value text: `""` for a bare flag, `null` for "do not write it". */
function render(type: SettingType, value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (type === "bool") return value === true ? "" : null;
  if (Array.isArray(value)) return shellQuote(value.join(","));
  return shellQuote(plainText(type, value as SettingValue) ?? "");
}

/**
 * A standalone command line that reproduces `resolved` (canonical keys) with no
 * environment variables, config files or shorthand needed. A setting equal to its
 * default is left out, so is a boolean that is off, and so is an unset value.
 */
export function formatInvocation(
  settings: readonly Setting[],
  resolved: Readonly<Record<string, unknown>>,
  options: InvocationOptions = {},
): string {
  const skip = new Set(options.skip ?? []);
  const always = new Set(options.alwaysInclude ?? []);
  const compare = options.compareDefaults;
  const parts = options.prog ? [options.prog] : [];
  for (const setting of settings) {
    if (skip.has(setting.key)) continue;
    const value = resolved[setting.key] ?? null;
    const baseline = compare === undefined ? (setting.default ?? null) : (compare[setting.key] ?? null);
    if (same(value, baseline) && !always.has(setting.key)) continue;
    const rendered = render(setting.type, value);
    if (rendered === null) continue;
    const flag = cliFlagName(setting.key);
    parts.push(rendered === "" ? flag : `${flag}=${rendered}`);
  }
  return parts.join(" ");
}
