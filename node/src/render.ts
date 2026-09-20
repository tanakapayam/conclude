/**
 * Rendering a default as text, an `.env` value or a TOML value
 * (docs/concept.md, section 11).
 */

import type { SettingType, SettingValue } from "./types.ts";

/** A float is written with a decimal point even when whole (`3.0`). */
function floatText(value: number): string {
  return Number.isInteger(value) && Math.abs(value) < 1e15 ? value.toFixed(1) : String(value);
}

/** A default as unquoted text, or `null` for "no value". */
export function plainText(type: SettingType, value: SettingValue | null): string | null {
  if (value === null) return null;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(",");
  if (type === "float" && typeof value === "number") return floatText(value);
  return String(value);
}

const ENV_BARE = /^[\p{L}\p{N}_./:@%+,-]*$/u;
const ENV_ESCAPES: Readonly<Record<string, string>> = {
  "\\": "\\\\",
  '"': '\\"',
  "\n": "\\n",
  "\t": "\\t",
  "\r": "\\r",
};

/** The right-hand side of a `NAME=value` line that reads back as exactly `text`. */
export function envValue(text: string): string {
  if (ENV_BARE.test(text)) return text;
  if (!text.includes("'") && !/[\n\t\r]/.test(text)) return `'${text}'`;
  return `"${Array.from(text, (ch) => ENV_ESCAPES[ch] ?? ch).join("")}"`;
}

/** `text` as a double-quoted TOML basic string. */
export function tomlString(text: string): string {
  const escaped = text
    .replaceAll("\\", "\\\\")
    .replaceAll('"', '\\"')
    .replaceAll("\n", "\\n")
    .replaceAll("\t", "\\t")
    .replaceAll("\r", "\\r")
    // Every other control character (and DEL) is illegal unescaped in TOML.
    .replace(/[\u0000-\u001f\u007f]/g, (ch) => {
      return `\\u${ch.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}`;
    });
  return `"${escaped}"`;
}

/** A TOML key: bare if it can be, quoted otherwise. */
export function tomlKey(key: string): string {
  return /^[A-Za-z0-9_-]+$/.test(key) ? key : tomlString(key);
}

/** A native TOML value for a default of the declared `type`. */
export function tomlValue(type: SettingType, value: SettingValue): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return `[${value.map(tomlString).join(", ")}]`;
  if (typeof value === "number") return type === "float" ? floatText(value) : String(value);
  return tomlString(value);
}
