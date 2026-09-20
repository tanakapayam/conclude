/**
 * `defineConfig`: declare settings once, then resolve every layer into one
 * typed settings object (docs/node/guide.md).
 */

import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import type { ParseArgsOptionsConfig } from "node:util";

import { ConfigFileError, SetupError } from "./errors.ts";
import { loadDotenv } from "./dotenv.ts";
import {
  DEFAULT_AUX_PATTERN,
  loadConfigFile,
  loadConfigFiles,
  resolveConfigTable,
} from "./config.ts";
import { resolve as resolveLayers } from "./merge.ts";
import { cliFlagName, envVarName } from "./naming.ts";
import { developerStatus, dotenvStatus, formatDeveloperStatus, formatDotenvStatus } from "./local.ts";
import type { DeveloperStatus, DotenvStatus } from "./local.ts";
import { normalize } from "./settings.ts";
import type { Declarations, Resolved } from "./settings.ts";
import { formatCli, formatEnv, formatToml } from "./templates.ts";
import type { TemplateOptions } from "./templates.ts";
import type { Layer, SettingValue } from "./types.ts";

/** "Use the conventional default for this path" -- distinct from `undefined` and from `null` (off). */
export const AUTO: unique symbol = Symbol("conclude.AUTO");

/** A path option: a path, {@link AUTO} for the conventional one, or `null` for off. */
export type PathOption = string | typeof AUTO | null;

export interface ConfigOptions<S extends Declarations> {
  /** The application name: the env var prefix, the default TOML table, and default file locations. */
  readonly name: string;
  /** The declarations: each value is a default (or a `int()`/`float()`/... spec). */
  readonly settings: S;
  /** Environment variable names, where the derived one is not wanted. */
  readonly envVars?: Readonly<Partial<Record<keyof S & string, string>>>;
  /** The TOML table config files are read from (default: `name`). */
  readonly defaultTable?: string;

  /** `~/.config/<name>/config.toml`. On by default; `null` turns it off. */
  readonly userConfigPath?: PathOption;
  /** `./.config.toml`. On by default; `null` turns it off, and its siblings with it. */
  readonly projectConfigPath?: PathOption;
  /** Sibling files merged after the project file (default `.config.*.toml`); `null` drops just those. */
  readonly projectAuxPattern?: string | null;
  /** `/etc/<name>/config.toml`. Off by default: {@link AUTO} or a path opts in. */
  readonly systemConfigPath?: PathOption;
  /** A `.env` fallback beneath the real environment. Off by default: {@link AUTO} (`./.env`) or a path opts in. */
  readonly dotenvPath?: PathOption;
  /** Read `.env` only if it is gitignored (needs the optional `ignore` package). */
  readonly dotenvRequireGitignored?: boolean;
  /** The `package.json` naming a private developer config file. Off by default: {@link AUTO} (`./package.json`) or a path opts in. */
  readonly manifestPath?: PathOption;
}

export interface ResolveOptions<S extends Declarations> {
  /** Parsed CLI values, by declared key. `undefined` or `null` is no opinion. */
  readonly cli?: Readonly<Partial<Record<keyof S & string, unknown>>>;
  /** Where to read the environment from (default: `process.env`). */
  readonly environ?: Readonly<Record<string, string | undefined>>;
  /** An explicit config-table selection (say, from a `--config` flag): `PARENT` or `PARENT.CHILD`. */
  readonly configValue?: string | null;
  /** A positional shorthand, looked up as a table in the config files. */
  readonly shorthand?: string | null;
}

export interface FormatOptions<S extends Declarations> {
  /** Settings to leave out. */
  readonly skip?: readonly (keyof S & string)[];
  /** Effective defaults to show instead of the declared ones. */
  readonly defaults?: Readonly<Partial<Record<keyof S & string, SettingValue | null>>>;
}

export interface TomlFormatOptions<S extends Declarations> extends FormatOptions<S> {
  /** The TOML header: a name, a path for a nested table, or `[]` for none. */
  readonly table?: string | readonly string[];
  /** `false` drops the header. */
  readonly header?: boolean;
}

export interface CliFormatOptions<S extends Declarations> extends FormatOptions<S> {
  /** Metavar overrides (a list makes several). */
  readonly metavars?: Readonly<Partial<Record<keyof S & string, string | readonly string[]>>>;
}

export interface ParsedArgs<S extends Declarations> {
  /** The CLI layer: the setting flags that were given, by declared key. */
  readonly cli: Partial<Record<keyof S & string, unknown>>;
  /** Everything `util.parseArgs` parsed, by flag name (setting flags and any extra options). */
  readonly values: Record<string, string | boolean | (string | boolean)[] | undefined>;
  readonly positionals: string[];
}

