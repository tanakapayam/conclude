import pytest

from conclude.files import (
    ConfigFileError,
    cwd_aux_config_paths,
    load_config_file,
    load_config_files,
    load_raw_toml,
    parse_config_table,
    resolve_config_table,
    table_exists,
)

DEFAULTS = {"filename": None, "size": 1, "loud": False}


def write(path, text):
    path.write_text(text)
    return path


def test_load_raw_toml_missing_file_returns_empty(tmp_path):
    assert load_raw_toml(tmp_path / "nope.toml") == {}


def test_load_raw_toml_none_path_returns_empty():
    assert load_raw_toml(None) == {}


def test_load_raw_toml_reads_content(tmp_path):
    path = write(tmp_path / "c.toml", '[a]\nx = "y"\n')
    assert load_raw_toml(path) == {"a": {"x": "y"}}


def test_load_raw_toml_bad_toml_raises(tmp_path):
    path = write(tmp_path / "bad.toml", "not = [valid")
    with pytest.raises(ConfigFileError):
        load_raw_toml(path)


def test_table_exists():
    raw = {"a": {"b": {"c": 1}}, "d": 5}
    assert table_exists(raw, ["a"])
    assert table_exists(raw, ["a", "b"])
    assert not table_exists(raw, ["a", "missing"])
    assert not table_exists(raw, ["d"])  # d is not a table
    assert not table_exists(raw, ["missing"])


def test_cwd_aux_config_paths(tmp_path):
    main = tmp_path / ".config.toml"
    write(main, "")
    aux_b = write(tmp_path / ".config.b.toml", "")
    aux_a = write(tmp_path / ".config.a.toml", "")
    write(tmp_path / "other.toml", "")  # doesn't match pattern
    assert cwd_aux_config_paths(main) == [aux_a, aux_b]


def test_cwd_aux_config_paths_none_returns_empty():
    assert cwd_aux_config_paths(None) == []


def test_load_config_file_single_table(tmp_path):
    path = write(tmp_path / "c.toml", '[myapp]\nfilename = "cards.csv"\nsize = 2\n')
    result = load_config_file(path, DEFAULTS, ["myapp"])
    assert result == {"filename": "cards.csv", "size": 2}


def test_load_config_file_only_known_keys(tmp_path):
    path = write(tmp_path / "c.toml", '[myapp]\nfilename = "x"\nnot_a_setting = "y"\n')
    result = load_config_file(path, DEFAULTS, ["myapp"])
    assert result == {"filename": "x"}


def test_load_config_file_two_level_table_layers(tmp_path):
    path = write(
        tmp_path / "c.toml",
        """
        [myapp]
        filename = "shared.csv"
        size = 2

        [myapp.verbs]
        size = 3
        """,
    )
    result = load_config_file(path, DEFAULTS, ["myapp", "verbs"])
    assert result == {"filename": "shared.csv", "size": 3}


def test_load_config_file_missing_file_is_empty(tmp_path):
    assert load_config_file(tmp_path / "nope.toml", DEFAULTS, ["myapp"]) == {}


def test_load_config_file_none_path_is_empty():
    assert load_config_file(None, DEFAULTS, ["myapp"]) == {}


def test_load_config_file_missing_table_is_empty(tmp_path):
    path = write(tmp_path / "c.toml", '[other]\nfilename = "x"\n')
    assert load_config_file(path, DEFAULTS, ["myapp"]) == {}


def test_load_config_files_cwd_overrides_home(tmp_path):
    home = write(tmp_path / "home.toml", '[myapp]\nfilename = "home.csv"\nsize = 1\n')
    cwd = write(tmp_path / ".config.toml", '[myapp]\nfilename = "cwd.csv"\n')
    result = load_config_files(home, cwd, DEFAULTS, ["myapp"])
    assert result == {"filename": "cwd.csv", "size": 1}


def test_load_config_files_aux_wins_over_cwd(tmp_path):
    home = tmp_path / "home.toml"
    cwd = write(tmp_path / ".config.toml", "[myapp]\nsize = 1\n")
    write(tmp_path / ".config.extra.toml", "[myapp]\nsize = 9\n")
    result = load_config_files(home, cwd, DEFAULTS, ["myapp"])
    assert result["size"] == 9


def test_load_config_files_home_none_is_skipped(tmp_path):
    cwd = write(tmp_path / ".config.toml", '[myapp]\nfilename = "cwd.csv"\n')
    result = load_config_files(None, cwd, DEFAULTS, ["myapp"])
    assert result == {"filename": "cwd.csv"}


