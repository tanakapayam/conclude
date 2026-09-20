"""The conventional per-app config file locations."""

from pathlib import Path


def default_config_home_path(app_name: str) -> Path:
    """``~/.config/<app_name>/config.toml`` -- the usual user-global
    config file location (XDG-style, minus actually honoring
    ``$XDG_CONFIG_HOME``; pass your own path to the loading functions
    instead if your app needs that).
    """
    return Path.home() / ".config" / app_name / "config.toml"


def default_config_system_path(app_name: str) -> Path:
    """``/etc/<app_name>/config.toml`` -- the conventional system-wide
    config file location, shared by every user on the machine (the
    lowest-priority config file: any user-global, project-local, env,
    or CLI value overrides it).

    Unlike the user-global path this is never read unless the app opts
    in (``config_system_path=AUTO`` on :class:`conclude.App`), since
    silently picking up machine-wide configuration is a decision about
    the program, not something that should happen by default.
    """
    return Path("/etc") / app_name / "config.toml"
