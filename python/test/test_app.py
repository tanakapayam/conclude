import argparse
from pathlib import Path

import pytest

import conclude
from conclude import App

DEFAULTS = {
    "filename": conclude.opt(str),
    "front": conclude.opt(list),
    "shuffle": False,
    "size": 1,
}


def test_resolved_defaults_unwraps_opt():
    app = App("myapp", DEFAULTS)
    assert app.resolved_defaults == {"filename": None, "front": None, "shuffle": False, "size": 1}


def test_resolved_env_vars_inferred():
    app = App("myapp", DEFAULTS)
    assert app.resolved_env_vars == {
        "filename": "MYAPP_FILENAME",
        "front": "MYAPP_FRONT",
        "shuffle": "MYAPP_SHUFFLE",
        "size": "MYAPP_SIZE",
    }


def test_resolved_env_vars_override():
    app = App("myapp", DEFAULTS, env_vars={"filename": "MYAPP_FILE"})
    resolved = app.resolved_env_vars
    assert resolved["filename"] == "MYAPP_FILE"
    assert resolved["size"] == "MYAPP_SIZE"  # unaffected


def test_resolved_casters_inferred():
    app = App("myapp", DEFAULTS)
    casters = app.resolved_casters
    assert casters["shuffle"]("true") is True
    assert casters["size"]("5") == 5
    assert casters["front"]("a,b") == ["a", "b"]


def test_resolved_casters_override():
    app = App("myapp", DEFAULTS, casters={"size": lambda v: int(v) * 10})
    casters = app.resolved_casters
    assert casters["size"]("5") == 50
    assert casters["shuffle"]("true") is True  # still inferred


def test_build_arg_parser_infers_flags():
    app = App("myapp", DEFAULTS)
    parser = app.build_arg_parser(prog="myapp")
    ns = parser.parse_args(["--filename=cards.csv", "--shuffle", "--size=3"])
    assert ns.filename == "cards.csv"
    assert ns.shuffle is True
    assert ns.size == "3"  # unparsed/uncast at the argparse level -- casting happens in resolve()
    assert ns.front is None


def test_add_arguments_with_overrides_and_skip():
    app = App("myapp", DEFAULTS)
    parser = argparse.ArgumentParser(prog="myapp")
    parser.add_argument("shorthand", nargs="?", default=None)
    app.add_arguments(
        parser,
        overrides={"filename": {"help": "custom help text"}},
        skip={"front"},
    )
    # "front" was skipped -- no --front flag registered
    with pytest.raises(SystemExit):
        parser.parse_args(["--front=x"])
    ns = parser.parse_args(["--filename=cards.csv"])
    assert ns.filename == "cards.csv"
    assert not hasattr(ns, "front")


def test_resolve_merges_layers():
    app = App("myapp", DEFAULTS)
    result = app.resolve(
        cli={"size": "7"},
        env={"shuffle": "true"},
        config_file={"filename": "from-file.csv"},
    )
    assert result == {
        "filename": "from-file.csv",
        "front": None,
        "shuffle": True,
        "size": 7,
    }


def test_resolve_cli_wins_over_env_and_config():
    app = App("myapp", DEFAULTS)
    result = app.resolve(
        cli={"filename": "cli.csv"},
        env={"filename": "env.csv"},
        config_file={"filename": "file.csv"},
    )
    assert result["filename"] == "cli.csv"


def test_resolve_loads_env_and_config_itself_when_not_given(tmp_path, monkeypatch):
    monkeypatch.setenv("MYAPP_SIZE", "9")
    app = App(
        "myapp",
        DEFAULTS,
        dotenv_path=None,  # not under test here; keep deterministic regardless of cwd
        config_home_path=tmp_path / "home.toml",
        config_cwd_path=tmp_path / ".config.toml",
    )
    result = app.resolve(cli={})
    assert result["size"] == 9
    monkeypatch.delenv("MYAPP_SIZE")


def test_load_config_files_reads_default_table(tmp_path):
    home = tmp_path / "home.toml"
    home.write_text('[myapp]\nfilename = "home.csv"\n')
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=home,
        config_cwd_path=tmp_path / ".config.toml",
    )
    assert app.load_config_files() == {"filename": "home.csv"}


def test_resolve_config_table_shorthand(tmp_path):
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[profile-a]\nsize = 5\n")
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=tmp_path / "home.toml",
        config_cwd_path=cwd,
    )
    table_path = app.resolve_config_table(shorthand_value="profile-a")
    assert table_path == ["profile-a"]


