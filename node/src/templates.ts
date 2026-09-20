/** Generated environment, TOML and CLI templates (docs/concept.md, section 11). */

import { cliFlagName, configKeyName, envVarName } from "./naming.ts";
import { envValue, plainText, tomlKey, tomlValue } from "./render.ts";
import type { Setting, SettingValue } from "./types.ts";

export interface TemplateOptions {
  /** The application name: the env var prefix and the default TOML table. */
  readonly appName: string;
  /** Keys to leave out. */
  readonly skip?: Iterable<string>;
  /** Effective defaults that replace the declared ones, by key. */
  readonly defaults?: Readonly<Record<string, SettingValue | null>>;
  /** Env var name overrides, by key. */
  readonly envVars?: Readonly<Record<string, string>>;
  /** TOML header: a name, a path for a nested table, or `[]` for none. */
  readonly table?: string | readonly string[];
  /** `false` drops the TOML header. */
  readonly header?: boolean;
  /** CLI metavar overrides, by key; an array makes several. */
  readonly metavars?: Readonly<Record<string, string | readonly string[]>>;
}

interface Row {
  readonly setting: Setting;
  readonly value: SettingValue | null;
}

function rows(settings: readonly Setting[], options: TemplateOptions): Row[] {
  const skip = new Set(options.skip ?? []);
  const overrides = options.defaults ?? {};
  return settings
    .filter((setting) => !skip.has(setting.key))
    .map((setting) => ({
      setting,
      value: Object.hasOwn(overrides, setting.key)
        ? (overrides[setting.key] ?? null)
        : (setting.default ?? null),
    }));
}

/** One `NAME=value` line per setting; `# NAME=` for one with no value. */
export function formatEnv(settings: readonly Setting[], options: TemplateOptions): string {
  const names = options.envVars ?? {};
  return rows(settings, options)
    .map(({ setting, value }) => {
      const name = Object.hasOwn(names, setting.key)
        ? (names[setting.key] as string)
        : envVarName(options.appName, setting.key);
      const text = plainText(setting.type, value);
      return text === null ? `# ${name}=` : `${name}=${envValue(text)}`;
    })
    .join("\n");
}

/** A `[table]` header and one `key = value` line per setting. */
export function formatToml(settings: readonly Setting[], options: TemplateOptions): string {
  const lines: string[] = [];
  if (options.header ?? true) {
    const path =
      options.table === undefined
        ? [options.appName]
        : typeof options.table === "string"
          ? [options.table]
          : [...options.table];
    if (path.length > 0) lines.push(`[${path.map(tomlKey).join(".")}]`);
  }
  for (const { setting, value } of rows(settings, options)) {
    const key = tomlKey(configKeyName(setting.key));
    lines.push(value === null ? `# ${key} =` : `${key} = ${tomlValue(setting.type, value)}`);
  }
  return lines.join("\n");
}

/** One aligned `--flag <METAVAR>  (default: ...)` line per setting. */
export function formatCli(settings: readonly Setting[], options: TemplateOptions): string {
  const metavars = options.metavars ?? {};
  const table = rows(settings, options).map(({ setting, value }) => {
    let flag = cliFlagName(setting.key);
    if (setting.type !== "bool") {
      const override = Object.hasOwn(metavars, setting.key) ? metavars[setting.key] : undefined;
      const names =
        override === undefined
          ? [setting.key.toUpperCase()]
          : typeof override === "string"
            ? [override]
            : [...override];
      flag += ` ${names.map((name) => `<${name}>`).join(" ")}`;
    }
    const text = plainText(setting.type, value);
    return { flag, text: text === null ? "none" : text === "" ? '""' : text };
  });
  const width = Math.max(0, ...table.map((row) => row.flag.length));
  return table.map(({ flag, text }) => `${flag.padEnd(width)} (default: ${text})`).join("\n");
}
