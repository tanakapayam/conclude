/**
 * Turning a raw value from any layer into a setting's declared type
 * (docs/concept.md, section 5). A caster returns a value, returns `null`
 * for "unset", or throws a {@link CastError}; it never guesses.
 */

import { CastError } from "./errors.ts";
import type { SettingType, SettingValue } from "./types.ts";

const TRUE_TEXT = new Set(["1", "true", "yes", "on", "y"]);
const FALSE_TEXT = new Set(["0", "false", "no", "off", "n"]);

// A decimal or exponent number: no hex, no underscores, no `inf`/`nan`.
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function isUnset(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function show(value: unknown): string {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

export function castBool(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value !== "string" && typeof value !== "number") {
    throw new CastError(`expected a boolean, got ${show(value)}`);
  }
  const text = String(value).trim().toLowerCase();
  if (text === "") return false;
  if (TRUE_TEXT.has(text)) return true;
  if (FALSE_TEXT.has(text)) return false;
  throw new CastError(
    `expected a boolean (true/false/yes/no/on/off/1/0/y/n), got ${show(value)}`,
  );
}

/** A number (an integer when whole) or `null`. Serves both `int` and `float`. */
export function castNumber(value: unknown): number | null {
  if (isUnset(value)) return null;
  if (typeof value === "bigint") return Number(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new CastError(`expected a number, got ${show(value)}`);
    return value;
  }
  if (typeof value === "string") {
    const text = value.trim();
    if (NUMBER.test(text)) {
      const number = Number(text);
      if (Number.isFinite(number)) return number;
    }
  }
  throw new CastError(`expected a number, got ${show(value)}`);
}

export function castStr(value: unknown): string | null {
  if (isUnset(value)) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint") return String(value);
  throw new CastError(`expected text, got ${show(value)}`);
}

export function castList(value: unknown): string[] | null {
  if (isUnset(value)) return null;
  let parts: unknown[];
  if (Array.isArray(value)) {
    parts = value;
  } else if (typeof value === "string") {
    parts = value.split(",");
  } else {
    throw new CastError(`expected a list, got ${show(value)}`);
  }
  const items: string[] = [];
  for (const part of parts) {
    if (typeof part !== "string" && typeof part !== "number") {
      throw new CastError(`expected a list of text, got an item ${show(part)}`);
    }
    const item = String(part).trim();
    if (item !== "") items.push(item);
  }
  return items;
}

/** Cast `value` to the declared `type`. */
export function cast(type: SettingType, value: unknown): SettingValue | null {
  switch (type) {
    case "bool":
      return castBool(value);
    case "int":
    case "float":
      return castNumber(value);
    case "str":
      return castStr(value);
    case "list":
      return castList(value);
  }
}

const ESCAPES: Readonly<Record<string, string>> = {
  n: "\n",
  t: "\t",
  r: "\r",
  "\\": "\\",
  '"': '"',
};

/**
 * Decode just `\n`, `\t`, `\r`, `\\` and `\"`; every other character, and any
 * other backslash sequence, is left exactly as written.
 */
export function decodeBackslashEscapes(text: string): string {
  let result = "";
  for (let i = 0; i < text.length; i += 1) {
    const ch = text.charAt(i);
    const next = text.charAt(i + 1);
    if (ch === "\\" && next !== "" && Object.hasOwn(ESCAPES, next)) {
      result += ESCAPES[next];
      i += 1;
    } else {
      result += ch;
    }
  }
  return result;
}
