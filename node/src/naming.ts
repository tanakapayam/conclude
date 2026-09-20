/**
 * Each layer's conventional name for a setting, derived from the
 * application name and the setting's key (docs/concept.md, section 4).
 */

const NON_IDENTIFIER = /[^0-9a-zA-Z_]/gu;

function sanitize(text: string): string {
  return text.replace(NON_IDENTIFIER, "_");
}

/** `("remind", "retries")` is `"REMIND_RETRIES"`; `("my-app", "foo_bar")` is `"MY_APP_FOO_BAR"`. */
export function envVarName(appName: string, key: string): string {
  const name = `${sanitize(appName)}_${sanitize(key)}`.toUpperCase();
  return /^[0-9]/.test(name) ? `_${name}` : name;
}

/** `"filter_col"` is `"--filter-col"`. */
export function cliFlagName(key: string): string {
  return `--${key.replaceAll("_", "-")}`;
}

/** The config-file key is the key itself. */
export function configKeyName(key: string): string {
  return key;
}
