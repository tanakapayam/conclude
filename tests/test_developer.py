import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import conclude
from conclude import App, ConfigFileError, DeveloperState, opt
from conclude.developer import developer_status, load_developer_config
from conclude.guard import matches_git_ignore_rules
from conclude.merge import resolve as merge_resolve

pathspec = pytest.importorskip("pathspec")

DEFAULTS = {"filename": opt(str), "size": 1, "loud": False}


@pytest.fixture(autouse=True)
def _clean_kill_switch(monkeypatch):
    monkeypatch.delenv("MYAPP_DEVELOPER_CONFIG", raising=False)


@pytest.fixture
def project(tmp_path):
    """A git working tree whose pyproject.toml names a gitignored
    developer file that exists -- the fully-ACTIVE setup."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".gitignore").write_text(".conclude.local.toml\n")
    (root / "pyproject.toml").write_text(
        '[tool.conclude.developer]\nconfig = ".conclude.local.toml"\n'
    )
    (root / ".conclude.local.toml").write_text("[myapp]\nsize = 6\n")
    return root


def dev_app(root, **kwargs):
    kwargs.setdefault("config_home_path", None)
    kwargs.setdefault("config_cwd_path", None)
    return App("myapp", DEFAULTS, pyproject_path=root / "pyproject.toml", **kwargs)


# --- the four states -----------------------------------------------------------


def test_not_opted_in():
    status = developer_status(None)
    assert status.state is DeveloperState.NOT_OPTED_IN
    assert not status.active
    assert str(status) == "not opted in"


@pytest.mark.parametrize(
    ("pyproject_text", "reason_part"),
    [
        (None, "no "),  # no pyproject.toml at all
        ("this is [not toml", "not readable TOML"),
        ("[project]\nname = 'x'\n", "no tool.conclude.developer.config"),
        ("[tool.conclude]\nsomething = 1\n", "no tool.conclude.developer.config"),
        ("[tool]\nconclude = 'x'\n", "no tool.conclude.developer.config"),
        ("[tool.conclude.developer]\nconfig = 5\n", "must be a non-empty string"),
        ("[tool.conclude.developer]\nconfig = ''\n", "must be a non-empty string"),
        ("[tool.conclude.developer]\nconfig = '  '\n", "must be a non-empty string"),
    ],
)
def test_not_configured(tmp_path, pyproject_text, reason_part):
    pyproject = tmp_path / "pyproject.toml"
    if pyproject_text is not None:
        pyproject.write_text(pyproject_text)
    status = developer_status(pyproject)
    assert status.state is DeveloperState.NOT_CONFIGURED
    assert reason_part in status.reason
    assert not status.setup_error
    assert str(status).startswith("not configured (")


def test_active(project):
    status = developer_status(project / "pyproject.toml")
    assert status.state is DeveloperState.ACTIVE
    assert status.active
    assert status.path == project / ".conclude.local.toml"
    assert str(status) == f"{project / '.conclude.local.toml'} -- configured, active"


def test_inactive_file_not_found(project):
    (project / ".conclude.local.toml").unlink()
    status = developer_status(project / "pyproject.toml")
    assert status.state is DeveloperState.INACTIVE
    assert status.reason == "file not found"
    assert str(status).endswith("-- configured, inactive (file not found)")


def test_inactive_not_in_a_git_tree(project):
    (project / ".git").rmdir()
    status = developer_status(project / "pyproject.toml")
    assert status.state is DeveloperState.INACTIVE
    assert status.reason == "not inside a git working tree"


def test_inactive_not_gitignored(project):
    (project / ".gitignore").write_text("something-else\n")
    status = developer_status(project / "pyproject.toml")
    assert status.state is DeveloperState.INACTIVE
    assert status.reason == "not covered by .gitignore"
    assert not status.setup_error


def test_inactive_when_there_is_no_gitignore_at_all(project):
    (project / ".gitignore").unlink()
    assert developer_status(project / "pyproject.toml").state is DeveloperState.INACTIVE


# --- kill switch ----------------------------------------------------------------


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "No", " off "])
def test_kill_switch_deactivates(project, value):
    status = developer_status(
        project / "pyproject.toml",
        kill_switch_var="MYAPP_DEVELOPER_CONFIG",
        environ={"MYAPP_DEVELOPER_CONFIG": value},
    )
    assert status.state is DeveloperState.INACTIVE
    assert status.reason == f"disabled by MYAPP_DEVELOPER_CONFIG={value.strip()}"


@pytest.mark.parametrize("value", ["on", "1", "true", "yes", "", "anything"])
def test_kill_switch_other_values_do_nothing(project, value):
    status = developer_status(
        project / "pyproject.toml",
        kill_switch_var="MYAPP_DEVELOPER_CONFIG",
        environ={"MYAPP_DEVELOPER_CONFIG": value},
    )
    assert status.active


def test_kill_switch_does_not_make_an_unconfigured_layer_look_configured(tmp_path):
    status = developer_status(
        tmp_path / "pyproject.toml",
        kill_switch_var="X",
        environ={"X": "off"},
    )
    assert status.state is DeveloperState.NOT_CONFIGURED


def test_kill_switch_defaults_to_the_real_environment(project, monkeypatch):
    monkeypatch.setenv("MYAPP_DEVELOPER_CONFIG", "off")
    status = developer_status(project / "pyproject.toml", kill_switch_var="MYAPP_DEVELOPER_CONFIG")
    assert status.state is DeveloperState.INACTIVE


# --- where the file is found ------------------------------------------------------


def test_path_is_relative_to_pyproject_directory_not_cwd(project, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert developer_status(project / "pyproject.toml").active


def test_path_in_a_subdirectory(project):
    (project / "conf").mkdir()
    (project / "conf" / "dev.toml").write_text("[myapp]\nsize = 2\n")
    (project / ".gitignore").write_text("conf/\n")
    (project / "pyproject.toml").write_text('[tool.conclude.developer]\nconfig = "conf/dev.toml"\n')
    assert developer_status(project / "pyproject.toml").active


def test_dotdot_is_normalized_before_checking_the_ignore_rules(project):
    # pyproject.toml lives in a subdirectory; the file it names is a
    # sibling of the sub-directory, at the repo root.
    (project / "sub").mkdir()
    (project / "sub" / "pyproject.toml").write_text(
        '[tool.conclude.developer]\nconfig = "../.conclude.local.toml"\n'
    )
    assert developer_status(project / "sub" / "pyproject.toml").active


def test_absolute_path_inside_the_repo(project):
    (project / "pyproject.toml").write_text(
        f'[tool.conclude.developer]\nconfig = "{project / ".conclude.local.toml"}"\n'
    )
    assert developer_status(project / "pyproject.toml").active


def test_git_file_counts_as_a_working_tree(project):
    # A worktree/submodule has a .git *file* rather than a directory.
    (project / ".git").rmdir()
    (project / ".git").write_text("gitdir: /somewhere/else\n")
    assert developer_status(project / "pyproject.toml").active


def test_git_root_can_be_an_ancestor_of_the_project(project):
    # pyproject.toml in a monorepo subdirectory, .gitignore at the root.
    package = project / "packages" / "app"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[tool.conclude.developer]\nconfig = ".conclude.local.toml"\n'
    )
    (package / ".conclude.local.toml").write_text("[myapp]\nsize = 3\n")
    (project / ".gitignore").write_text(".conclude.local.toml\n")  # unanchored: matches anywhere
    assert developer_status(package / "pyproject.toml").active


def test_git_info_exclude_counts(project):
    (project / ".gitignore").unlink()
    (project / ".git" / "info").mkdir()
    (project / ".git" / "info" / "exclude").write_text(".conclude.local.toml\n")
    assert developer_status(project / "pyproject.toml").active


# --- gitignore semantics (without needing a git binary) ---------------------------


def make_tree(root, files, gitignores):
    (root / ".git").mkdir(exist_ok=True)
    for name, text in gitignores.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def test_negation_within_one_file(tmp_path):
    make_tree(
        tmp_path,
        ["a.local.toml", "keep.local.toml"],
        {".gitignore": "*.local.toml\n!keep.local.toml\n"},
    )
    assert matches_git_ignore_rules(tmp_path, tmp_path / "a.local.toml")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "keep.local.toml")


def test_nested_gitignore_overrides_parent(tmp_path):
    make_tree(
        tmp_path,
        ["x.local.toml", "sub/x.local.toml"],
        {".gitignore": "*.local.toml\n", "sub/.gitignore": "!*.local.toml\n"},
    )
    assert matches_git_ignore_rules(tmp_path, tmp_path / "x.local.toml")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "sub" / "x.local.toml")


def test_nested_gitignore_patterns_are_relative_to_its_directory(tmp_path):
    make_tree(
        tmp_path,
        ["sub/only.toml", "only.toml", "sub/deeper/only.toml"],
        {"sub/.gitignore": "/only.toml\n"},
    )
    assert matches_git_ignore_rules(tmp_path, tmp_path / "sub" / "only.toml")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "only.toml")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "sub" / "deeper" / "only.toml")


def test_a_file_cannot_be_reincluded_inside_an_ignored_directory(tmp_path):
    make_tree(
        tmp_path,
        ["outer/inner/file.toml"],
        {".gitignore": "inner/\n", "outer/inner/.gitignore": "!file.toml\n"},
    )
    assert matches_git_ignore_rules(tmp_path, tmp_path / "outer" / "inner" / "file.toml")


def test_directory_only_patterns_only_match_directories(tmp_path):
    make_tree(tmp_path, ["build/x.toml", "sub/build"], {".gitignore": "build/\n"})
    assert matches_git_ignore_rules(tmp_path, tmp_path / "build" / "x.toml")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "sub" / "build")  # a file named build


def test_info_exclude_has_lower_priority_than_gitignore(tmp_path):
    make_tree(tmp_path, ["a.toml"], {".gitignore": "!a.toml\n"})
    (tmp_path / ".git" / "info").mkdir()
    (tmp_path / ".git" / "info" / "exclude").write_text("a.toml\n")
    assert not matches_git_ignore_rules(tmp_path, tmp_path / "a.toml")


# --- differential check against real git ------------------------------------------

GIT_MATRIX_GITIGNORES = {
    ".gitignore": (
        "*.local.toml\n!keep.local.toml\nbuild/\n/rootonly.toml\nsecret*\n.env.local\n"
        "docs/*.tmp\n**/deep/*.priv\n"
    ),
    ".git/info/exclude": "excluded-by-info.toml\n!secret-keep.toml\n",
    "sub/.gitignore": "!*.local.toml\nsubonly.toml\n/anchored.toml\n",
    "sub/inner/.gitignore": "*.local.toml\n",
    "ign/.gitignore": "*\n!.gitignore\n!keep.toml\n",
    "outer/.gitignore": "inner/\n",
    "outer/inner/.gitignore": "!file.toml\n",
    "neg/.gitignore": "/*\n!/keep/\n!/keep/**\n",
}

GIT_MATRIX_PATH_LINES = [
    "a.local.toml keep.local.toml sub/a.local.toml sub/keep.local.toml sub/inner/a.local.toml",
    "sub/inner/keep.local.toml build/x.toml x/build/y.toml sub/build/z.toml rootonly.toml",
    "sub/rootonly.toml secret.toml secret-keep.toml sub/secret2.toml .env.local sub/.env.local",
    "docs/a.tmp docs/x/a.tmp a/deep/b.priv a/b/deep/c.priv deep/d.priv excluded-by-info.toml",
    "sub/excluded-by-info.toml sub/subonly.toml sub/x/subonly.toml sub/anchored.toml",
    "sub/y/anchored.toml ign/other.toml ign/keep.toml ign/sub/keep.toml outer/inner/file.toml",
    "outer/other.toml neg/a.toml neg/keep/a.toml neg/keep/deep/b.toml plain.toml sub/plain.toml",
    "sub/inner/plain.toml",
]
GIT_MATRIX_PATHS = [path for line in GIT_MATRIX_PATH_LINES for path in line.split()]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs the git binary")
def test_matches_git_ignore_rules_agrees_with_git_check_ignore(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
    make_tree(root, GIT_MATRIX_PATHS, GIT_MATRIX_GITIGNORES)
    disagreements = []
    for relative in GIT_MATRIX_PATHS:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", relative], cwd=root, env=env
        )
        expected = result.returncode == 0
        assert result.returncode in (0, 1), result
        if matches_git_ignore_rules(root, root / relative) != expected:
            disagreements.append((relative, expected))
    assert not disagreements


# --- pathspec missing: loud only when it actually matters ---------------------------


@pytest.fixture
def no_pathspec(monkeypatch):
    monkeypatch.setitem(sys.modules, "pathspec", None)


def test_missing_pathspec_is_a_setup_error_inactive_status(project, no_pathspec):
    status = developer_status(project / "pyproject.toml")
    assert status.state is DeveloperState.INACTIVE
    assert status.setup_error
    assert "conclude[gitignore]" in status.reason


def test_missing_pathspec_makes_loading_raise(project, no_pathspec):
    status = developer_status(project / "pyproject.toml")
    with pytest.raises(ImportError, match=r"conclude\[gitignore\]"):
        load_developer_config(status, DEFAULTS, ["myapp"])
    # ...and the error names the file it is about.
    with pytest.raises(ImportError, match=r"developer config file .*\.conclude\.local\.toml"):
        load_developer_config(status, DEFAULTS, ["myapp"])
    with pytest.raises(ImportError):
        dev_app(project).resolve({}, env={})


def test_missing_pathspec_never_breaks_describe_sources(project, no_pathspec):
    assert "conclude[gitignore]" in dev_app(project).describe_sources()


def test_missing_pathspec_is_irrelevant_until_a_file_is_actually_configured(
    project, tmp_path, no_pathspec
):
    # Not opted in, not configured, file missing, no git tree: none of
    # these ever reach the ignore check, so a production install without
    # the extra is untouched.
    assert developer_status(None).state is DeveloperState.NOT_OPTED_IN
    assert developer_status(tmp_path / "nope.toml").state is DeveloperState.NOT_CONFIGURED
    (project / ".conclude.local.toml").unlink()
    missing = developer_status(project / "pyproject.toml")
    assert missing.reason == "file not found" and not missing.setup_error
    (project / ".conclude.local.toml").write_text("")
    (project / ".git").rmdir()
    no_git = developer_status(project / "pyproject.toml")
    assert no_git.reason == "not inside a git working tree" and not no_git.setup_error
    assert dev_app(project).resolve({}, env={})["size"] == 1  # no exception


# --- loading the file -----------------------------------------------------------------


def test_load_developer_config_reads_the_app_table(project):
    status = developer_status(project / "pyproject.toml")
    assert load_developer_config(status, DEFAULTS, ["myapp"]) == {"size": 6}


def test_load_developer_config_table_selection_and_unknown_keys(project):
    (project / ".conclude.local.toml").write_text(
        "[myapp]\nsize = 6\nunrelated = 1\n[mom]\nfilename = 'mom.csv'\n[mom.deck]\nsize = 9\n"
    )
    status = developer_status(project / "pyproject.toml")
    assert load_developer_config(status, DEFAULTS, ["myapp"]) == {"size": 6}
    assert load_developer_config(status, DEFAULTS, ["mom"]) == {"filename": "mom.csv"}
    assert load_developer_config(status, DEFAULTS, ["mom", "deck"]) == {
        "filename": "mom.csv",
        "size": 9,
    }


def test_load_developer_config_inactive_is_empty(project):
    (project / ".gitignore").write_text("")
    status = developer_status(project / "pyproject.toml")
    assert load_developer_config(status, DEFAULTS, ["myapp"]) == {}
    assert load_developer_config(developer_status(None), DEFAULTS, ["myapp"]) == {}


def test_load_developer_config_bad_toml_raises(project):
    (project / ".conclude.local.toml").write_text("not [valid")
    status = developer_status(project / "pyproject.toml")
    assert status.active
    with pytest.raises(ConfigFileError):
        load_developer_config(status, DEFAULTS, ["myapp"])


# --- merge.resolve ------------------------------------------------------------------


def test_merge_resolve_developer_sits_between_env_and_cli():
    base = {"defaults": {"size": 1}, "casters": {"size": int}}
    assert merge_resolve({}, {}, {"size": 2}, **base, developer={"size": 3})["size"] == 3
    assert merge_resolve({}, {"size": "4"}, {"size": 2}, **base, developer={"size": 3})["size"] == 3
    assert merge_resolve({"size": 5}, {"size": "4"}, {}, **base, developer={"size": 3})["size"] == 5
    # No developer layer: unchanged behavior.
    assert merge_resolve({}, {"size": "4"}, {"size": 2}, **base)["size"] == 4
    assert merge_resolve({}, {"size": "4"}, {}, **base, developer=None)["size"] == 4


def test_merge_resolve_developer_none_values_are_no_opinion():
    result = merge_resolve(
        {}, {"size": "4"}, {}, {"size": 1}, {"size": int}, developer={"size": None}
    )
    assert result["size"] == 4


# --- App -------------------------------------------------------------------------------


def test_pyproject_path_is_off_by_default():
    app = App("myapp", DEFAULTS)
    assert app.pyproject_path is None
    assert app.resolved_pyproject_path is None
    assert app.developer_status().state is DeveloperState.NOT_OPTED_IN
    assert app.load_developer_config() == {}


def test_pyproject_path_auto_and_explicit():
    assert App("myapp", DEFAULTS, pyproject_path=conclude.AUTO).resolved_pyproject_path == Path(
        "pyproject.toml"
    )
    custom = Path("/x/pyproject.toml")
    assert App("myapp", DEFAULTS, pyproject_path=custom).resolved_pyproject_path == custom


def test_auto_reads_pyproject_from_the_cwd(project, monkeypatch):
    monkeypatch.chdir(project)
    app = App("myapp", DEFAULTS, pyproject_path=conclude.AUTO, config_home_path=None)
    assert app.developer_status().active
    assert app.load_developer_config() == {"size": 6}
    assert app.describe_sources().splitlines()[-1] == (
        "  developer config  .conclude.local.toml -- configured, active"
    )


def test_developer_layer_ignored_when_not_opted_in(project):
    # The file exists and is gitignored, but the app never asked.
    app = App("myapp", DEFAULTS, config_home_path=None, config_cwd_path=None)
    assert app.resolve({}, env={})["size"] == 1


def test_developer_beats_env_and_loses_to_cli(project):
    app = dev_app(project)
    assert app.resolve({}, env={"size": "5"})["size"] == 6
    assert app.resolve({"size": 7}, env={"size": "5"})["size"] == 7


def test_full_precedence_chain_including_developer(project, tmp_path):
    def write(name, text):
        path = tmp_path / name
        path.write_text(text)
        return path

    system = write("system.toml", "[myapp]\nsize = 2\n")
    home = write("home.toml", "[myapp]\nsize = 3\n")
    cwd = write("cwd.toml", "[myapp]\nsize = 4\n")
    (project / ".conclude.local.toml").write_text("[myapp]\nsize = 6\n")

    def build(*, developer):
        return App(
            "myapp",
            DEFAULTS,
            config_system_path=system,
            config_home_path=home,
            config_cwd_path=cwd,
            pyproject_path=(project / "pyproject.toml") if developer else None,
        )

    without = build(developer=False)
    with_dev = build(developer=True)
    assert without.resolve({}, env={})["size"] == 4  # project layer
    assert without.resolve({}, env={"size": "5"})["size"] == 5  # env
    assert with_dev.resolve({}, env={"size": "5"})["size"] == 6  # developer
    assert with_dev.resolve({"size": 7}, env={"size": "5"})["size"] == 7  # CLI


def test_developer_only_overrides_the_keys_it_sets(project):
    app = dev_app(project)
    resolved = app.resolve({}, env={"filename": "env.csv", "size": "5"})
    assert resolved == {"filename": "env.csv", "size": 6, "loud": False}


def test_kill_switch_through_resolve(project, monkeypatch):
    app = dev_app(project)
    assert app.resolve({}, env={"size": "5"})["size"] == 6
    monkeypatch.setenv("MYAPP_DEVELOPER_CONFIG", "off")
    assert app.resolve({}, env={"size": "5"})["size"] == 5
    assert app.load_developer_config() == {}


def test_kill_switch_variable_name_follows_the_app_name(project):
    app = App("my-app", DEFAULTS, pyproject_path=project / "pyproject.toml", config_home_path=None)
    assert app.developer_status(environ={"MY_APP_DEVELOPER_CONFIG": "off"}).state is (
        DeveloperState.INACTIVE
    )
    assert app.developer_status(environ={"MYAPP_DEVELOPER_CONFIG": "off"}).active


def test_explicit_developer_argument_skips_loading(project):
    app = dev_app(project)
    assert app.resolve({}, env={}, developer={"size": 42})["size"] == 42
    assert app.resolve({}, env={}, developer={})["size"] == 1


def test_load_developer_config_with_a_chosen_table_path(project):
    (project / ".conclude.local.toml").write_text("[mom]\nsize = 8\n")
    app = dev_app(project)
    assert app.load_developer_config() == {}
    assert app.load_developer_config(["mom"]) == {"size": 8}
    config_file = {"filename": "f.csv"}
    resolved = app.resolve(
        {}, env={}, config_file=config_file, developer=app.load_developer_config(["mom"])
    )
    assert resolved["size"] == 8 and resolved["filename"] == "f.csv"


# --- describe_sources ---------------------------------------------------------------------


def developer_line(app, **kwargs):
    line = app.describe_sources(**kwargs).splitlines()[-1]
    assert line.startswith("  developer config  ")
    return line.removeprefix("  developer config  ")


def test_describe_sources_developer_not_opted_in():
    assert developer_line(App("myapp", DEFAULTS)) == "not opted in"


def test_describe_sources_developer_not_configured(tmp_path):
    app = App("myapp", DEFAULTS, pyproject_path=tmp_path / "pyproject.toml")
    assert developer_line(app).startswith("not configured (")


def test_describe_sources_developer_configured_inactive(project):
    (project / ".gitignore").write_text("")
    text = developer_line(dev_app(project))
    assert (
        text
        == f"{project / '.conclude.local.toml'} -- configured, inactive (not covered by .gitignore)"
    )


def test_describe_sources_developer_configured_active(project):
    assert developer_line(dev_app(project)) == (
        f"{project / '.conclude.local.toml'} -- configured, active"
    )


def test_describe_sources_reports_the_kill_switch(project):
    text = developer_line(dev_app(project), environ={"MYAPP_DEVELOPER_CONFIG": "off"})
    assert text.endswith("configured, inactive (disabled by MYAPP_DEVELOPER_CONFIG=off)")


def test_describe_sources_developer_row_is_aligned_with_the_others():
    lines = App("myapp", DEFAULTS).describe_sources().splitlines()[1:]
    # "  " + the widest label ("developer config", 16) + "  " -> values start at column 20.
    assert all(line[18:20] == "  " and line[20] != " " for line in lines)


def test_missing_pathspec_message_mentions_the_kill_switch_escape_hatch(project, no_pathspec):
    status = developer_status(project / "pyproject.toml", kill_switch_var="MYAPP_DEVELOPER_CONFIG")
    assert "MYAPP_DEVELOPER_CONFIG=off" in status.reason
    # Without a known kill switch the hint doesn't invent one.
    assert "=off" not in developer_status(project / "pyproject.toml").reason


def test_kill_switch_avoids_the_missing_pathspec_error(project, no_pathspec):
    # The production escape hatch: the file exists, pathspec isn't
    # installed, but the kill switch is checked first -- so nothing raises.
    app = dev_app(project)
    off = {"MYAPP_DEVELOPER_CONFIG": "off"}
    status = app.developer_status(environ=off)
    assert status.state is DeveloperState.INACTIVE and not status.setup_error
    assert app.load_developer_config(environ=off) == {}


def test_bad_developer_toml_error_says_which_file_it_is(project):
    (project / ".conclude.local.toml").write_text("not [valid")
    status = developer_status(project / "pyproject.toml")
    with pytest.raises(ConfigFileError, match=r"^developer config file .*\.conclude\.local\.toml"):
        load_developer_config(status, DEFAULTS, ["myapp"])


# --- a dotenv-format developer file (.env.local) -------------------------------------


@pytest.fixture
def dotenv_project(project):
    """Like ``project``, but the developer file is a gitignored dotenv
    file, ``.env.local``, keyed by the app's environment variable names."""
    (project / ".conclude.local.toml").unlink()
    (project / ".env.local").write_text("MYAPP_SIZE=8\nMYAPP_FILENAME=local.csv\nUNRELATED=1\n")
    (project / ".gitignore").write_text(".env.local\n")
    (project / "pyproject.toml").write_text('[tool.conclude.developer]\nconfig = ".env.local"\n')
    return project


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (".developer.toml", "toml"),
        ("dev.TOML", "toml"),
        (".toml", "toml"),
        (".env.local", "dotenv"),
        (".env", "dotenv"),
        ("local", "dotenv"),
        ("dev.json", "dotenv"),
        ("dev.toml.bak", "dotenv"),
    ],
)
def test_format_follows_the_file_name(name, expected):
    status = conclude.DeveloperStatus(DeveloperState.ACTIVE, Path(name))
    assert status.format == expected