def test_load_config_files_cwd_none_disables_cwd_and_aux(tmp_path):
    home = write(tmp_path / "home.toml", '[myapp]\nfilename = "home.csv"\n')
    # A cwd file and an aux file exist on disk, but with cwd_path=None
    # neither should be read.
    write(tmp_path / ".config.toml", '[myapp]\nfilename = "cwd.csv"\n')
    write(tmp_path / ".config.extra.toml", '[myapp]\nfilename = "aux.csv"\n')
    result = load_config_files(home, None, DEFAULTS, ["myapp"])
    assert result == {"filename": "home.csv"}


def test_load_config_files_both_none_is_empty():
    assert load_config_files(None, None, DEFAULTS, ["myapp"]) == {}


def test_parse_config_table():
    assert parse_config_table(None, "myapp") == ["myapp"]
    assert parse_config_table("", "myapp") == ["myapp"]
    assert parse_config_table("parent", "myapp") == ["parent"]
    assert parse_config_table("parent.child", "myapp") == ["parent", "child"]


def test_parse_config_table_rejects_too_many_levels():
    with pytest.raises(ValueError):
        parse_config_table("a.b.c", "myapp")


def test_parse_config_table_rejects_stray_dots():
    # Each of these reads as a plausible typo (a doubled separator, a
    # trailing/leading one) for a name the person meant to type
    # correctly -- not a third way to spell "a.b"/"a"/"a".
    for value in ("a..b", "a.", ".a", "."):
        with pytest.raises(ValueError, match="PARENT"):
            parse_config_table(value, "myapp")


def test_resolve_config_table_explicit_config_wins(tmp_path):
    table_path = resolve_config_table(
        config_value="parent.child",
        shorthand_value="deckname",
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=tmp_path / ".config.toml",
    )
    assert table_path == ["parent", "child"]


def test_resolve_config_table_no_config_no_shorthand(tmp_path):
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value=None,
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=tmp_path / ".config.toml",
    )
    assert table_path == ["myapp"]


def test_resolve_config_table_shorthand_top_level_match(tmp_path):
    cwd = write(tmp_path / ".config.toml", "[japanese-verbs]\nsize = 2\n")
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="japanese-verbs",
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=cwd,
    )
    assert table_path == ["japanese-verbs"]


def test_resolve_config_table_shorthand_nested_match(tmp_path):
    cwd = write(tmp_path / ".config.toml", "[myapp.verbs]\nsize = 2\n")
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="verbs",
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=cwd,
    )
    assert table_path == ["myapp", "verbs"]


def test_resolve_config_table_shorthand_no_match_falls_back(tmp_path):
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="nonexistent",
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=tmp_path / ".config.toml",
    )
    assert table_path == ["myapp"]


def test_resolve_config_table_none_paths_fall_back_to_default_table():
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="anything",
        default_table="myapp",
        home_path=None,
        cwd_path=None,
    )
    assert table_path == ["myapp"]


def test_resolve_config_table_shorthand_checks_aux_files_too(tmp_path):
    cwd = tmp_path / ".config.toml"
    write(cwd, "")
    write(tmp_path / ".config.extra.toml", "[from-aux]\nsize = 1\n")
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="from-aux",
        default_table="myapp",
        home_path=tmp_path / "home.toml",
        cwd_path=cwd,
    )
    assert table_path == ["from-aux"]


def test_load_config_files_system_is_lowest_priority(tmp_path):
    system = write(tmp_path / "system.toml", '[myapp]\nfilename = "system.csv"\nsize = 1\n')
    home = write(tmp_path / "home.toml", '[myapp]\nfilename = "home.csv"\n')
    result = load_config_files(home, None, DEFAULTS, ["myapp"], system_path=system)
    assert result == {"filename": "home.csv", "size": 1}


def test_load_config_files_system_loses_to_cwd_and_aux(tmp_path):
    system = write(tmp_path / "system.toml", "[myapp]\nsize = 1\nloud = true\n")
    cwd = write(tmp_path / ".config.toml", "[myapp]\nsize = 2\n")
    write(tmp_path / ".config.extra.toml", "[myapp]\nsize = 3\n")
    result = load_config_files(None, cwd, DEFAULTS, ["myapp"], system_path=system)
    assert result == {"size": 3, "loud": True}


