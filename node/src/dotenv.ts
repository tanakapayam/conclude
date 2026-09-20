/** The `.env` dialect (docs/concept.md, section 8). */

import { existsSync, readFileSync, statSync } from "node:fs";

import { decodeBackslashEscapes } from "./casters.ts";

/** Parse `.env` text (a leading byte-order mark is ignored) into `{ NAME: value }`. */
export function parseDotenv(text: string): Record<string, string> {
  const result: Record<string, string> = Object.create(null) as Record<string, string>;
  const source = text.startsWith("\uFEFF") ? text.slice(1) : text;
  for (const rawLine of source.split(/\r\n|\n|\r/)) {
    let line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    if (line.startsWith("export ")) line = line.slice("export ".length).trim();
    const equals = line.indexOf("=");
    if (equals === -1) continue;
    const key = line.slice(0, equals).trim();
    let value = line.slice(equals + 1).trim();
    const quote = value.charAt(0);
    if (value.length >= 2 && (quote === '"' || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1);
      if (quote === '"') value = decodeBackslashEscapes(value);
    }
    result[key] = value;
  }
  return { ...result };
}

/** Read a `.env` file as UTF-8, whatever the platform; `{}` if it does not exist. */
export function loadDotenv(path: string): Record<string, string> {
  if (!existsSync(path) || !statSync(path).isFile()) return {};
  return parseDotenv(readFileSync(path, "utf8"));
}
