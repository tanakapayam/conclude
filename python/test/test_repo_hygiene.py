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

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # python/, this package's own root
REPO_ROOT = PACKAGE_ROOT.parent  # the monorepo root -- .git, .github, spec, docs, node/
GITIGNORE = REPO_ROOT / ".gitignore"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "python-ci.yml"
PUBLISH = WORKFLOWS / "python-publish.yml"

pytestmark = pytest.mark.skipif(
    not (GITIGNORE.exists() and CI.exists() and PUBLISH.exists()),
    reason="repository housekeeping files are not part of this checkout",
)

# Names the docs tell people to use for private files.
PRIVATE = [".env", ".env.local", ".developer.toml", ".remind.local.toml", ".conclude.local.toml"]
# Things that must always be tracked. Not a claim about what any one
# language's own package ships -- see sdist_guard_pattern() for that, on the
# Python side -- just that git must not be ignoring them.
SHIPPED = [
    ".gitignore",
    ".github/dependabot.yml",
    ".github/workflows/bash-ci.yml",
    ".github/workflows/bash-publish.yml",
    ".github/workflows/node-ci.yml",
    ".github/workflows/node-publish.yml",
    ".github/workflows/python-ci.yml",
    ".github/workflows/python-publish.yml",
    "LICENSE",
    "README.md",
    "bash/.shellcheckrc",
    "bash/CHANGELOG.md",
    "bash/LICENSE",
    "bash/README.md",
    "bash/RELEASING.md",
    "bash/scripts/install-bash.sh",
    "bash/scripts/smoke.sh",
    "bash/src/conclude.sh",
    "bash/test/.shellcheckrc",
    "bash/test/casters.bats",
    "bash/test/config_layers.bats",
    "bash/test/config_tables.bats",
    "bash/test/dotenv.bats",
    "bash/test/gitignore.bats",
    "bash/test/guard.bats",
    "bash/test/invocation.bats",
    "bash/test/merge.bats",
    "bash/test/naming.bats",
    "bash/test/resolve.bats",
    "bash/test/sources.bats",
    "bash/test/templates.bats",
    "docs/bash/guide.md",
    "docs/bash/reference.md",
    "docs/concept.md",
    "docs/node/guide.md",
    "docs/node/reference.md",
    "docs/python/comparison.md",
    "docs/python/guide.md",
    "docs/python/reference.md",
    "node/CHANGELOG.md",
    "node/LICENSE",
    "node/README.md",
    "node/package-lock.json",
    "node/RELEASING.md",
    "node/package.json",
    "node/scripts/registry.mjs",
    "node/scripts/rehearse.mjs",
    "node/scripts/smoke.mjs",
    "node/scripts/verdaccio.yaml",
    "node/src/define.ts",
    "node/src/index.ts",
    "node/src/invocation.ts",
    "node/test/config.test.ts",
    "node/test/docs.test.ts",
    "node/test/package.test.ts",
    "node/test/spec.test.ts",
    "python/CHANGELOG.md",
    "python/LICENSE",
    "python/README.md",
    "python/RELEASING.md",
    "python/hatch_build.py",
    "python/pyproject.toml",
    "python/src/conclude/__init__.py",
    "python/src/conclude/py.typed",
    "python/test/test_docs.py",
    "python/test/test_spec.py",
    "spec/README.md",
    "spec/casters.json",
    "spec/invocation.json",
]
# Things that must never be tracked. A few (.DS_Store, *.tgz) are tested
# unprefixed since the pattern that catches them is unanchored -- it matches
# at any depth, so where exactly is incidental.
GENERATED = [
    ".DS_Store",
    "node/.verdaccio-storage/htpasswd",
    "node/dist/index.d.ts",
    "node/dist/index.js",
    "node/node_modules/smol-toml/package.json",
    "node/tsconfig.tsbuildinfo",
    "python/.coverage",
    "python/.mypy_cache/x",
    "python/.pytest_cache/v/cache",
    "python/.ruff_cache/x",
    "python/.venv-plain/bin/python",
    "python/.venv-wheel/bin/python",
    "python/.venv/bin/python",
    "python/build/lib/conclude/app.py",
    "python/dist/conclude-1.0.0.tar.gz",
    "python/htmlcov/index.html",
    "python/src/conclude.egg-info/PKG-INFO",
    "python/src/conclude/__pycache__/app.cpython-312.pyc",
    "python/test/__pycache__/x.cpython-313-pytest-8.0.pyc",
    "tanakapayam-conclude-0.1.0.tgz",
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
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
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
    assert "uses: ./.github/workflows/python-ci.yml" in publish
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


def test_runners_are_pinned_not_latest():
    # `ubuntu-latest` moves to a new OS on GitHub's schedule; move on ours.
    found = 0
    for name, text in workflow_texts().items():
        for value in re.findall(r"runs-on:\s*(\S+)", text):
            found += 1
            assert not value.endswith("-latest"), (name, value)
    assert found


def test_the_sdist_leaves_out_repository_plumbing():
    hatch = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "hatch"
    ]
    exclude = hatch["build"]["targets"]["sdist"]["exclude"]
    assert "/uv.lock" in exclude
    assert "twine check --strict" in CI.read_text(encoding="utf-8")
    assert "The sdist contains files that should not ship" in CI.read_text(encoding="utf-8")