def test_format_invocation_omits_defaults():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": "cards.csv", "front": None, "shuffle": False, "size": 1}
    invocation = app.format_invocation(resolved, prog="myapp")
    assert invocation == "myapp --filename=cards.csv"


def test_format_invocation_includes_non_defaults():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": "cards.csv", "front": ["A", "B"], "shuffle": True, "size": 3}
    invocation = app.format_invocation(resolved, prog="myapp")
    assert "--filename=cards.csv" in invocation
    assert "--front=A,B" in invocation
    assert "--shuffle" in invocation
    assert "--size=3" in invocation
    # bool flag is bare, no "=" for it
    assert "--shuffle=" not in invocation


def test_format_invocation_no_prog_is_just_flags():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": None, "front": None, "shuffle": True, "size": 1}
    invocation = app.format_invocation(resolved)
    assert invocation == "--shuffle"


def test_format_invocation_always_include():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": None, "front": None, "shuffle": False, "size": 1}
    invocation = app.format_invocation(resolved, prog="myapp", always_include={"size"})
    assert invocation == "myapp --size=1"


def test_format_invocation_skip():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": "cards.csv", "front": None, "shuffle": True, "size": 1}
    invocation = app.format_invocation(resolved, prog="myapp", skip={"shuffle"})
    assert "--shuffle" not in invocation
    assert "--filename=cards.csv" in invocation


def test_format_invocation_compare_defaults_override():
    app = App("myapp", DEFAULTS)
    resolved = {"filename": None, "front": None, "shuffle": False, "size": 1}
    # Pretend `size` effectively defaults to 5 for this call (e.g. a
    # post-resolve fallback substitution the app itself applies) --
    # a resolved size of 1 should now be shown, not omitted.
    compare_defaults = {**app.resolved_defaults, "size": 5}
    invocation = app.format_invocation(resolved, prog="myapp", compare_defaults=compare_defaults)
    assert invocation == "myapp --size=1"


def test_format_invocation_formatter_override_pairs_with_caster_override():
    defaults = {"separator": conclude.opt(str)}
    app = App(
        "myapp",
        defaults,
        casters={"separator": conclude.cast_escaped_str},
    )

    def format_separator(value):
        import shlex

        return shlex.quote(value.encode("unicode_escape").decode("ascii"))

    invocation = app.format_invocation(
        {"separator": "\n\n"},
        prog="myapp",
        formatters={"separator": format_separator},
    )
    assert invocation == r"myapp --separator='\n\n'"


def test_format_invocation_required_setting_always_shown_without_always_include():
    # A setting whose default is None (opt(str)) essentially never
    # equals its resolved value in practice, so it's included without
    # needing `always_include` -- this is the "required setting" case
    # falling naturally out of the omit-if-equals-default rule.
    app = App("myapp", DEFAULTS)
    resolved = {"filename": "cards.csv", "front": None, "shuffle": False, "size": 1}
    invocation = app.format_invocation(resolved, prog="myapp")
    assert invocation == "myapp --filename=cards.csv"


def test_load_env_dotenv_disabled_by_default(tmp_path, monkeypatch):
    # Reading an arbitrary local .env file for secrets should never
    # happen just because nobody thought about it -- off unless
    # explicitly requested.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MYAPP_SIZE=7\n")
    app = App("myapp", DEFAULTS)
    result = app.load_env({})
    assert "size" not in result


def test_load_env_dotenv_auto_opts_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MYAPP_SIZE=7\n")
    app = App("myapp", DEFAULTS, dotenv_path=conclude.AUTO)
    result = app.load_env({})
    assert result["size"] == "7"


def test_load_env_dotenv_path_none_disables_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MYAPP_SIZE=7\n")
    app = App("myapp", DEFAULTS, dotenv_path=None)
    result = app.load_env({})
    assert "size" not in result


def test_load_env_custom_dotenv_path(tmp_path):
    dotenv_path = tmp_path / "custom.env"
    dotenv_path.write_text("MYAPP_SIZE=42\n")
    app = App("myapp", DEFAULTS, dotenv_path=dotenv_path)
    result = app.load_env({})
    assert result["size"] == "42"


def test_add_print_invocation_argument_default():
    app = App("myapp", DEFAULTS)
    parser = argparse.ArgumentParser(prog="myapp")
    app.add_print_invocation_argument(parser)
    ns = parser.parse_args([])
    assert ns.print_invocation is False
    ns = parser.parse_args(["--print-invocation"])
    assert ns.print_invocation is True