def test_load_config_files_system_alone(tmp_path):
    system = write(tmp_path / "system.toml", '[myapp]\nfilename = "system.csv"\n')
    assert load_config_files(None, None, DEFAULTS, ["myapp"], system_path=system) == {
        "filename": "system.csv"
    }


def test_load_config_files_system_defaults_to_disabled(tmp_path):
    # Not passing system_path at all reads no system file -- existing
    # callers are unaffected.
    home = write(tmp_path / "home.toml", '[myapp]\nfilename = "home.csv"\n')
    assert load_config_files(home, None, DEFAULTS, ["myapp"]) == {"filename": "home.csv"}


def test_load_config_files_system_missing_file_is_skipped(tmp_path):
    home = write(tmp_path / "home.toml", '[myapp]\nfilename = "home.csv"\n')
    result = load_config_files(
        home, None, DEFAULTS, ["myapp"], system_path=tmp_path / "does-not-exist.toml"
    )
    assert result == {"filename": "home.csv"}


def test_load_config_files_system_uses_selected_table(tmp_path):
    system = write(
        tmp_path / "system.toml", "[myapp]\nsize = 1\n[other]\nsize = 7\n[myapp.deck]\nsize = 9\n"
    )
    assert load_config_files(None, None, DEFAULTS, ["other"], system_path=system) == {"size": 7}
    assert load_config_files(None, None, DEFAULTS, ["myapp", "deck"], system_path=system) == {
        "size": 9
    }


def test_load_config_files_system_bad_toml_raises(tmp_path):
    system = write(tmp_path / "system.toml", "not [valid toml")
    with pytest.raises(ConfigFileError):
        load_config_files(None, None, DEFAULTS, ["myapp"], system_path=system)


def test_resolve_config_table_shorthand_checks_system_file_too(tmp_path):
    system = write(tmp_path / "system.toml", "[from-system]\nsize = 1\n")
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="from-system",
        default_table="myapp",
        home_path=None,
        cwd_path=None,
        system_path=system,
    )
    assert table_path == ["from-system"]


def test_resolve_config_table_shorthand_nested_match_in_system_file(tmp_path):
    system = write(tmp_path / "system.toml", "[myapp.deck]\nsize = 1\n")
    table_path = resolve_config_table(
        config_value=None,
        shorthand_value="deck",
        default_table="myapp",
        home_path=None,
        cwd_path=None,
        system_path=system,
    )
    assert table_path == ["myapp", "deck"]


def test_cwd_aux_config_paths_none_pattern_returns_nothing(tmp_path):
    cwd = write(tmp_path / ".config.toml", "")
    write(tmp_path / ".config.extra.toml", "")
    assert cwd_aux_config_paths(cwd, ".config.*.toml") == [tmp_path / ".config.extra.toml"]
    assert cwd_aux_config_paths(cwd, None) == []


def test_load_config_files_aux_pattern_none_skips_only_the_siblings(tmp_path):
    cwd = write(tmp_path / ".config.toml", "[myapp]\nsize = 2\n")
    write(tmp_path / ".config.extra.toml", "[myapp]\nsize = 3\n")
    assert load_config_files(None, cwd, DEFAULTS, ["myapp"]) == {"size": 3}
    assert load_config_files(None, cwd, DEFAULTS, ["myapp"], aux_pattern=None) == {"size": 2}


def test_load_config_files_custom_aux_pattern(tmp_path):
    cwd = write(tmp_path / ".config.toml", "[myapp]\nsize = 2\n")
    write(tmp_path / ".config.extra.toml", "[myapp]\nsize = 3\n")
    write(tmp_path / ".local.one.toml", "[myapp]\nsize = 4\n")
    result = load_config_files(None, cwd, DEFAULTS, ["myapp"], aux_pattern=".local.*.toml")
    assert result == {"size": 4}


def test_resolve_config_table_shorthand_ignores_aux_files_when_pattern_is_none(tmp_path):
    cwd = write(tmp_path / ".config.toml", "[myapp]\nsize = 1\n")
    write(tmp_path / ".config.extra.toml", "[deck]\nsize = 2\n")
    common = {
        "config_value": None,
        "shorthand_value": "deck",
        "default_table": "myapp",
        "home_path": None,
        "cwd_path": cwd,
    }
    assert resolve_config_table(**common) == ["deck"]
    assert resolve_config_table(**common, aux_pattern=None) == ["myapp"]
