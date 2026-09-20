"""The repository's own housekeeping: the .gitignore covers what it should
and nothing that ships, and the CI workflows test what the package claims
and pin every third-party action to a commit."""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from conclude.guard import matches_git_ignore_rules

pytest.importorskip("pathspec")

ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = ROOT / ".gitignore"
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
PUBLISH = WORKFLOWS / "publish.yml"

pytestmark = pytest.mark.skipif(
    not (GITIGNORE.exists() and CI.exists() and PUBLISH.exists()),
    reason="repository housekeeping files are not part of this checkout",
)

# Names the docs tell people to use for private files.
PRIVATE = [".env", ".env.local", ".developer.toml", ".remind.local.toml", ".conclude.local.toml"]
# Things that must always be tracked, and shipped in the sdist.
SHIPPED = [
    ".gitignore",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/publish.yml",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "docs/comparison.md",
    "docs/guide.md",
    "docs/reference.md",
    "pyproject.toml",
    "src/conclude/__init__.py",
    "src/conclude/py.typed",
    "tests/test_docs.py",
]
# Things that must never be tracked.
GENERATED = [
    ".DS_Store",
    ".coverage",
    ".mypy_cache/x",
    ".pytest_cache/v/cache",
    ".ruff_cache/x",
    ".venv/bin/python",
    ".venv-plain/bin/python",
    ".venv-wheel/bin/python",
    "build/lib/conclude/app.py",
    "dist/conclude-1.0.0.tar.gz",
    "htmlcov/index.html",
    "src/conclude.egg-info/PKG-INFO",
    "src/conclude/__pycache__/app.cpython-312.pyc",
    "tests/__pycache__/x.cpython-313-pytest-8.0.pyc",
    "venv/bin/python",
]


@pytest.fixture
def tree(tmp_path):
    """A git working tree with this repository's .gitignore."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(GITIGNORE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def matches(tree, relative):
    path = tree / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return matches_git_ignore_rules(tree, path)


@pytest.mark.parametrize("name", PRIVATE)
def test_private_files_are_ignored(tree, name):
    assert matches(tree, name)


@pytest.mark.parametrize("name", GENERATED)
def test_generated_files_are_ignored(tree, name):
    assert matches(tree, name)


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_files_are_not_ignored(tree, name):
    assert not matches(tree, name)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs the git binary")
def test_the_gitignore_agrees_with_real_git(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True, env=env)
    repo = tmp_path / "repo"
    (repo / ".gitignore").write_text(GITIGNORE.read_text(encoding="utf-8"), encoding="utf-8")
    for relative in [*PRIVATE, *GENERATED, *SHIPPED]:
        if relative == ".gitignore":
            continue
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        expected = (
            subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", relative], cwd=repo, env=env
            ).returncode
            == 0
        )
        assert matches_git_ignore_rules(repo, path) == expected, relative


# --- workflows -----------------------------------------------------------------------


def workflow_texts():
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))}


def test_every_third_party_action_is_pinned_to_a_commit_with_a_version_comment():
    pinned = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*$")
    found = 0
    for name, text in workflow_texts().items():
        for line in text.splitlines():
            match = re.match(r"\s*(?:-\s*)?uses:\s*(.+?)\s*$", line)
            if match and not match.group(1).startswith("./"):
                found += 1
                assert pinned.match(match.group(1)), (name, match.group(1))
    assert found


def test_ci_tests_exactly_the_python_versions_the_package_claims():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    claimed = {
        c.rsplit(" :: ", 1)[1]
        for c in project["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    }
    matrix = re.search(r"python-version:\s*\[(.*?)\]", CI.read_text(encoding="utf-8"))
    assert matrix
    tested = set(re.findall(r"\d+\.\d+", matrix.group(1)))
    assert tested == claimed
    assert project["requires-python"] == f">={min(claimed, key=lambda v: int(v.split('.')[1]))}"


def test_ci_runs_every_check_it_promises():
    text = CI.read_text(encoding="utf-8")
    for command in [
        "uv run pytest",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv build",
        "twine check --strict",
    ]:
        assert command in text, command


def test_ci_is_reusable_and_publish_runs_it_first():
    assert re.search(r"^\s+workflow_call:", CI.read_text(encoding="utf-8"), re.M)
    publish = PUBLISH.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in publish
    assert re.search(r"needs:\s*ci\b", publish)


def test_publishing_uses_trusted_publishing_not_a_stored_token():
    publish = PUBLISH.read_text(encoding="utf-8")
    assert "id-token: write" in publish
    assert "password:" not in publish and "secrets." not in publish
    for environment in ["pypi", "testpypi"]:
        assert re.search(rf"name:\s*{environment}\b", publish), environment


def test_only_the_publish_jobs_may_write_the_oidc_token():
    text = PUBLISH.read_text(encoding="utf-8")
    top_level = text.split("\njobs:", 1)[0]
    assert "id-token" not in top_level
    assert "id-token" not in CI.read_text(encoding="utf-8")
