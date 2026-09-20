/** Merging the layers (docs/concept.md, section 6). */

import { cast } from "./casters.ts";
import type { Layer, ResolvedValues, Setting } from "./types.ts";

/** The layers above the defaults, lowest priority first. `null` or absent means none. */
export interface Layers {
  readonly config?: Layer | null;
  readonly env?: Layer | null;
  readonly developer?: Layer | null;
  readonly cli?: Layer | null;
}

/**
 * Merge `defaults < config < env < developer < cli`, casting each value as it
 * lands. A `null` or absent value is no opinion; an empty string is a value.
 * Keys no setting declares are ignored. Throws a `CastError` for a value that
 * does not cast, wherever it came from.
 */
export function resolve(settings: readonly Setting[], layers: Layers = {}): ResolvedValues {
  const byKey = new Map(settings.map((setting) => [setting.key, setting]));
  const merged = new Map<string, ReturnType<typeof cast>>();

  const apply = (layer: Layer | null | undefined): void => {
    if (!layer) return;
    for (const key of Object.keys(layer)) {
      const setting = byKey.get(key);
      const value = layer[key];
      if (setting === undefined || value === null || value === undefined) continue;
      merged.set(key, cast(setting.type, value));
    }
  };

  apply(Object.fromEntries(settings.map((setting) => [setting.key, setting.default ?? null])));
  apply(layers.config);
  apply(layers.env);
  apply(layers.developer);
  apply(layers.cli);

  return Object.fromEntries(settings.map((setting) => [setting.key, merged.get(setting.key) ?? null]));
}
