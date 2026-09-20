"""Writing (not reading) small bits of TOML -- for an app feature like
"print me a ready-to-paste config entry for what I just set up".
"""

import re

_TOML_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOML_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def toml_string(s: str) -> str:
    """``s`` as a double-quoted TOML basic string, with the characters
    that need escaping there escaped.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    # Every other control character (and DEL) is illegal unescaped in a
    # TOML basic string.
    escaped = _TOML_CONTROL_RE.sub(lambda m: f"\\u{ord(m.group()):04X}", escaped)
    return f'"{escaped}"'


def toml_key(s: str) -> str:
    """A TOML table/key name for ``s`` -- bare if that's valid syntax
    (letters, digits, ``_``/``-``, non-empty), a quoted string key
    otherwise (TOML allows arbitrary quoted keys, e.g. one containing a
    space).
    """
    return s if _TOML_BARE_KEY_RE.match(s) else toml_string(s)
