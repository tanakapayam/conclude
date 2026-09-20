from pathlib import Path

from conclude.paths import default_config_home_path, default_config_system_path
from conclude.tomlwrite import toml_key, toml_string


def test_toml_string_escapes():
    assert toml_string("plain") == '"plain"'
    assert toml_string('has "quotes"') == '"has \\"quotes\\""'
    assert toml_string("back\\slash") == '"back\\\\slash"'
    assert toml_string("line\nbreak") == '"line\\nbreak"'
    assert toml_string("tab\there") == '"tab\\there"'


def test_toml_key_bare_when_valid():
    assert toml_key("africa") == "africa"
    assert toml_key("east-africa_2") == "east-africa_2"


def test_toml_key_quoted_when_needed():
    assert toml_key("has space") == '"has space"'
    assert toml_key("") == '""'


def test_default_config_home_path():
    path = default_config_home_path("myapp")
    assert path == Path.home() / ".config" / "myapp" / "config.toml"


def test_default_config_system_path():
    path = default_config_system_path("myapp")
    assert path == Path("/etc/myapp/config.toml")


def test_toml_string_escapes_other_control_characters():
    assert toml_string("a\x00b") == '"a\\u0000b"'
    assert toml_string("\x1b[0m") == '"\\u001B[0m"'
    assert toml_string("\x7f") == '"\\u007F"'
