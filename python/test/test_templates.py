import argparse
import shlex
import tomllib
from pathlib import Path

import pytest

import conclude
from conclude import App, opt
from conclude.casters import cast_escaped_str
from conclude.env import load_dotenv
from conclude.templates import env_value, plain_text, toml_value

DEFAULTS = {
    "host": "localhost",
    "port": 8080,
    "debug": False,
    "timeout": 30,
}

TRICKY_STRINGS = [
    "plain",
    "hello world",
    "it's",
    'say "hi"',
    "a#b",
    "a=b",
    "tab\there",
    "line1\nline2",
    "back\\slash",
    "trailing\\",
    "  padded  ",
    "$HOME",
    "`cmd`",
    "'single'",
    '"double"',
    "both ' and \" and \n",
    "ünï cödé 日本語 🎉",
    "/usr/local/bin:/opt/x",
]


# --- plain_text ---------------------------------------------------------------


def test_plain_text_by_type():
    assert plain_text("localhost") == "localhost"
    assert plain_text(8080) == "8080"
    assert plain_text(0.5) == "0.5"
    assert plain_text(True) == "true"
    assert plain_text(False) == "false"
    assert plain_text(["a", "b"]) == "a,b"
    assert plain_text([]) == ""
    assert plain_text(None) is None


def test_plain_text_formatter_output_is_unquoted():
    assert plain_text("a b", lambda v: shlex.quote(v)) == "a b"
    assert plain_text("", lambda v: shlex.quote(v)) == ""
    assert plain_text(90, lambda v: f"{v}m") == "90m"


def test_plain_text_formatter_returning_none_is_no_value():
    assert plain_text(1, lambda v: None) is None


def test_plain_text_bool_ignores_cli_style_formatter():
    # The bare-flag/omitted shape of a bool's CLI formatter is meaningless
    # as text: a bool is always true/false.
    assert plain_text(True, conclude.formatters.format_bool) == "true"
    assert plain_text(False, conclude.formatters.format_bool) == "false"


# --- env_value ----------------------------------------------------------------


def test_env_value_bare_when_unremarkable():
    for text in ["localhost", "8080", "a,b", "/usr/bin", "x.y-z_1", "café", "", "50%"]:
        assert env_value(text) == text


def test_env_value_single_quoted_when_needed():
    assert env_value("hello world") == "'hello world'"
    assert env_value("$HOME") == "'$HOME'"
    assert env_value("a#b") == "'a#b'"
    assert env_value("back\\slash") == "'back\\slash'"


def test_env_value_double_quoted_for_quote_or_control_chars():
    assert env_value("it's") == '"it\'s"'
    assert env_value("a\nb") == '"a\\nb"'
    assert env_value('say "hi"\t') == '"say \\"hi\\"\\t"'


