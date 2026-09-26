from conclude.casters import cast_bool, cast_int_or_none, cast_str_or_none
from conclude.merge import resolve

DEFAULTS = {"name": None, "count": 1, "loud": False}
CASTERS = {"name": cast_str_or_none, "count": cast_int_or_none, "loud": cast_bool}


def test_defaults_only():
    merged = resolve({}, {}, {}, DEFAULTS, CASTERS)
    assert merged == {"name": None, "count": 1, "loud": False}


def test_layers_override_lowest_to_highest():
    merged = resolve(
        cli={},
        env={"name": "env-name"},
        config_file={"name": "file-name", "count": "5"},
        defaults=DEFAULTS,
        casters=CASTERS,
    )
    # env beats config_file
    assert merged["name"] == "env-name"
    # config_file beats default
    assert merged["count"] == 5


def test_cli_wins_over_everything():
    merged = resolve(
        cli={"name": "cli-name"},
        env={"name": "env-name"},
        config_file={"name": "file-name"},
        defaults=DEFAULTS,
        casters=CASTERS,
    )
    assert merged["name"] == "cli-name"


def test_none_values_do_not_overwrite():
    merged = resolve(
        cli={"name": None},
        env={},
        config_file={"name": "file-name"},
        defaults=DEFAULTS,
        casters=CASTERS,
    )
    assert merged["name"] == "file-name"


def test_unrelated_keys_ignored():
    merged = resolve(
        cli={"unrelated": "whatever"},
        env={},
        config_file={},
        defaults=DEFAULTS,
        casters=CASTERS,
    )
    assert "unrelated" not in merged


def test_every_layer_gets_cast_the_same_way():
    # A TOML-native bool and an env-var string both normalize to True.
    merged_from_file = resolve({}, {}, {"loud": True}, DEFAULTS, CASTERS)
    merged_from_env = resolve({}, {"loud": "yes"}, {}, DEFAULTS, CASTERS)
    assert merged_from_file["loud"] is True
    assert merged_from_env["loud"] is True
