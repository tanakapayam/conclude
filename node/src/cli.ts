/**
 * The command-line surface derived from the settings (docs/concept.md,
 * section 4): one flag per setting, a negation (`--no-flag`) for every `bool`,
 * and what a command line gives each setting.
 */

import { parseArgs } from "node:util";
import type { ParseArgsOptionsConfig } from "node:util";

import { ConcludeError } from "./errors.ts";
import { cliFlagName, cliNegatedFlagName } from "./naming.ts";
import type { Setting, SettingType } from "./types.ts";

/** One flag a setting answers to. */
export interface CliFlag {
  readonly key: string;
  /** The flag with its leading `--`. */
  readonly flag: string;
  readonly type: SettingType;
  /** `true` for a `bool`'s negation: it sets the setting to false. */
  readonly negated: boolean;
}

/**
 * Every flag the settings get, in declaration order: a setting's own flag, then,
 * for a `bool`, its negation. Throws if two settings claim the same flag (a
 * `bool` `cache` and a setting `no_cache` both want `--no-cache`).
 */
export function cliFlags(settings: readonly Setting[], skip: Iterable<string> = []): CliFlag[] {
  const skipped = new Set(skip);
  const owners = new Map<string, string>();
  const flags: CliFlag[] = [];
  for (const { key, type } of settings) {
    if (skipped.has(key)) continue;
    const mine: CliFlag[] = [{ key, flag: cliFlagName(key), type, negated: false }];
    if (type === "bool") mine.push({ key, flag: cliNegatedFlagName(key), type, negated: true });
    for (const flag of mine) {
      const owner = owners.get(flag.flag);
      if (owner !== undefined) throw new ConcludeError(`settings "${owner}" and "${key}" both claim the CLI flag ${flag.flag}`);
      owners.set(flag.flag, key);
      flags.push(flag);
    }
  }
  return flags;
}

/**
 * The derived flags in the shape `node:util`'s `parseArgs` takes. A `bool`'s
 * negation is a boolean option of its own (`no-debug`); `parseCli` folds it back
 * into the setting, so use that rather than reading these options yourself.
 */
export function cliOptions(settings: readonly Setting[]): ParseArgsOptionsConfig {
  return Object.fromEntries(
    cliFlags(settings).map(({ flag, type, negated }) => [
      flag.slice(2),
      { type: negated || type === "bool" ? "boolean" : "string" } as const,
    ]),
  );
}

export interface ParsedCli {
  /** The CLI layer by canonical key: a `bool` as `true` (its flag) or `false` (its negation), anything else as raw text. Settings no flag mentioned are absent. */
  readonly cli: Record<string, unknown>;
  /** Everything `util.parseArgs` parsed, by flag name (setting flags, negations and any extra options). */
  readonly values: Record<string, string | boolean | (string | boolean)[] | undefined>;
  readonly positionals: string[];
}

/**
 * Parse `argv` with `node:util`'s `parseArgs`, strictly, and fold the result into
 * the CLI layer. The last flag given for a setting wins, a `bool`'s flag and its
 * negation included.
 */
export function parseCli(
  settings: readonly Setting[],
  argv: readonly string[],
  extra: { readonly options?: ParseArgsOptionsConfig; readonly allowPositionals?: boolean } = {},
): ParsedCli {
  const byName = new Map(cliFlags(settings).map((flag) => [flag.flag.slice(2), flag]));
  const { values, positionals, tokens } = parseArgs({
    args: [...argv],
    options: { ...extra.options, ...cliOptions(settings) },
    allowPositionals: extra.allowPositionals ?? true,
    strict: true,
    tokens: true,
  });
  const cli: Record<string, unknown> = {};
  for (const token of tokens) {
    if (token.kind !== "option") continue;
    const flag = byName.get(token.name);
    if (flag === undefined) continue; // an extra option, not a setting
    cli[flag.key] = flag.negated ? false : flag.type === "bool" ? true : token.value;
  }
  return { cli, values, positionals };
}
