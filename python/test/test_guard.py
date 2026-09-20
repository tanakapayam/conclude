import dataclasses
import sys

import pytest

from conclude.guard import GuardResult, check_guard

pytest.importorskip("pathspec")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".gitignore").write_text("private.toml\n")
    (root / "private.toml").write_text("")
    return root


def test_active_when_the_file_exists_in_a_git_tree_and_is_ignored(repo):
    assert check_guard(repo / "private.toml") == GuardResult(True)


def test_file_not_found(repo):
    result = check_guard(repo / "missing.toml")
    assert result == GuardResult(False, "file not found")


def test_not_inside_a_git_tree(repo):
    (repo / ".git").rmdir()
    assert check_guard(repo / "private.toml") == GuardResult(False, "not inside a git working tree")


def test_not_ignored(repo):
    (repo / "public.toml").write_text("")
    assert check_guard(repo / "public.toml") == GuardResult(False, "not covered by .gitignore")


def test_checks_run_in_order_first_failure_wins(repo, tmp_path):
    # Kill switch beats "file not found"; "file not found" beats everything after it.
    off = {"X": "off"}
    assert check_guard(repo / "missing.toml", kill_switch_var="X", environ=off).reason == (
        "disabled by X=off"
    )
    assert check_guard(repo / "missing.toml", kill_switch_var="X", environ={}).reason == (
        "file not found"
    )
    # A file outside any repo is "not in a git tree", never "not ignored".
    outside = tmp_path / "outside.toml"
    outside.write_text("")
    assert check_guard(outside).reason == "not inside a git working tree"


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "No", " off "])
def test_kill_switch_values(repo, value):
    result = check_guard(repo / "private.toml", kill_switch_var="X", environ={"X": value})
    assert not result.active and result.reason == f"disabled by X={value.strip()}"


@pytest.mark.parametrize("value", ["on", "1", "true", "", "anything"])
def test_other_kill_switch_values_do_nothing(repo, value):
    assert check_guard(repo / "private.toml", kill_switch_var="X", environ={"X": value}).active


def test_no_kill_switch_variable_means_no_kill_switch(repo):
    assert check_guard(repo / "private.toml", environ={"X": "off"}).active


def test_kill_switch_defaults_to_the_real_environment(repo, monkeypatch):
    monkeypatch.setenv("CONCLUDE_TEST_SWITCH", "off")
    assert not check_guard(repo / "private.toml", kill_switch_var="CONCLUDE_TEST_SWITCH").active


# --- pathspec missing --------------------------------------------------------------


@pytest.fixture
def no_pathspec(monkeypatch):
    monkeypatch.setitem(sys.modules, "pathspec", None)


def test_missing_pathspec_is_a_setup_error(repo, no_pathspec):
    result = check_guard(repo / "private.toml")
    assert not result.active and result.setup_error
    assert result.reason.endswith("pip install 'conclude[gitignore]'")


def test_escape_hint_defaults_to_the_kill_switch(repo, no_pathspec):
    result = check_guard(repo / "private.toml", kill_switch_var="X", environ={})
    assert result.reason.endswith("(or set X=off to skip the file)")


def test_explicit_escape_hint_wins(repo, no_pathspec):
    result = check_guard(repo / "private.toml", kill_switch_var="X", escape_hint="or do Y")
    assert result.reason.endswith("(or do Y)")


def test_missing_pathspec_is_never_reached_by_earlier_failures(repo, no_pathspec):
    assert not check_guard(repo / "missing.toml").setup_error
    (repo / ".git").rmdir()
    assert not check_guard(repo / "private.toml").setup_error
    off = check_guard(repo / "private.toml", kill_switch_var="X", environ={"X": "off"})
    assert not off.setup_error


def test_guard_result_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        GuardResult(True).active = False  # type: ignore[misc]