export interface Config<S extends Declarations> {
  readonly name: string;
  /** The environment variable each setting reads. */
  readonly envVarNames: Readonly<Record<keyof S & string, string>>;
  /** Merge every layer -- `defaults < system < user < project < env < developer < CLI` -- into one settings object. */
  resolve(options?: ResolveOptions<S>): Resolved<S>;
  /** Where the developer layer stands, and why. Never throws. */
  developerStatus(environ?: Readonly<Record<string, string | undefined>>): DeveloperStatus;
  /** Where the `.env` fallback stands, and why. Never throws. */
  dotenvStatus(): DotenvStatus;
  /** Which sources are in play, lowest priority first, for `--help`. */
  describeSources(environ?: Readonly<Record<string, string | undefined>>): string;
  /** An environment-variable template with the defaults filled in. */
  formatEnv(options?: FormatOptions<S>): string;
  /** A config-file template. */
  formatToml(options?: TomlFormatOptions<S>): string;
  /** A CLI reference, one aligned line per flag. */
  formatCli(options?: CliFormatOptions<S>): string;
  /** The derived flags in the shape `node:util`'s `parseArgs` takes (`filterCol` is `filter-col`). */
  cliOptions(): ParseArgsOptionsConfig;
  /** Parse arguments with `node:util`'s `parseArgs`: the derived flags plus any `extra` options. */
  parseArgs(argv?: readonly string[], extra?: { readonly options?: ParseArgsOptionsConfig; readonly allowPositionals?: boolean }): ParsedArgs<S>;
}

type Environ = Readonly<Record<string, string | undefined>>;

function pathOption(value: PathOption | undefined, auto: string | null, unset: string | null): string | null {
  if (value === undefined) return unset;
  return value === AUTO ? auto : value;
}