def test_format_is_none_until_a_file_is_named():
    assert developer_status(None).format is None


def test_a_dotenv_file_goes_through_the_same_guard(dotenv_project):
    status = developer_status(dotenv_project / "pyproject.toml")
    assert status.active and status.format == "dotenv"
    (dotenv_project / ".gitignore").write_text("")
    assert developer_status(dotenv_project / "pyproject.toml").reason == "not covered by .gitignore"


def test_a_dotenv_file_is_keyed_by_the_apps_env_var_names(dotenv_project):
    # Raw strings, like the environment layer; the unrelated variable is ignored.
    assert dev_app(dotenv_project).load_developer_config() == {
        "size": "8",
        "filename": "local.csv",
    }


def test_a_dotenv_file_can_use_unprefixed_names_via_env_vars(dotenv_project):
    (dotenv_project / ".env.local").write_text("SIZE=9\nMYAPP_SIZE=1\n")
    app = dev_app(dotenv_project, env_vars={"size": "SIZE"})
    assert app.load_developer_config() == {"size": "9"}


def test_dotenv_developer_layer_beats_env_and_loses_to_cli(dotenv_project):
    app = dev_app(dotenv_project)
    assert app.resolve({}, env={"size": "5"})["size"] == 8  # cast to int, beats env
    assert app.resolve({"size": 7}, env={"size": "5"})["size"] == 7


