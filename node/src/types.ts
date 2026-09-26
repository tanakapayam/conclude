/** The declared types (see docs/concept.md, section 3). */
export type SettingType = "bool" | "int" | "float" | "str" | "list";

/** A value a setting can hold once resolved. */
export type SettingValue = boolean | number | string | string[];

/**
 * One declared setting: a key, a type, and a default. A missing or `null`
 * default means the setting starts out unset.
 */
export interface Setting {
  readonly key: string;
  readonly type: SettingType;
  readonly default?: SettingValue | null;
}

/** Raw values from one layer, by key. A `null` or absent value is "no opinion". */
export type Layer = Readonly<Record<string, unknown>>;

/** Fully resolved settings by canonical key; a setting nothing set is `null`. */
export type ResolvedValues = Record<string, SettingValue | null>;