def test_add_print_invocation_argument_custom_flag_and_dest():
    app = App("myapp", DEFAULTS)
    parser = argparse.ArgumentParser(prog="myapp")
    app.add_print_invocation_argument(parser, flag="--show-command", dest="show_command")
    ns = parser.parse_args(["--show-command"])
    assert ns.show_command is True


def test_resolved_config_home_path_computed_by_default():
    app = App("myapp", DEFAULTS)
    assert app.resolved_config_home_path == conclude.default_config_home_path("myapp")


def test_resolved_config_home_path_explicit_override():
    custom = Path("/tmp/somewhere/config.toml")
    app = App("myapp", DEFAULTS, config_home_path=custom)
    assert app.resolved_config_home_path == custom


def test_resolved_config_home_path_explicit_auto_same_as_default():
    app = App("myapp", DEFAULTS, config_home_path=conclude.AUTO)
    assert app.resolved_config_home_path == conclude.default_config_home_path("myapp")


def test_auto_repr():
    assert repr(conclude.AUTO) == "AUTO"


def test_resolved_config_home_path_disabled():
    app = App("myapp", DEFAULTS, config_home_path=None)
    assert app.resolved_config_home_path is None


def test_resolved_config_cwd_path_default_and_disabled():
    app = App("myapp", DEFAULTS)
    assert app.resolved_config_cwd_path == Path(".config.toml")
    app_disabled = App("myapp", DEFAULTS, config_cwd_path=None)
    assert app_disabled.resolved_config_cwd_path is None


def test_resolved_dotenv_path_default_and_disabled():
    # Default is off (None) -- unlike the config-file sources, .env
    # reads arbitrary local files for secrets, so it requires opt-in.
    app = App("myapp", DEFAULTS)
    assert app.resolved_dotenv_path is None
    app_auto = App("myapp", DEFAULTS, dotenv_path=conclude.AUTO)
    assert app_auto.resolved_dotenv_path == Path(".env")
    app_disabled = App("myapp", DEFAULTS, dotenv_path=None)
    assert app_disabled.resolved_dotenv_path is None


def test_config_home_path_disabled_is_excluded_from_load_config_files(tmp_path):
    home = tmp_path / "home.toml"
    home.write_text('[myapp]\nfilename = "home.csv"\n')
    cwd = tmp_path / ".config.toml"
    # config_home_path disabled -- even though the file exists and is
    # valid, it should never be read.
    app = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd)
    result = app.load_config_files()
    assert result == {}


def test_config_cwd_path_disabled_also_disables_aux_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".config.toml").write_text('[myapp]\nfilename = "cwd.csv"\n')
    (tmp_path / ".config.extra.toml").write_text('[myapp]\nfilename = "aux.csv"\n')
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=tmp_path / "home.toml",
        config_cwd_path=None,
    )
    result = app.load_config_files()
    assert result == {}


def test_resolve_config_table_shorthand_with_home_disabled(tmp_path):
    home = tmp_path / "home.toml"
    home.write_text("[profile-a]\nsize = 5\n")  # would match, but home is disabled
    cwd = tmp_path / ".config.toml"
    cwd.write_text("")
    app = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd)
    table_path = app.resolve_config_table(shorthand_value="profile-a")
    assert table_path == ["myapp"]  # falls back -- home wasn't checked


def test_dotenv_path_disabled_ignores_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MYAPP_SIZE=7\n")
    app = App("myapp", DEFAULTS, dotenv_path=None)
    result = app.load_env({})
    assert "size" not in result


def test_describe_sources_default_opt_in_sources_disabled_config_enabled():
    # User/project config files default to enabled; .env and the
    # system config default to off, since each requires an explicit
    # opt-in (see App.dotenv_path / App.config_system_path).
    app = App("myapp", DEFAULTS)
    description = app.describe_sources()
    assert "system config" in description
    assert "user config" in description
    assert str(conclude.default_config_home_path("myapp")) in description
    assert "project config" in description
    assert ".config.toml" in description
    assert ".env file" in description
    assert description.count("disabled") == 2  # system config and .env


def test_describe_sources_all_auto_shows_everything_enabled():
    app = App("myapp", DEFAULTS, dotenv_path=conclude.AUTO, config_system_path=conclude.AUTO)
    description = app.describe_sources()
    assert "disabled" not in description
    assert ".env" in description
    assert "/etc/myapp/config.toml" in description


def test_describe_sources_lists_system_config_first():
    # Lowest priority first: system, user, project, .env, then developer.
    app = App("myapp", DEFAULTS, config_system_path=conclude.AUTO)
    labels = [line.split("  ")[1] for line in app.describe_sources().splitlines()[1:]]
    assert labels == [
        "system config",
        "user config",
        "project config",
        ".env file",
        "developer config",
    ]