def test_the_sdist_pulls_in_spec_and_this_packages_docs_from_outside_python():
    # .github/ and node/ are structurally impossible to include now (they're
    # outside pyproject.toml's own project root) -- what needs a positive
    # check is that spec/ and docs/python/ are still pulled in on purpose.
    hatch = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "hatch"
    ]
    assert hatch["build"]["hooks"]["custom"]["path"] == "hatch_build.py"
    hook = (PACKAGE_ROOT / "hatch_build.py").read_text(encoding="utf-8")
    assert 'force_include[str(repo_root / "spec")] = "spec"' in hook
    assert 'force_include[str(repo_root / "docs" / "python")] = "docs"' in hook
    assert 'if self.target_name != "sdist"' in hook  # never the wheel


# --- the Node package ------------------------------------------------------------------


NODE = REPO_ROOT / "node"
NODE_CI = WORKFLOWS / "node-ci.yml"
NODE_PUBLISH = WORKFLOWS / "node-publish.yml"


def job_blocks(workflow):
    """``{job name: its text}`` for the top-level jobs of a workflow, in order."""
    body = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def release_guard_prefixes(workflow_text):
    """Every '<lang>-v' prefix a release-triggered gate mentions, via
    startsWith(github.event.release.tag_name, '<lang>-v') -- regardless of
    whether it's used as a positive self-match ("only run for my own tag")
    or a negative exclusion ("skip theirs")."""
    return set(
        re.findall(
            r"startsWith\(github\.event\.release\.tag_name,\s*'([a-z]+-v)'\)",
            workflow_text,
        )
    )


def ignores_other_languages_releases(workflow_text, own_prefix, other_prefixes):
    mentioned = release_guard_prefixes(workflow_text)
    # A positive self-match excludes every other language for free; a
    # negative-exclusion style instead needs each one named explicitly.
    return own_prefix in mentioned or other_prefixes <= mentioned