def test_dotenv_syntax_is_the_same_as_dot_env(dotenv_project):
    (dotenv_project / ".env.local").write_text(
        "# a comment\nexport MYAPP_FILENAME='a b'\nMYAPP_SIZE=\"4\"\n"
    )
    assert dev_app(dotenv_project).load_developer_config() == {"filename": "a b", "size": "4"}


def test_dotenv_developer_file_has_no_tables(dotenv_project):
    app = dev_app(dotenv_project)
    assert app.load_developer_config(["mom"]) == app.load_developer_config()


def test_an_empty_dotenv_value_behaves_like_an_empty_environment_variable(dotenv_project):
    # Same rule as the environment layer: an empty value is cast (to None
    # for an int), it is not "no opinion" -- that is what an absent line is.
    (dotenv_project / ".env.local").write_text("MYAPP_SIZE=\n")
    app = dev_app(dotenv_project)
    assert app.resolve({}, env={"size": "5"})["size"] is None
    assert app.resolve({}, env={"size": ""})["size"] is None
    (dotenv_project / ".env.local").write_text("# MYAPP_SIZE=\n")
    assert app.resolve({}, env={"size": "5"})["size"] == 5


def test_kill_switch_covers_a_dotenv_developer_file(dotenv_project):
    app = dev_app(dotenv_project)
    off = {"MYAPP_DEVELOPER_CONFIG": "off"}
    assert app.developer_status(environ=off).state is DeveloperState.INACTIVE
    assert app.load_developer_config(environ=off) == {}


