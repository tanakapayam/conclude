/**
 * The two private local files that go through the gitignore guard: the
 * developer config file and (optionally) a `.env` file (docs/concept.md,
 * sections 8-10).
 */

import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";

import { checkGuard } from "./guard.ts";

// --- the .env fallback ------------------------------------------------------------------

export type DotenvState = "disabled" | "active" | "inactive";

export interface DotenvStatus {
  readonly state: DotenvState;
  readonly path: string | null;
  /** Why `inactive`, in one short phrase. */
  readonly reason: string | null;
  /** Whether a gitignore guard was requested. */
  readonly guarded: boolean;
  /** The optional `ignore` package is missing: loading throws instead of skipping the file. */
  readonly setupError: boolean;
  readonly active: boolean;
}

export function dotenvStatus(path: string | null, requireGitignored: boolean): DotenvStatus {
  if (path === null) {
    return { state: "disabled", path: null, reason: null, guarded: false, setupError: false, active: false };
  }
  if (!requireGitignored) {
    return { state: "active", path, reason: null, guarded: false, setupError: false, active: true };
  }
  const result = checkGuard(path, { escapeHint: "or stop requiring it to be gitignored" });
  return {
    state: result.active ? "active" : "inactive",
    path,
    reason: result.reason,
    guarded: true,
    setupError: result.setupError,
    active: result.active,
  };
}

export function formatDotenvStatus(status: DotenvStatus): string {
  if (status.state === "disabled") return "disabled";
  if (status.state === "active") return status.guarded ? `${status.path} -- active (gitignored)` : `${status.path}`;
  return `${status.path} -- inactive (${status.reason})`;
}

// --- the developer layer ----------------------------------------------------------------

export type DeveloperState =
  | "not opted in"
  | "not configured"
  | "configured, inactive"
  | "configured, active";

export interface DeveloperStatus {
  readonly state: DeveloperState;
  /** The developer file, once the manifest names one. */
  readonly path: string | null;
  /** Why `not configured` or `configured, inactive`, in one short phrase. */
  readonly reason: string | null;
  /** The optional `ignore` package is missing: loading throws instead of skipping the file. */
  readonly setupError: boolean;
  /** How the file is read, decided by its name: `.toml` is TOML, anything else is dotenv. */
  readonly format: "toml" | "dotenv" | null;
  readonly active: boolean;
}

/** `"toml"` for a name ending in `.toml` (any case), `"dotenv"` for anything else. */
export function developerFileFormat(path: string): "toml" | "dotenv" {
  return path.toLowerCase().endsWith(".toml") ? "toml" : "dotenv";
}

function notConfigured(reason: string): DeveloperStatus {
  return { state: "not configured", path: null, reason, setupError: false, format: null, active: false };
}

function readConfiguredPath(manifestPath: string): { path: string } | { reason: string } {
  let manifest: unknown;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    const missing = (error as NodeJS.ErrnoException).code === "ENOENT";
    return { reason: missing ? `no ${manifestPath}` : `${manifestPath} is not readable JSON` };
  }
  const value = (manifest as { conclude?: { developer?: { config?: unknown } } } | null)?.conclude?.developer?.config;
  if (value === undefined) return { reason: `no conclude.developer.config in ${manifestPath}` };
  if (typeof value !== "string" || value.trim() === "") {
    return { reason: "conclude.developer.config must be a non-empty string" };
  }
  const relative = value.trim();
  return { path: isAbsolute(relative) ? relative : join(dirname(manifestPath), relative) };
}

export interface DeveloperOptions {
  /** The kill-switch variable, e.g. `MYAPP_DEVELOPER_CONFIG`. */
  readonly killSwitchVar: string;
  readonly environ: Readonly<Record<string, string | undefined>>;
}

export function developerStatus(manifestPath: string | null, options: DeveloperOptions): DeveloperStatus {
  if (manifestPath === null) {
    return { state: "not opted in", path: null, reason: null, setupError: false, format: null, active: false };
  }
  const configured = readConfiguredPath(manifestPath);
  if ("reason" in configured) return notConfigured(configured.reason);
  const { path } = configured;
  const result = checkGuard(path, { killSwitchVar: options.killSwitchVar, environ: options.environ });
  return {
    state: result.active ? "configured, active" : "configured, inactive",
    path,
    reason: result.reason,
    setupError: result.setupError,
    format: developerFileFormat(path),
    active: result.active,
  };
}

export function formatDeveloperStatus(status: DeveloperStatus): string {
  if (status.state === "not opted in") return status.state;
  if (status.state === "not configured") return status.reason ? `${status.state} (${status.reason})` : status.state;
  const detail = status.state === "configured, inactive" ? ` (${status.reason})` : "";
  return `${status.path} -- ${status.state}${detail}`;
}
