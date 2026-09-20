/**
 * Declaring settings (docs/node/guide.md): a plain object whose values are
 * the defaults, with helpers for the types a bare value cannot express.
 */

import type { Setting, SettingType, SettingValue } from "./types.ts";

/** A declared setting: its type and default. Built by {@link bool}, {@link int}, {@link float}, {@link str} and {@link list}. */
export interface Spec<T = SettingValue | null> {
  readonly type: SettingType;
  readonly default: SettingValue | null;
  /** Type-level only: the value the setting resolves to. */
  readonly __value?: T;
}

/**
 * What a declaration may hold: a `boolean`, `string` or `string[]` shorthand
 * for `bool(...)`, `str(...)` and `list(...)`, or a {@link Spec}. A bare
 * number is deliberately not allowed -- JavaScript cannot tell `3` from `3.0`,
 * so say `int(3)` or `float(3)`.
 */
export type Declared = boolean | string | readonly string[] | Spec;

export type Declarations = Readonly<Record<string, Declared>>;

/** The value a declaration resolves to. */
export type ValueOf<D> =
  D extends Spec<infer T>
    ? T
    : D extends boolean
      ? boolean
      : D extends string
        ? string
        : D extends readonly string[]
          ? string[]
          : never;

/** The resolved settings for a set of declarations, keyed as declared. */
export type Resolved<S extends Declarations> = { -readonly [K in keyof S]: ValueOf<S[K]> };

function spec(type: SettingType, defaultValue: SettingValue | undefined): Spec {
  return { type, default: defaultValue === undefined ? null : defaultValue };
}

/** A flag. `bool()` with no default starts out unset. */
export function bool(): Spec<boolean | null>;
export function bool(defaultValue: boolean): Spec<boolean>;
export function bool(defaultValue?: boolean): Spec {
  if (defaultValue !== undefined && typeof defaultValue !== "boolean") {
    throw new TypeError(`bool() takes a boolean default, got ${String(defaultValue)}`);
  }
  return spec("bool", defaultValue);
}

/** A number that is an integer when whole (a fraction is accepted). */
export function int(): Spec<number | null>;
export function int(defaultValue: number): Spec<number>;
export function int(defaultValue?: number): Spec {
  if (defaultValue !== undefined && !Number.isFinite(defaultValue)) {
    throw new TypeError(`int() takes a finite number default, got ${String(defaultValue)}`);
  }
  return spec("int", defaultValue);
}

/** A number. Templates write a whole default with a decimal point (`3.0`). */
export function float(): Spec<number | null>;
export function float(defaultValue: number): Spec<number>;
export function float(defaultValue?: number): Spec {
  if (defaultValue !== undefined && !Number.isFinite(defaultValue)) {
    throw new TypeError(`float() takes a finite number default, got ${String(defaultValue)}`);
  }
  return spec("float", defaultValue);
}

/** Text. `str()` with no default starts out unset. */
export function str(): Spec<string | null>;
export function str(defaultValue: string): Spec<string>;
export function str(defaultValue?: string): Spec {
  if (defaultValue !== undefined && typeof defaultValue !== "string") {
    throw new TypeError(`str() takes a string default, got ${String(defaultValue)}`);
  }
  return spec("str", defaultValue);
}

/** A list of text items. `list()` with no default starts out unset. */
export function list(): Spec<string[] | null>;
export function list(defaultValue: readonly string[]): Spec<string[]>;
export function list(defaultValue?: readonly string[]): Spec {
  if (defaultValue !== undefined && !(Array.isArray(defaultValue) && defaultValue.every((item) => typeof item === "string"))) {
    throw new TypeError("list() takes an array of strings as its default");
  }
  return spec("list", defaultValue === undefined ? undefined : [...defaultValue]);
}

/**
 * The canonical (`snake_case`) form of an API key, used in config files, the
 * environment and CLI flags (docs/concept.md, decision D1):
 * `filterCol` is `filter_col`, `apiURL` is `api_url`.
 */
export function toCanonicalKey(key: string): string {
  return key
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase();
}

const KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

export interface Normalized {
  /** The settings in canonical form, in declaration order. */
  readonly settings: readonly Setting[];
  /** API key by canonical key. */
  readonly apiKeys: ReadonlyMap<string, string>;
  /** Canonical key by API key. */
  readonly canonicalKeys: ReadonlyMap<string, string>;
}

function isSpec(value: unknown): value is Spec {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    "default" in value &&
    typeof (value as { type: unknown }).type === "string"
  );
}

/** Turn declarations into canonical settings and the key maps between the two spellings. */
export function normalize(declarations: Declarations): Normalized {
  const settings: Setting[] = [];
  const apiKeys = new Map<string, string>();
  const canonicalKeys = new Map<string, string>();
  for (const [apiKey, declared] of Object.entries(declarations)) {
    if (!KEY.test(apiKey)) {
      throw new TypeError(`setting key "${apiKey}" must be an identifier (letters, digits and _)`);
    }
    const canonical = toCanonicalKey(apiKey);
    const clash = apiKeys.get(canonical);
    if (clash !== undefined) {
      throw new TypeError(`settings "${clash}" and "${apiKey}" are both "${canonical}" in files, the environment and flags`);
    }
    let resolved: Spec;
    if (typeof declared === "boolean") resolved = bool(declared);
    else if (typeof declared === "string") resolved = str(declared);
    else if (Array.isArray(declared)) resolved = list(declared as readonly string[]);
    else if (isSpec(declared)) resolved = declared;
    else if (typeof declared === "number") {
      throw new TypeError(`setting "${apiKey}": declare numbers with int() or float(), e.g. ${apiKey}: int(${declared})`);
    } else {
      throw new TypeError(`setting "${apiKey}" is not a boolean, string, string[] or int()/float()/bool()/str()/list() declaration`);
    }
    settings.push({ key: canonical, type: resolved.type, default: resolved.default });
    apiKeys.set(canonical, apiKey);
    canonicalKeys.set(apiKey, canonical);
  }
  return { settings, apiKeys, canonicalKeys };
}