def test_describe_sources_reports_disabled_sources():
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=None,
        config_cwd_path=None,
        dotenv_path=None,
        config_system_path=None,
    )
    description = app.describe_sources()
    assert description.count("disabled") == 4


def test_describe_sources_survives_raw_description_help_formatter(capsys):
    # argparse's default formatter re-wraps epilog text into one
    # paragraph, destroying describe_sources()'s aligned columns --
    # RawDescriptionHelpFormatter is required to preserve it. This
    # locks in that documented requirement.
    app = App("myapp", DEFAULTS, config_cwd_path=None)
    description = app.describe_sources()
    parser = argparse.ArgumentParser(
        prog="myapp",
        epilog=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    assert "  project config    disabled" in captured.out
    assert "  developer config  not opted in" in captured.out


# --- system-wide config: opt-in, lowest-priority config file ---------------


def test_config_system_path_is_off_by_default():
    app = App("myapp", DEFAULTS)
    assert app.config_system_path is None
    assert app.resolved_config_system_path is None


def test_config_system_path_auto_resolves_to_etc():
    app = App("myapp", DEFAULTS, config_system_path=conclude.AUTO)
    assert app.resolved_config_system_path == Path("/etc/myapp/config.toml")
    assert app.resolved_config_system_path == conclude.default_config_system_path("myapp")


def test_config_system_path_explicit_override():
    custom = Path("/opt/somewhere/else.toml")
    app = App("myapp", DEFAULTS, config_system_path=custom)
    assert app.resolved_config_system_path == custom


def test_config_system_path_uses_app_name_verbatim():
    app = App("my-app", DEFAULTS, config_system_path=conclude.AUTO)
    assert app.resolved_config_system_path == Path("/etc/my-app/config.toml")


def test_system_config_is_not_read_unless_opted_in(tmp_path):
    system = tmp_path / "system.toml"
    system.write_text('[myapp]\nfilename = "system.csv"\n')
    # The file exists, but the App never opted in (config_system_path
    # left at its default) -- so it must never be read.
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=None,
        config_cwd_path=tmp_path / ".config.toml",
    )
    assert app.load_config_files() == {}


def test_system_config_is_read_when_opted_in(tmp_path):
    system = tmp_path / "system.toml"
    system.write_text('[myapp]\nfilename = "system.csv"\nsize = 3\n')
    app = App(
        "myapp",
        DEFAULTS,
        config_system_path=system,
        config_home_path=None,
        config_cwd_path=None,
    )
    assert app.load_config_files() == {"filename": "system.csv", "size": 3}


def test_system_config_is_lowest_priority_config_file(tmp_path):
    system = tmp_path / "system.toml"
    system.write_text('[myapp]\nfilename = "system.csv"\nsize = 3\nshuffle = true\n')
    home = tmp_path / "home.toml"
    home.write_text('[myapp]\nfilename = "home.csv"\nsize = 4\n')
    cwd = tmp_path / ".config.toml"
    cwd.write_text('[myapp]\nfilename = "cwd.csv"\n')
    app = App(
        "myapp",
        DEFAULTS,
        config_system_path=system,
        config_home_path=home,
        config_cwd_path=cwd,
    )
    # system < user < project, key by key.
    assert app.load_config_files() == {"filename": "cwd.csv", "size": 4, "shuffle": True}


def test_full_precedence_chain_defaults_system_user_project_env_cli(tmp_path):
    # Each layer sets `size`, and every layer above it sets it too, so
    # peeling layers off one at a time reveals the next one down:
    #   defaults(1) < system(2) < user(3) < project(4) < env(5) < cli(6)
    system = tmp_path / "system.toml"
    system.write_text("[myapp]\nsize = 2\n")
    home = tmp_path / "home.toml"
    home.write_text("[myapp]\nsize = 3\n")
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[myapp]\nsize = 4\n")

    def build(**kwargs):
        return App(
            "myapp",
            DEFAULTS,
            dotenv_path=None,
            config_system_path=kwargs.get("system"),
            config_home_path=kwargs.get("home"),
            config_cwd_path=kwargs.get("cwd"),
        )

    assert build().resolve({}, env={})["size"] == DEFAULTS["size"]
    assert build(system=system).resolve({}, env={})["size"] == 2
    assert build(system=system, home=home).resolve({}, env={})["size"] == 3
    assert build(system=system, home=home, cwd=cwd).resolve({}, env={})["size"] == 4
    full = build(system=system, home=home, cwd=cwd)
    assert full.resolve({}, env={"size": "5"})["size"] == 5
    assert full.resolve({"size": 6}, env={"size": "5"})["size"] == 6


