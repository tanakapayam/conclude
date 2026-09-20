import sys

import pytest

import conclude
from conclude import App, DotenvState, opt
from conclude.env import dotenv_status, load_env

pytest.importorskip("pathspec")

DEFAULTS = {"filename": opt(str), "size": 1}
ENV_VARS = {"filename": "MYAPP_FILENAME", "size": "MYAPP_SIZE"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ["MYAPP_FILENAME", "MYAPP_SIZE", "MYAPP_DEVELOPER_CONFIG"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path):
    """A git working tree whose .gitignore covers an existing .env."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".gitignore").write_text(".env\n")
    (root / ".env").write_text("MYAPP_SIZE=7\nMYAPP_FILENAME=dotenv.csv\n")
    return root


def app_for(path, **kwargs):
    kwargs.setdefault("dotenv_require_gitignored", True)
    return App(
        "myapp", DEFAULTS, dotenv_path=path, config_home_path=None, config_cwd_path=None, **kwargs
    )


# --- defaults and the unguarded behavior are unchanged -----------------------------


def test_the_guard_is_off_by_default():
    app = App("myapp", DEFAULTS)
    assert app.dotenv_require_gitignored is False
    assert app.dotenv_status().state is DotenvState.DISABLED
    assert str(app.dotenv_status()) == "disabled"


def test_no_dotenv_path_stays_disabled_even_when_a_guard_is_requested():
    app = App("myapp", DEFAULTS, dotenv_require_gitignored=True)
    assert app.dotenv_status().state is DotenvState.DISABLED
    assert not app.dotenv_status().guarded


def test_unguarded_opt_in_is_active_whether_or_not_the_file_exists(tmp_path):
    path = tmp_path / ".env"  # not in a git tree, does not exist
    status = dotenv_status(path)
    assert status.state is DotenvState.ACTIVE and status.active and not status.guarded
    assert str(status) == str(path)


def test_unguarded_dotenv_is_read_outside_any_git_tree(tmp_path):
    (tmp_path / ".env").write_text("MYAPP_SIZE=5\n")
    app = app_for(tmp_path / ".env", dotenv_require_gitignored=False)
    assert app.load_env(environ={}) == {"size": "5"}


# --- guarded: the four outcomes ------------------------------------------------------


def test_guarded_and_ignored_is_active(repo):
    status = app_for(repo / ".env").dotenv_status()
    assert status.state is DotenvState.ACTIVE and status.guarded and status.reason is None
    assert str(status) == f"{repo / '.env'} -- active (gitignored)"


def test_guarded_file_not_found(repo):
    (repo / ".env").unlink()
    status = app_for(repo / ".env").dotenv_status()
    assert status.state is DotenvState.INACTIVE and status.reason == "file not found"
    assert str(status) == f"{repo / '.env'} -- inactive (file not found)"


def test_guarded_outside_a_git_tree(repo):
    (repo / ".git").rmdir()
    status = app_for(repo / ".env").dotenv_status()
    assert status.reason == "not inside a git working tree"


def test_guarded_but_not_gitignored(repo):
    (repo / ".gitignore").write_text("something-else\n")
    status = app_for(repo / ".env").dotenv_status()
    assert status.state is DotenvState.INACTIVE and status.reason == "not covered by .gitignore"
    assert not status.setup_error


# --- what is actually read -------------------------------------------------------------


def test_active_guarded_dotenv_is_read(repo):
    assert app_for(repo / ".env").load_env(environ={}) == {"size": "7", "filename": "dotenv.csv"}


def test_inactive_guarded_dotenv_contributes_nothing(repo):
    (repo / ".gitignore").write_text("")
    app = app_for(repo / ".env")
    assert app.load_env(environ={}) == {}
    # ...but the real environment is unaffected.
    assert app.load_env(environ={"MYAPP_SIZE": "3"}) == {"size": "3"}


def test_the_real_environment_still_beats_an_active_dotenv(repo):
    env = app_for(repo / ".env").load_env(environ={"MYAPP_SIZE": "3"})
    assert env == {"size": "3", "filename": "dotenv.csv"}


def test_resolve_end_to_end(repo):
    assert app_for(repo / ".env").resolve({}, developer={})["size"] == 7
    (repo / ".gitignore").write_text("")
    assert app_for(repo / ".env").resolve({}, developer={})["size"] == 1


def test_auto_path_is_relative_to_the_working_directory(repo, monkeypatch):
    monkeypatch.chdir(repo)
    app = App(
        "myapp",
        DEFAULTS,
        dotenv_path=conclude.AUTO,
        dotenv_require_gitignored=True,
        config_home_path=None,
        config_cwd_path=None,
    )
    assert app.dotenv_status().active
    assert app.load_env(environ={})["size"] == "7"


def test_load_env_function_level(repo):
    assert load_env(ENV_VARS, {}, dotenv_path=repo / ".env", require_gitignored=True) == {
        "size": "7",
        "filename": "dotenv.csv",
    }
    (repo / ".gitignore").write_text("")
    assert load_env(ENV_VARS, {}, dotenv_path=repo / ".env", require_gitignored=True) == {}
    assert load_env(ENV_VARS, {}, dotenv_path=repo / ".env") == {
        "size": "7",
        "filename": "dotenv.csv",
    }


def test_the_developer_kill_switch_does_not_touch_dotenv(repo, monkeypatch):
    # Deliberate: .env has no kill switch of its own, and the developer
    # file's switch is not a general "no local files" switch.
    monkeypatch.setenv("MYAPP_DEVELOPER_CONFIG", "off")
    assert app_for(repo / ".env").dotenv_status().active


# --- describe_sources ----------------------------------------------------------------------


def env_row(app):
    row = [line for line in app.describe_sources().splitlines() if ".env file" in line][0]
    return row.split("  ", 2)[2].strip()


def test_describe_sources_env_row_in_every_state(repo, tmp_path):
    assert env_row(App("myapp", DEFAULTS)) == "disabled"
    assert env_row(app_for(tmp_path / "x.env", dotenv_require_gitignored=False)) == str(
        tmp_path / "x.env"
    )
    assert env_row(app_for(repo / ".env")) == f"{repo / '.env'} -- active (gitignored)"
    (repo / ".gitignore").write_text("")
    assert env_row(app_for(repo / ".env")) == (
        f"{repo / '.env'} -- inactive (not covered by .gitignore)"
    )


# --- pathspec missing --------------------------------------------------------------------------


@pytest.fixture
def no_pathspec(monkeypatch):
    monkeypatch.setitem(sys.modules, "pathspec", None)


def test_missing_pathspec_is_a_setup_error(repo, no_pathspec):
    status = app_for(repo / ".env").dotenv_status()
    assert status.state is DotenvState.INACTIVE and status.setup_error
    assert "conclude[gitignore]" in status.reason
    assert "stop requiring it to be gitignored" in status.reason


def test_missing_pathspec_makes_loading_raise_naming_the_file(repo, no_pathspec):
    app = app_for(repo / ".env")
    with pytest.raises(ImportError, match=r"^\.env file .*\.env: .*conclude\[gitignore\]"):
        app.load_env(environ={})
    with pytest.raises(ImportError):
        app.resolve({}, developer={})


def test_missing_pathspec_never_breaks_describe_sources(repo, no_pathspec):
    assert "conclude[gitignore]" in app_for(repo / ".env").describe_sources()


def test_missing_pathspec_is_irrelevant_without_a_guard(repo, no_pathspec):
    app = app_for(repo / ".env", dotenv_require_gitignored=False)
    assert app.load_env(environ={})["size"] == "7"


def test_missing_pathspec_is_irrelevant_until_the_guard_gets_that_far(repo, no_pathspec):
    (repo / ".env").unlink()
    app = app_for(repo / ".env")
    assert app.dotenv_status().reason == "file not found"
    assert app.load_env(environ={}) == {}