@pytest.mark.skipif(not NODE.is_dir(), reason="there is no node/ package in this checkout")
class TestNodePackage:
    def test_its_license_is_a_copy_of_the_root_license(self):
        # npm packs only the package directory, so the package carries its own copy.
        assert (NODE / "LICENSE").read_text(encoding="utf-8") == (REPO_ROOT / "LICENSE").read_text(
            encoding="utf-8"
        )

    def test_ci_tests_the_engine_floor_and_no_older_node(self):
        import json

        engines = json.loads((NODE / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
        floor = int(re.fullmatch(r">=(\d+)(?:\.\d+)*", engines).group(1))
        matrix = re.search(r"node:\s*\[(.*?)\]", NODE_CI.read_text(encoding="utf-8"))
        assert matrix
        tested = {int(v) for v in re.findall(r"\d+", matrix.group(1))}
        assert floor in tested and min(tested) == floor

    def test_ci_runs_the_typecheck_the_fixtures_and_the_tarball_smoke_test(self):
        text = NODE_CI.read_text(encoding="utf-8")
        for command in ["npm ci", "npm run typecheck", "npm test", "npm run smoke"]:
            assert command in text, command

    def test_ci_is_reusable_and_publish_runs_it_first(self):
        assert re.search(r"^\s+workflow_call:", NODE_CI.read_text(encoding="utf-8"), re.M)
        publish = NODE_PUBLISH.read_text(encoding="utf-8")
        assert "uses: ./.github/workflows/node-ci.yml" in publish
        assert re.search(r"needs:\s*ci\b", publish)

    def test_publishing_uses_trusted_publishing_and_a_rehearsal_is_the_default(self):
        publish = NODE_PUBLISH.read_text(encoding="utf-8")
        assert "--provenance" in publish
        assert "NPM_TOKEN" not in publish
        # The only secret in play is the workflow's own token, for GitHub Packages.
        assert set(re.findall(r"secrets\.(\w+)", publish)) <= {"GITHUB_TOKEN"}
        assert re.search(r"mode:.*?default:\s*dry-run", publish, re.S)
        top_level = publish.split("\njobs:", 1)[0]
        assert "id-token" not in top_level and "packages: write" not in top_level
        assert "id-token" not in NODE_CI.read_text(encoding="utf-8")

    def test_each_language_ignores_the_other_languages_releases(self):
        assert ignores_other_languages_releases(
            NODE_PUBLISH.read_text(encoding="utf-8"), "node-v", {"python-v", "bash-v"}
        )
        assert ignores_other_languages_releases(
            PUBLISH.read_text(encoding="utf-8"), "python-v", {"node-v"}
        )

    def test_the_package_stays_private_until_it_is_ready_to_publish(self):
        # A deliberate gate: flip it (and the CHANGELOG) in the release that publishes.
        import json

        package = json.loads((NODE / "package.json").read_text(encoding="utf-8"))
        if not package.get("private"):
            changelog = (NODE / "CHANGELOG.md").read_text(encoding="utf-8")
            assert f"## [{package['version']}]" in changelog

    def test_publishing_stages_first_and_production_waits_behind_an_approval_gate(self):
        publish = NODE_PUBLISH.read_text(encoding="utf-8")
        jobs = job_blocks(publish)
        assert list(jobs) == ["ci", "build", "stage", "production"]
        stage, production = jobs["stage"], jobs["production"]

        # Staging: GitHub Packages, its own environment, and nothing that can publish to npm.
        assert re.search(r"needs:\s*build\b", stage)
        assert "npm.pkg.github.com" in stage and "packages: write" in stage
        assert re.search(r"name:\s*npm-staging\b", stage)
        assert "id-token" not in stage and "--provenance" not in stage

        # Production: after staging, release-only, behind the `npm` environment (the approval gate).
        assert re.search(r"needs:\s*\[build,\s*stage\]", production)
        assert re.search(r"^\s+if:\s*github\.event_name == 'release'\s*$", production, re.M)
        assert re.search(r"environment:\s*\n\s+name:\s*npm\s*\n", production)
        assert "id-token: write" in production and "--provenance" in production
        assert "npm.pkg.github.com" not in production and "packages: write" not in production

        # ...and it publishes the tarball that was staged, after checking it is that tarball.
        assert "needs.stage.outputs.integrity" in production
        assert '"$local" != "$STAGED"' in production and '"$local" != "$BUILT"' in production
        assert re.search(r"npm publish .*\$TARBALL", production)
        assert "--expect-provenance" in production

    def test_the_release_pipeline_is_rehearsed_against_a_local_registry_in_ci(self):
        ci = NODE_CI.read_text(encoding="utf-8")
        assert "npm run rehearse" in ci and re.search(r"verdaccio@\d+\.\d+\.\d+", ci)
        for script in ["registry.mjs", "rehearse.mjs", "verdaccio.yaml"]:
            assert (NODE / "scripts" / script).exists(), script


# --- the Bash package -------------------------------------------------------------------


BASH = REPO_ROOT / "bash"
BASH_CI = WORKFLOWS / "bash-ci.yml"
BASH_PUBLISH = WORKFLOWS / "bash-publish.yml"


@pytest.mark.skipif(not BASH.is_dir(), reason="there is no bash/ package in this checkout")
class TestBashPackage:
    def test_its_license_is_a_copy_of_the_root_license(self):
        assert (BASH / "LICENSE").read_text(encoding="utf-8") == (REPO_ROOT / "LICENSE").read_text(
            encoding="utf-8"
        )

    def test_ci_tests_exactly_the_bash_version_the_library_requires(self):
        version_gate = (BASH / "src" / "conclude.sh").read_text(encoding="utf-8")
        floor = re.search(r"BASH_VERSINFO\[1\] < (\d+)", version_gate)
        assert floor, "couldn't find the minor-version floor in conclude.sh's own version gate"
        matrix = re.search(r'bash:\s*\["([\d.]+)"\]', BASH_CI.read_text(encoding="utf-8"))
        assert matrix, "couldn't find the CI matrix's bash: [...] version"
        assert matrix.group(1) == f"5.{floor.group(1)}"

    def test_ci_runs_every_check_it_promises(self):
        text = BASH_CI.read_text(encoding="utf-8")
        for command in ["shellcheck src/conclude.sh", "scripts/smoke.sh", "bats test/"]:
            assert command in text

    def test_ci_is_reusable_and_publish_runs_it_first(self):
        assert re.search(r"^\s+workflow_call:", BASH_CI.read_text(encoding="utf-8"), re.M)
        publish = BASH_PUBLISH.read_text(encoding="utf-8")
        assert "uses: ./.github/workflows/bash-ci.yml" in publish
        assert re.search(r"needs:\s*ci\b", publish)

    def test_each_language_ignores_the_other_languages_releases(self):
        assert ignores_other_languages_releases(
            BASH_PUBLISH.read_text(encoding="utf-8"), "bash-v", {"python-v", "node-v"}
        )
        assert ignores_other_languages_releases(
            PUBLISH.read_text(encoding="utf-8"), "python-v", {"bash-v"}
        )

    def test_publishing_has_no_stored_secret_and_waits_behind_an_approval_gate(self):
        publish = BASH_PUBLISH.read_text(encoding="utf-8")
        assert set(re.findall(r"secrets\.(\w+)", publish)) == set()
        assert "GH_TOKEN: ${{ github.token }}" in publish

        jobs = job_blocks(publish)
        assert list(jobs) == ["ci", "build", "production"]
        production = jobs["production"]
        assert re.search(r"needs:\s*build\b", production)
        assert re.search(r"environment:\s*\n\s+name:\s*bash-release\s*\n", production)
        assert "contents: write" in production
        assert "contents: write" not in publish.split("\njobs:", 1)[0]

    def test_the_released_file_is_verified_byte_for_byte(self):
        production = job_blocks(BASH_PUBLISH.read_text(encoding="utf-8"))["production"]
        assert '"$actual" != "$BUILT"' in production
        assert production.count("sha256sum") >= 2

    def test_a_manual_run_is_a_rehearsal_that_never_reaches_production(self):
        publish = BASH_PUBLISH.read_text(encoding="utf-8")
        assert "workflow_dispatch" in publish
        production = job_blocks(publish)["production"]
        assert re.search(r"^\s+if:\s*github\.event_name == 'release'\s*$", production, re.M)

    def test_version_and_changelog_are_checked_before_anything_is_built(self):
        build = job_blocks(BASH_PUBLISH.read_text(encoding="utf-8"))["build"]
        assert "CONCLUDE_VERSION" in build
        assert "CHANGELOG.md" in build


def sdist_guard_pattern():
    """The ERE the `Check what the sdist contains` step greps for, as written in ci.yml."""
    text = CI.read_text(encoding="utf-8")
    step = text[text.index("Check what the sdist contains") :]
    match = re.search(r"sed -E '[^']*' \| grep -E '([^']+)'", step)
    assert match, "the sdist step must strip the top-level directory and grep for plumbing"
    return re.compile(match.group(1))


def flagged(pattern, entry):
    return bool(pattern.search(re.sub(r"^[^/]+/", "", entry)))  # what `sed -E 's#^[^/]+/##'` does


@pytest.mark.parametrize(
    "entry",
    [
        "conclude-1.0.1/uv.lock",
        "conclude-1.0.1/.venv/bin/python",
        "conclude-1.0.1/.venv-plain/bin/python",
        "conclude-1.0.1/src/conclude/__pycache__/app.cpython-312.pyc",
        "conclude-1.0.1/test/__pycache__/x.pyc",
    ],
)
def test_the_sdist_guard_flags_repository_plumbing(entry):
    assert flagged(sdist_guard_pattern(), entry), entry


@pytest.mark.parametrize(
    "entry",
    [
        "conclude-1.0.1/docs/guide.md",  # sourced from docs/python/guide.md, flattened by the build hook
        "conclude-1.0.1/spec/naming.json",
        "conclude-1.0.1/src/conclude/py.typed",
        "conclude-1.0.1/test/test_docs.py",
        "conclude-1.0.1/hatch_build.py",
        "conclude-1.0.1/CHANGELOG.md",
        "conclude-1.0.1/PKG-INFO",
        "conclude-1.0.1/pyproject.toml",
    ],
)
def test_the_sdist_guard_leaves_shipped_files_alone(entry):
    assert not flagged(sdist_guard_pattern(), entry), entry