def test_missing_pathspec_applies_to_a_dotenv_file_too(dotenv_project, no_pathspec):
    with pytest.raises(ImportError, match=r"developer config file .*\.env\.local"):
        dev_app(dotenv_project).load_developer_config()


def test_loading_a_dotenv_file_without_env_vars_is_a_clear_error(dotenv_project):
    status = developer_status(dotenv_project / "pyproject.toml")
    with pytest.raises(ValueError, match="env_vars"):
        load_developer_config(status, DEFAULTS, ["myapp"])
    assert load_developer_config(status, DEFAULTS, ["myapp"], {"size": "MYAPP_SIZE"}) == {
        "size": "8"
    }


def test_toml_developer_file_is_unaffected_by_env_vars(project):
    status = developer_status(project / "pyproject.toml")
    assert status.format == "toml"
    assert load_developer_config(status, DEFAULTS, ["myapp"], {"size": "SIZE"}) == {"size": 6}


def test_describe_sources_for_a_dotenv_developer_file(dotenv_project):
    assert developer_line(dev_app(dotenv_project)) == (
        f"{dotenv_project / '.env.local'} -- configured, active"
    )


def test_format_env_writes_a_skeleton_the_developer_layer_reads_back(dotenv_project):
    app = dev_app(dotenv_project)
    (dotenv_project / ".env.local").write_text(app.format_env() + "\n")
    assert app.resolve({}, env={}, config_file={}) == app.resolved_defaults