@pytest.mark.parametrize("text", TRICKY_STRINGS)
def test_env_value_round_trips_through_load_dotenv(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(f"KEY={env_value(text)}\n")
    assert load_dotenv(path) == {"KEY": text}


# --- toml_value ---------------------------------------------------------------


def test_toml_value_native_types():
    assert toml_value(True) == "true"
    assert toml_value(False) == "false"
    assert toml_value(8080) == "8080"
    assert toml_value(-3) == "-3"
    assert toml_value(0.5) == "0.5"
    assert toml_value("hi") == '"hi"'
    assert toml_value(["a", "b"]) == '["a", "b"]'
    assert toml_value([]) == "[]"
    assert toml_value([1, True, "x"]) == '[1, true, "x"]'


@pytest.mark.parametrize("value", [0.1, -2.5, 1e16, 1e-7, float("inf"), 3.0])
def test_toml_value_floats_round_trip(value):
    assert tomllib.loads(f"v = {toml_value(value)}")["v"] == value


@pytest.mark.parametrize("text", [*TRICKY_STRINGS, "\x00", "\x1b[0m", "\x7f", "a\x1fb"])
def test_toml_value_strings_round_trip(text):
    assert tomllib.loads(f"v = {toml_value(text)}")["v"] == text


# --- format_env ---------------------------------------------------------------


def test_format_env_basic():
    assert App("myapp", DEFAULTS).format_env() == (
        "MYAPP_HOST=localhost\nMYAPP_PORT=8080\nMYAPP_DEBUG=false\nMYAPP_TIMEOUT=30"
    )


def test_format_env_unset_is_commented_placeholder():
    app = App("myapp", {"host": "h", "filename": opt(str), "tags": opt(list)})
    assert app.format_env() == "MYAPP_HOST=h\n# MYAPP_FILENAME=\n# MYAPP_TAGS="


def test_format_env_uses_resolved_env_var_names():
    app = App("my-app", {"host": "h", "port": 1}, env_vars={"port": "PORT"})
    assert app.format_env() == "MY_APP_HOST=h\nPORT=1"


def test_format_env_skip_and_defaults_override():
    app = App("myapp", {"host": "h", "filename": opt(str), "port": 1})
    out = app.format_env(skip={"port"}, defaults={"filename": "~/.myapp.csv"})
    assert out == "MYAPP_HOST=h\nMYAPP_FILENAME='~/.myapp.csv'"


def test_format_env_defaults_override_unwraps_opt_and_ignores_unknown_keys():
    app = App("myapp", {"filename": opt(str)})
    assert app.format_env(defaults={"filename": opt(str), "nope": 1}) == "# MYAPP_FILENAME="


def test_format_env_no_settings_is_empty_string():
    assert App("myapp", DEFAULTS).format_env(skip=DEFAULTS) == ""


def test_format_env_default_that_is_empty_string():
    assert App("myapp", {"sep": ""}).format_env() == "MYAPP_SEP="


def test_format_env_does_not_need_an_inferred_formatter():
    # A default of a type with no built-in formatter is fine as long as
    # its caster handles the text -- unlike format_invocation, which
    # needs a formatter for every setting.
    app = App("myapp", {"path": Path("/a b")}, casters={"path": Path})
    assert app.format_env() == "MYAPP_PATH='/a b'"


def test_format_env_round_trips_through_the_env_layer(tmp_path):
    defaults = {
        "host": "localhost",
        "port": 8080,
        "ratio": 0.25,
        "debug": True,
        "quiet": False,
        "tags": ["a", "b"],
        "filename": opt(str),
        "limit": opt(int),
    }
    dotenv = tmp_path / ".env"
    app = App("myapp", defaults, dotenv_path=dotenv)
    dotenv.write_text(app.format_env() + "\n")
    env = app.load_env(environ={})
    assert app.resolve({}, env=env, config_file={}) == app.resolved_defaults


@pytest.mark.parametrize("text", TRICKY_STRINGS)
def test_format_env_round_trips_tricky_strings(tmp_path, text):
    dotenv = tmp_path / ".env"
    app = App("myapp", {"v": text}, dotenv_path=dotenv)
    dotenv.write_text(app.format_env() + "\n")
    env = app.load_env(environ={})
    assert app.resolve({}, env=env, config_file={}) == {"v": text}


# --- format_toml --------------------------------------------------------------


def test_format_toml_basic():
    assert App("myapp", DEFAULTS).format_toml() == (
        '[myapp]\nhost = "localhost"\nport = 8080\ndebug = false\ntimeout = 30'
    )


def test_format_toml_native_types_and_unset_placeholder():
    app = App("myapp", {"ratio": 0.5, "tags": ["a", "b"], "on": True, "filename": opt(str)})
    assert app.format_toml() == ('[myapp]\nratio = 0.5\ntags = ["a", "b"]\non = true\n# filename =')


def test_format_toml_table_argument():
    app = App("myapp", {"a": 1})
    assert app.format_toml(table="other").splitlines()[0] == "[other]"
    assert app.format_toml(table=["myapp", "deck"]).splitlines()[0] == "[myapp.deck]"
    assert app.format_toml(table="has space").splitlines()[0] == '["has space"]'
    assert app.format_toml(table=[]) == "a = 1"


def test_format_toml_uses_default_table_field():
    app = App("myapp", {"a": 1}, default_table="custom")
    assert app.format_toml().splitlines()[0] == "[custom]"


def test_format_toml_header_false_is_just_the_key_lines():
    assert App("myapp", DEFAULTS).format_toml(header=False) == (
        'host = "localhost"\nport = 8080\ndebug = false\ntimeout = 30'
    )


def test_format_toml_skip_and_defaults_override():
    app = App("myapp", {"host": "h", "filename": opt(str), "port": 1})
    out = app.format_toml(skip={"port"}, defaults={"filename": "x.csv"})
    assert out == '[myapp]\nhost = "h"\nfilename = "x.csv"'


def test_format_toml_no_settings_is_just_the_header():
    assert App("myapp", DEFAULTS).format_toml(skip=DEFAULTS) == "[myapp]"
    assert App("myapp", DEFAULTS).format_toml(skip=DEFAULTS, header=False) == ""


def test_format_toml_output_parses_to_the_defaults():
    defaults = {
        "host": "localhost",
        "port": 8080,
        "ratio": 0.25,
        "debug": True,
        "tags": ["a", "b"],
        "empty": [],
    }
    parsed = tomllib.loads(App("myapp", defaults).format_toml())
    assert parsed == {"myapp": defaults}


def test_format_toml_unset_placeholder_is_not_parsed_as_a_key():
    parsed = tomllib.loads(App("myapp", {"host": "h", "filename": opt(str)}).format_toml())
    assert parsed == {"myapp": {"host": "h"}}


@pytest.mark.parametrize("text", [*TRICKY_STRINGS, "\x00", "\x1b[0m", "a\x1fb"])
def test_format_toml_round_trips_through_the_config_file_layer(tmp_path, text):
    config = tmp_path / "config.toml"
    app = App("myapp", {"v": text}, config_home_path=config, config_cwd_path=None)
    config.write_text(app.format_toml() + "\n")
    assert app.resolve({}, env={}) == {"v": text}


def test_format_toml_full_round_trip_through_the_config_file_layer(tmp_path):
    defaults = {
        "host": "localhost",
        "port": 8080,
        "ratio": 0.25,
        "debug": True,
        "quiet": False,
        "tags": ["a", "b"],
        "filename": opt(str),
    }
    config = tmp_path / "config.toml"
    app = App("myapp", defaults, config_home_path=config, config_cwd_path=None)
    config.write_text(app.format_toml() + "\n")
    assert app.resolve({}, env={}) == app.resolved_defaults


# --- format_cli ---------------------------------------------------------------


def test_format_cli_matches_the_documented_shape():
    assert App("myapp", DEFAULTS).format_cli() == (
        "--host <HOST>       (default: localhost)\n"
        "--port <PORT>       (default: 8080)\n"
        "--debug             (default: false)\n"
        "--timeout <TIMEOUT> (default: 30)"
    )


def test_format_cli_no_trailing_whitespace_and_aligned():
    lines = App("myapp", DEFAULTS).format_cli().splitlines()
    assert all(line == line.rstrip() for line in lines)
    assert len({line.index("(default:") for line in lines}) == 1


def test_format_cli_flag_names_and_metavars_follow_inference():
    app = App("myapp", {"filter_col": "x", "on": opt(bool)})
    assert app.format_cli() == (
        "--filter-col <FILTER_COL> (default: x)\n--on                      (default: none)"
    )


def test_format_cli_none_and_empty_defaults():
    app = App("myapp", {"filename": opt(str), "sep": "", "tags": []})
    assert app.format_cli() == (
        "--filename <FILENAME> (default: none)\n"
        '--sep <SEP>           (default: "")\n'
        '--tags <TAGS>         (default: "")'
    )


def test_format_cli_list_default_is_comma_joined():
    assert App("myapp", {"tags": ["a", "b"]}).format_cli() == "--tags <TAGS> (default: a,b)"


def test_format_cli_metavar_override():
    app = App("myapp", {"filename": "x.csv", "pair": "a", "debug": False})
    out = app.format_cli(
        overrides={
            "filename": {"metavar": "FILE", "help": "ignored"},
            "pair": {"metavar": ("A", "B")},
        }
    )
    assert out == (
        "--filename <FILE> (default: x.csv)\n"
        "--pair <A> <B>    (default: a)\n"
        "--debug           (default: false)"
    )


def test_format_cli_skip_and_defaults_override():
    app = App("myapp", {"host": "h", "filename": opt(str), "port": 1})
    out = app.format_cli(skip={"port"}, defaults={"filename": "x.csv"})
    assert out == "--host <HOST>         (default: h)\n--filename <FILENAME> (default: x.csv)"


def test_format_cli_no_settings_is_empty_string():
    assert App("myapp", DEFAULTS).format_cli(skip=DEFAULTS) == ""


def test_format_cli_lists_exactly_the_flags_add_arguments_adds():
    app = App("myapp", {**DEFAULTS, "filter_col": opt(str), "tags": ["a"]})
    parser = app.build_arg_parser()
    for line in app.format_cli().splitlines():
        flag = line.split()[0]
        is_bool = "<" not in line.split("(default")[0]
        parser.parse_args([flag] if is_bool else [flag, "x"])  # exits if unknown
    assert len(app.format_cli().splitlines()) == len(DEFAULTS) + 2


def test_format_cli_flags_match_add_arguments_with_skip():
    app = App("myapp", DEFAULTS)
    parser = argparse.ArgumentParser()
    app.add_arguments(parser, skip={"port"})
    flags = {opt_str for action in parser._actions for opt_str in action.option_strings}
    listed = {line.split()[0] for line in app.format_cli(skip={"port"}).splitlines()}
    assert listed <= flags
    assert "--port" not in listed


# --- custom formatter/caster pairs ---------------------------------------------


def cast_duration(value):
    text = str(value).strip()
    if text.endswith("h"):
        return int(text[:-1]) * 60
    return int(text.removesuffix("m"))


def format_duration(value):
    return f"{value // 60}h" if value % 60 == 0 else f"{value}m"


def format_escaped(value):
    return shlex.quote(value.replace("\\", "\\\\").replace("\n", "\\n"))


def custom_app(**kwargs):
    return App(
        "myapp",
        {"delay": 90, "sep": "\n\n"},
        casters={"delay": cast_duration, "sep": cast_escaped_str},
        formatters={"delay": format_duration, "sep": format_escaped},
        **kwargs,
    )


def test_custom_formatter_is_used_by_all_three_templates():
    app = custom_app()
    assert app.format_env() == "MYAPP_DELAY=90m\nMYAPP_SEP='\\n\\n'"
    assert app.format_toml() == '[myapp]\ndelay = "90m"\nsep = "\\\\n\\\\n"'
    assert app.format_cli() == "--delay <DELAY> (default: 90m)\n--sep <SEP>     (default: \\n\\n)"


def test_custom_formatter_env_round_trip(tmp_path):
    dotenv = tmp_path / ".env"
    app = custom_app(dotenv_path=dotenv)
    dotenv.write_text(app.format_env() + "\n")
    env = app.load_env(environ={})
    assert app.resolve({}, env=env, config_file={}) == {"delay": 90, "sep": "\n\n"}


def test_custom_formatter_toml_round_trip(tmp_path):
    config = tmp_path / "config.toml"
    app = custom_app(config_home_path=config, config_cwd_path=None)
    config.write_text(app.format_toml() + "\n")
    assert app.resolve({}, env={}) == {"delay": 90, "sep": "\n\n"}


def test_formatters_argument_replaces_the_apps_own_formatters():
    app = custom_app()
    out = app.format_env(formatters={"delay": lambda v: f"{v}min"})
    # 'delay' uses the call's formatter; 'sep' has no explicit formatter
    # in this call, so it renders from its plain value (a real newline
    # pair) instead, double-quoted with escapes.
    assert out == 'MYAPP_DELAY=90min\nMYAPP_SEP="\\n\\n"'
