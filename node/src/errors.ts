/** Base class for every error conclude raises on purpose. */
export class ConcludeError extends Error {
  override name = "ConcludeError";
}

/** A raw value could not be cast to its setting's declared type. */
export class CastError extends ConcludeError {
  override name = "CastError";
}

/** A config file exists but is not valid TOML. */
export class ConfigFileError extends ConcludeError {
  override name = "ConfigFileError";
}

/** A config table selection is malformed (`a..b`, `a.b.c`, ...). */
export class ConfigTableError extends ConcludeError {
  override name = "ConfigTableError";
}

/** An optional dependency needed for the requested feature is not installed. */
export class SetupError extends ConcludeError {
  override name = "SetupError";
}
