"""Deriving the conventional name for a setting in each layer -- its
CLI flag, its environment variable, its config-file key -- from its
Python name alone, so an application writes that name exactly once
(as a key in its defaults dict) instead of once per layer.
"""

import re

_NON_IDENTIFIER_CHARS = re.compile(r"[^0-9a-zA-Z_]")


def cli_flag_name(key: str) -> str:
    """``"filter_col"`` -> ``"--filter-col"``."""
    return "--" + key.replace("_", "-")


def env_var_name(app_name: str, key: str) -> str:
    """``("remind", "retries")`` -> ``"REMIND_RETRIES"``.

    A hyphen (or any other character that can't appear in a shell
    environment variable name) in either part is replaced with an
    underscore first -- e.g. ``("my-app", "foo_bar")`` ->
    ``"MY_APP_FOO_BAR"``, not the shell-illegal ``"MY-APP_FOO_BAR"``
    a bare ``.upper()`` would otherwise produce. Common for the app
    name in particular, since "my-app"-style hyphenated names are a
    normal CLI-tool naming convention that an app's own ``name`` is
    often taken straight from (e.g. its package name).

    A leading underscore is added if the result would otherwise start
    with a digit (``("123app", "foo")`` -> ``"_123APP_FOO"``, not the
    equally shell-illegal ``"123APP_FOO"`` -- a shell identifier can't
    start with a digit even though it can contain one).

    One thing this can't fix: two app names that only differ by which
    non-identifier character they use in the same position --
    ``"my-app"`` and ``"my_app"``, say -- sanitize to the *same* env
    var prefix. Not a concern for a single app calling this on its own
    name, but worth knowing if you're generating names for several
    apps at once.
    """
    name = f"{_sanitize(app_name)}_{_sanitize(key)}".upper()
    if name[:1].isdigit():
        name = f"_{name}"
    return name


def config_key_name(key: str) -> str:
    """The config-file key for ``key`` -- always just ``key`` itself,
    since a config file's keys already *are* your defaults dict's
    keys. Provided for symmetry with :func:`cli_flag_name`/
    :func:`env_var_name`, and so calling code never has to special-case
    "no translation needed" for this one layer.
    """
    return key


def _sanitize(text: str) -> str:
    return _NON_IDENTIFIER_CHARS.sub("_", text)