def test_resolve_picks_up_system_config_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("MYAPP_FILENAME", raising=False)
    system = tmp_path / "system.toml"
    system.write_text('[myapp]\nfilename = "system.csv"\n')
    app = App(
        "myapp",
        DEFAULTS,
        dotenv_path=None,
        config_system_path=system,
        config_home_path=None,
        config_cwd_path=None,
    )
    assert app.resolve(cli={})["filename"] == "system.csv"


def test_resolve_config_table_shorthand_finds_table_in_system_config(tmp_path):
    system = tmp_path / "system.toml"
    system.write_text("[profile-a]\nsize = 5\n")
    app = App(
        "myapp",
        DEFAULTS,
        config_system_path=system,
        config_home_path=None,
        config_cwd_path=None,
    )
    assert app.resolve_config_table(shorthand_value="profile-a") == ["profile-a"]


def test_resolve_config_table_shorthand_ignores_system_config_unless_opted_in(tmp_path):
    system = tmp_path / "system.toml"
    system.write_text("[profile-a]\nsize = 5\n")
    app = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=None)
    assert app.resolve_config_table(shorthand_value="profile-a") == ["myapp"]


# --- config_cwd_aux_pattern: the sibling-file glob is its own knob ----------------


def test_config_cwd_aux_pattern_default():
    assert App("myapp", DEFAULTS).config_cwd_aux_pattern == ".config.*.toml"


def test_aux_siblings_are_merged_by_default(tmp_path):
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[myapp]\nsize = 2\n")
    (tmp_path / ".config.backup.toml").write_text("[myapp]\nsize = 9\n")
    app = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd)
    assert app.load_config_files() == {"size": 9}  # the stray sibling silently wins


def test_aux_pattern_none_keeps_the_project_file_but_drops_siblings(tmp_path):
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[myapp]\nsize = 2\n")
    (tmp_path / ".config.backup.toml").write_text("[myapp]\nsize = 9\n")
    app = App(
        "myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd, config_cwd_aux_pattern=None
    )
    assert app.load_config_files() == {"size": 2}


def test_aux_pattern_can_be_customised(tmp_path):
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[myapp]\nsize = 2\n")
    (tmp_path / ".config.backup.toml").write_text("[myapp]\nsize = 9\n")
    (tmp_path / ".config.local.toml").write_text("[myapp]\nsize = 5\n")
    app = App(
        "myapp",
        DEFAULTS,
        config_home_path=None,
        config_cwd_path=cwd,
        config_cwd_aux_pattern=".config.local.toml",
    )
    assert app.load_config_files() == {"size": 5}


def test_aux_pattern_none_also_applies_to_the_shorthand_table_lookup(tmp_path):
    cwd = tmp_path / ".config.toml"
    cwd.write_text("[myapp]\nsize = 1\n")
    (tmp_path / ".config.extra.toml").write_text("[deck]\nsize = 2\n")
    on = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd)
    off = App(
        "myapp", DEFAULTS, config_home_path=None, config_cwd_path=cwd, config_cwd_aux_pattern=None
    )
    assert on.resolve_config_table(shorthand_value="deck") == ["deck"]
    assert off.resolve_config_table(shorthand_value="deck") == ["myapp"]


def test_describe_sources_project_row_lists_the_sibling_pattern():
    row = [
        line
        for line in App("myapp", DEFAULTS).describe_sources().splitlines()
        if "project config" in line
    ][0]
    assert row.endswith("  .config.toml, .config.*.toml")


def test_describe_sources_project_row_without_siblings():
    app = App("myapp", DEFAULTS, config_cwd_aux_pattern=None)
    row = [line for line in app.describe_sources().splitlines() if "project config" in line][0]
    assert row.endswith("  .config.toml")


def test_describe_sources_project_row_puts_the_pattern_beside_the_file(tmp_path):
    app = App("myapp", DEFAULTS, config_cwd_path=tmp_path / "proj" / ".config.toml")
    row = [line for line in app.describe_sources().splitlines() if "project config" in line][0]
    assert row.endswith(
        f"  {tmp_path / 'proj' / '.config.toml'}, {tmp_path / 'proj' / '.config.*.toml'}"
    )


def test_describe_sources_project_row_disabled_hides_the_pattern():
    app = App("myapp", DEFAULTS, config_cwd_path=None)
    row = [line for line in app.describe_sources().splitlines() if "project config" in line][0]
    assert row.endswith("  disabled")