export function defineConfig<S extends Declarations>(options: ConfigOptions<S>): Config<S> {
  const { name } = options;
  if (typeof name !== "string" || name === "") throw new TypeError("defineConfig: name must be a non-empty string");
  const { settings, apiKeys, canonicalKeys } = normalize(options.settings);

  const userPath = pathOption(options.userConfigPath, join(homedir(), ".config", name, "config.toml"), join(homedir(), ".config", name, "config.toml"));
  const projectPath = pathOption(options.projectConfigPath, ".config.toml", ".config.toml");
  const auxPattern = options.projectAuxPattern === undefined ? DEFAULT_AUX_PATTERN : options.projectAuxPattern;
  const systemPath = pathOption(options.systemConfigPath, join("/etc", name, "config.toml"), null);
  const dotenvPath = pathOption(options.dotenvPath, ".env", null);
  const requireGitignored = options.dotenvRequireGitignored ?? false;
  const manifestPath = pathOption(options.manifestPath, "package.json", null);
  const defaultTable = options.defaultTable ?? name;

  // The environment variable each setting reads (canonical key -> name).
  const overrides = new Map<string, string>();
  for (const [apiKey, envName] of Object.entries(options.envVars ?? {})) {
    const canonical = canonicalKeys.get(apiKey);
    if (canonical === undefined) throw new TypeError(`envVars names "${apiKey}", which is not a declared setting`);
    if (typeof envName === "string") overrides.set(canonical, envName);
  }
  const envNames = new Map(settings.map((s) => [s.key, overrides.get(s.key) ?? envVarName(name, s.key)]));
  const killSwitchVar = envVarName(name, "developer_config");

  const toCanonical = (layer: Readonly<Record<string, unknown>> | undefined): Layer => {
    const out: Record<string, unknown> = {};
    for (const [apiKey, value] of Object.entries(layer ?? {})) {
      const canonical = canonicalKeys.get(apiKey);
      if (canonical !== undefined) out[canonical] = value;
    }
    return out;
  };
  const toApi = (canonicalKeyed: Readonly<Record<string, unknown>>): Record<string, unknown> =>
    Object.fromEntries(settings.map((s) => [apiKeys.get(s.key) as string, canonicalKeyed[s.key]]));
  const canonicalList = (keys: readonly string[] | undefined): string[] | undefined =>
    keys?.map((key) => canonicalKeys.get(key) ?? key);
  const canonicalMap = <T>(map: Readonly<Record<string, T | undefined>> | undefined): Record<string, T> | undefined => {
    if (map === undefined) return undefined;
    const out: Record<string, T> = {};
    for (const [key, value] of Object.entries(map)) {
      if (value !== undefined) out[canonicalKeys.get(key) ?? key] = value;
    }
    return out;
  };

  const status = (environ: Environ): DeveloperStatus => developerStatus(manifestPath, { killSwitchVar, environ });

  const activeDotenv = (): Record<string, string> => {
    const dotenv = dotenvStatus(dotenvPath, requireGitignored);
    if (dotenv.setupError) throw new SetupError(`.env file ${dotenv.path}: ${dotenv.reason}`);
    return dotenv.active && dotenv.path !== null ? loadDotenv(dotenv.path) : {};
  };

  const envLayer = (environ: Environ, dotenv: Readonly<Record<string, string>>): Layer => {
    const layer: Record<string, string> = {};
    for (const s of settings) {
      const envName = envNames.get(s.key) as string;
      const value = environ[envName] ?? (Object.hasOwn(dotenv, envName) ? dotenv[envName] : undefined);
      if (value !== undefined) layer[s.key] = value;
    }
    return layer;
  };

  const developerLayer = (tablePath: readonly string[], environ: Environ): Layer => {
    const developer = status(environ);
    if (developer.setupError) throw new SetupError(`developer config file ${developer.path}: ${developer.reason}`);
    if (!developer.active || developer.path === null) return {};
    if (developer.format === "dotenv") {
      const values = loadDotenv(developer.path);
      const layer: Record<string, string> = {};
      for (const s of settings) {
        const envName = envNames.get(s.key) as string;
        if (Object.hasOwn(values, envName)) layer[s.key] = values[envName] as string;
      }
      return layer;
    }
    try {
      return loadConfigFile(developer.path, settings, tablePath);
    } catch (error) {
      if (error instanceof ConfigFileError) throw new ConfigFileError(`developer config file ${error.message}`);
      throw error;
    }
  };

  const templateOptions = (format: FormatOptions<S>): TemplateOptions => {
    const skip = canonicalList(format.skip);
    const defaults = canonicalMap(format.defaults as Readonly<Record<string, SettingValue | null | undefined>> | undefined);
    return {
      appName: name,
      envVars: Object.fromEntries(overrides),
      table: defaultTable,
      ...(skip ? { skip } : {}),
      ...(defaults ? { defaults } : {}),
    };
  };

  const cliOptions = (): ParseArgsOptionsConfig =>
    Object.fromEntries(
      settings.map((s) => [cliFlagName(s.key).slice(2), { type: s.type === "bool" ? "boolean" : "string" } as const]),
    );

  return {
    name,
    envVarNames: Object.fromEntries(settings.map((s) => [apiKeys.get(s.key) as string, envNames.get(s.key) as string])) as Readonly<Record<keyof S & string, string>>,

    resolve(resolveOptions = {}) {
      const environ = resolveOptions.environ ?? process.env;
      const tablePath = resolveConfigTable({
        system: systemPath,
        user: userPath,
        project: projectPath,
        auxPattern,
        configValue: resolveOptions.configValue ?? null,
        shorthand: resolveOptions.shorthand ?? null,
        defaultTable,
      });
      const resolved = resolveLayers(settings, {
        config: loadConfigFiles({ system: systemPath, user: userPath, project: projectPath, auxPattern }, settings, tablePath),
        env: envLayer(environ, activeDotenv()),
        developer: developerLayer(tablePath, environ),
        cli: toCanonical(resolveOptions.cli),
      });
      return toApi(resolved) as Resolved<S>;
    },

    developerStatus: (environ = process.env) => status(environ),
    dotenvStatus: () => dotenvStatus(dotenvPath, requireGitignored),

    describeSources(environ = process.env) {
      let project = "disabled";
      if (projectPath !== null) {
        project = projectPath;
        if (auxPattern !== null) project += `, ${join(dirname(projectPath), auxPattern)}`;
      }
      const rows: [string, string][] = [
        ["system config", systemPath ?? "disabled"],
        ["user config", userPath ?? "disabled"],
        ["project config", project],
        [".env file", formatDotenvStatus(dotenvStatus(dotenvPath, requireGitignored))],
        ["developer config", formatDeveloperStatus(status(environ))],
      ];
      const width = Math.max(...rows.map(([label]) => label.length));
      return ["config sources:", ...rows.map(([label, value]) => `  ${label.padEnd(width)}  ${value}`)].join("\n");
    },

    formatEnv: (format = {}) => formatEnv(settings, templateOptions(format)),
    formatToml(format = {}) {
      const base = templateOptions(format);
      return formatToml(settings, {
        ...base,
        ...(format.table !== undefined ? { table: format.table } : {}),
        ...(format.header !== undefined ? { header: format.header } : {}),
      });
    },
    formatCli(format = {}) {
      const metavars = canonicalMap(format.metavars as Readonly<Record<string, string | readonly string[] | undefined>> | undefined);
      return formatCli(settings, { ...templateOptions(format), ...(metavars ? { metavars } : {}) });
    },

    cliOptions,

    parseArgs(argv = process.argv.slice(2), extra = {}) {
      const { values, positionals } = parseArgs({
        args: [...argv],
        options: { ...extra.options, ...cliOptions() },
        allowPositionals: extra.allowPositionals ?? true,
        strict: true,
      });
      const cli: Record<string, unknown> = {};
      for (const s of settings) {
        const value = values[cliFlagName(s.key).slice(2)];
        if (value !== undefined) cli[apiKeys.get(s.key) as string] = value;
      }
      return {
        cli: cli as Partial<Record<keyof S & string, unknown>>,
        values: values as ParsedArgs<S>["values"],
        positionals,
      };
    },
  };
}

