"""Runs the language-neutral conformance fixtures in ``spec/`` against the
Python implementation.

The fixtures (``spec/*.json``) describe conclude's behavior as plain data --
inputs and expected outputs -- so any implementation (the Python package
here, a TypeScript one, ...) can run the same cases. ``docs/concept.md``
explains the concept they pin down; ``spec/README.md`` documents the format.

Each ``test_*`` below is a small adapter from a fixture file to the Python
API. The last section keeps the fixtures, the concept document and the
implementation from drifting apart.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import conclude
from conclude import (
    ConfigFileError,
    DeveloperState,
    DotenvState,
    effective_defaults,
    infer_caster,
    infer_casters,
    opt,
)
from conclude.env import load_dotenv
from conclude.files import load_config_files, parse_config_table, resolve_config_table
from conclude.merge import resolve as merge_resolve
from conclude.naming import cli_flag_name, config_key_name, env_var_name

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # python/
# In a git checkout, spec/ and docs/ are siblings of python/, one level up.
# In a built sdist -- or an install from one -- they were flattened in
# alongside this package instead (see hatch_build.py), one level less deep.
IN_CHECKOUT = (PACKAGE_ROOT.parent / "spec").is_dir()
REPO_ROOT = PACKAGE_ROOT.parent if IN_CHECKOUT else PACKAGE_ROOT
SPEC = REPO_ROOT / "spec"
CONCEPT = REPO_ROOT / "docs" / "concept.md"
SPEC_VERSION = 1

pytestmark = pytest.mark.skipif(
    not SPEC.is_dir(), reason="the spec/ fixtures are not part of this checkout"
)

PYTYPES = {"bool": bool, "int": int, "float": float, "str": str, "list": list}


def load(name):
    document = json.loads((SPEC / name).read_text(encoding="utf-8"))
    assert document["spec_version"] == SPEC_VERSION, name
    return document


def cases(name):
    return load(name)["cases"]


def ids(name):
    return [case["name"] for case in cases(name)]


def defaults_from(settings):
    """The defaults dict for a list of ``{key, type, default}`` settings."""
    return {
        s["key"]: (s["default"] if s["default"] is not None else opt(PYTYPES[s["type"]]))
        for s in settings
    }


def same(actual, expected):
    """Equality that keeps bool distinct from 0/1 and treats 5 and 5.0 alike."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(same(a, e) for a, e in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(same(actual[k], expected[k]) for k in expected)
        )
    return actual == expected


def build_tree(root, files):
    """Write a ``files`` mapping into ``root`` (a key ending in ``/`` is a directory)."""
    for relative, content in files.items():
        path = root / relative.rstrip("/")
        if relative.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


# --- naming -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("naming.json"), ids=ids("naming.json"))
def test_naming(case):
    assert env_var_name(case["app"], case["key"]) == case["env_var"]
    assert cli_flag_name(case["key"]) == case["cli_flag"]
    assert config_key_name(case["key"]) == case["config_key"]


# --- casters ----------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("casters.json"), ids=ids("casters.json"))
def test_casters(case):
    caster = infer_caster(PYTYPES[case["type"]])
    if case.get("error"):
        with pytest.raises(ValueError):
            caster(case["input"])
    else:
        result = caster(case["input"])
        assert same(result, case["output"]), (result, case["output"])


# --- dotenv -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("dotenv.json"), ids=ids("dotenv.json"))
def test_dotenv(case, tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(case["text"].encode("utf-8"))
    assert load_dotenv(path) == case["expect"]


# --- merge ------------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("merge.json"), ids=ids("merge.json"))
def test_merge(case):
    defaults = defaults_from(case["settings"])
    layers = case["layers"]

    def run():
        return merge_resolve(
            layers.get("cli", {}),
            layers.get("env", {}),
            layers.get("config", {}),
            effective_defaults(defaults),
            infer_casters(defaults, {}),
            developer=layers.get("developer"),
        )

    if case.get("error"):
        with pytest.raises(ValueError):
            run()
    else:
        result = run()
        assert same(result, case["expect"]), (result, case["expect"])


# --- config files -----------------------------------------------------------------------


def write_layer_files(root, files):
    """Write ``files`` (system/user/project/siblings) and return the paths to hand over."""
    paths = {
        "system": root / "system.toml",
        "user": root / "user.toml",
        "project": root / "proj" / ".config.toml",
    }
    (root / "proj").mkdir()
    for layer, path in paths.items():
        if layer in files:
            path.write_text(files[layer], encoding="utf-8")
    for name, text in files.get("siblings", {}).items():
        (root / "proj" / name).write_text(text, encoding="utf-8")
    return paths


@pytest.mark.parametrize("case", cases("config_layers.json"), ids=ids("config_layers.json"))
def test_config_layers(case, tmp_path):
    paths = write_layer_files(tmp_path, case["files"])
    defaults = effective_defaults(defaults_from(case["settings"]))
    kwargs = {"aux_pattern": case["aux_pattern"]} if "aux_pattern" in case else {}

    def run():
        return load_config_files(
            paths["user"],
            paths["project"],
            defaults,
            case["table_path"],
            **kwargs,
            system_path=paths["system"],
        )

    if case.get("error"):
        with pytest.raises(ConfigFileError):
            run()
    else:
        assert same(run(), case["expect"])


@pytest.mark.parametrize("case", cases("config_tables.json"), ids=ids("config_tables.json"))
def test_config_tables(case, tmp_path):
    if case["op"] == "parse":
        if case.get("error"):
            with pytest.raises(ValueError):
                parse_config_table(case["value"], case["default_table"])
        else:
            assert parse_config_table(case["value"], case["default_table"]) == case["expect"]
        return
    paths = write_layer_files(tmp_path, case["files"])
    kwargs = {"aux_pattern": case["aux_pattern"]} if "aux_pattern" in case else {}
    assert (
        resolve_config_table(
            config_value=case["config_value"],
            shorthand_value=case["shorthand"],
            default_table=case["default_table"],
            home_path=paths["user"],
            cwd_path=paths["project"],
            system_path=paths["system"],
            **kwargs,
        )
        == case["expect"]
    )


# --- templates --------------------------------------------------------------------------


@pytest.mark.parametrize("case", cases("templates.json"), ids=ids("templates.json"))
def test_templates(case):
    options = case.get("options", {})
    app = conclude.App(
        case["app"],
        defaults_from(case["settings"]),
        env_vars=options.get("env_vars"),
        config_home_path=None,
        config_cwd_path=None,
    )
    common = {"skip": options.get("skip", ()), "defaults": options.get("defaults")}
    metavars = {
        key: {"metavar": tuple(value) if isinstance(value, list) else value}
        for key, value in options.get("metavars", {}).items()
    }
    toml_options = {k: options[k] for k in ("table", "header") if k in options}
    expect = case["expect"]
    if "env" in expect:
        assert app.format_env(**common) == expect["env"]
    if "toml" in expect:
        assert app.format_toml(**common, **toml_options) == expect["toml"]
    if "cli" in expect:
        assert app.format_cli(**common, overrides=metavars) == expect["cli"]


# --- gitignore and the guard (need the optional pathspec) ----------------------------------


def gitignore_params():
    document = load("gitignore.json")
    return [
        pytest.param(case, entry, id=f"{case['name']}: {entry['path']}")
        for case in document["cases"]
        for entry in case["paths"]
    ]


@pytest.fixture
def pathspec():
    return pytest.importorskip("pathspec")


@pytest.mark.parametrize(("case", "entry"), gitignore_params())
def test_gitignore(case, entry, tmp_path, pathspec):
    from conclude.guard import matches_git_ignore_rules

    build_tree(tmp_path, {".git/": None, **case["files"]})
    target = tmp_path / entry["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    assert matches_git_ignore_rules(tmp_path, target) == entry["ignored"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs the git binary")
def test_the_gitignore_verdicts_are_what_git_says(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    for case in cases("gitignore.json"):
        build_tree(repo, case["files"])
        for entry in case["paths"]:
            target = repo / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
            verdict = subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", entry["path"]], cwd=repo, env=env
            ).returncode
            assert (verdict == 0) == entry["ignored"], entry["path"]


@pytest.mark.parametrize("case", cases("guard.json"), ids=ids("guard.json"))
def test_guard(case, tmp_path, pathspec):
    from conclude.guard import check_guard

    build_tree(tmp_path, case["files"])
    result = check_guard(
        tmp_path / case["target"],
        kill_switch_var=case.get("kill_switch_var"),
        environ=case.get("env", {}),
    )
    assert (result.active, result.reason) == (case["expect"]["active"], case["expect"]["reason"])


@pytest.mark.parametrize("case", cases("invocation.json"), ids=ids("invocation.json"))
def test_invocation(case):
    app = conclude.App(
        "myapp", defaults_from(case["settings"]), config_home_path=None, config_cwd_path=None
    )
    options = case.get("options", {})
    kwargs = {
        key: options[key]
        for key in ("prog", "always_include", "skip", "compare_defaults")
        if key in options
    }
    assert app.format_invocation(case["resolved"], **kwargs) == case["expect"]


@pytest.mark.parametrize("case", cases("sources.json"), ids=ids("sources.json"))
def test_sources(case, tmp_path, pathspec):
    root = str(tmp_path)

    def path(value):
        return Path(value.replace("{root}", root)) if value else None

    options = case["options"]
    build_tree(tmp_path, case.get("files", {}))
    manifest = None
    if options["developer"] is not None:
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text(
            f'[tool.conclude.developer]\nconfig = "{options["developer"]["file"]}"\n',
            encoding="utf-8",
        )
    app = conclude.App(
        case["app"],
        {"a": "x"},
        config_system_path=path(options["system"]),
        config_home_path=path(options["user"]),
        config_cwd_path=path(options["project"]),
        config_cwd_aux_pattern=options["aux"],
        dotenv_path=path(options["dotenv"]["path"]),
        dotenv_require_gitignored=options["dotenv"]["require_gitignored"],
        pyproject_path=manifest,
    )
    assert app.describe_sources(environ=case.get("env", {})) == case["expect"].replace(
        "{root}", root
    )


# --- the fixtures, the concept document and the implementation stay in step -------------------

FIXTURES = [
    "naming.json",
    "casters.json",
    "dotenv.json",
    "merge.json",
    "config_layers.json",
    "config_tables.json",
    "templates.json",
    "gitignore.json",
    "guard.json",
    "invocation.json",
    "sources.json",
]


def test_every_fixture_file_is_run_by_this_module():
    assert sorted(p.name for p in SPEC.glob("*.json")) == sorted(FIXTURES)


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_files_are_well_formed(name):
    document = load(name)
    assert isinstance(document["description"], str) and document["description"]
    names = [case["name"] for case in document["cases"]]
    assert names and len(names) == len(set(names)), f"{name}: case names must be unique"


def test_the_spec_readme_names_every_fixture():
    text = (SPEC / "README.md").read_text(encoding="utf-8")
    for name in FIXTURES:
        assert name in text, name


@pytest.mark.skipif(not CONCEPT.exists(), reason="docs/concept.md is not part of this checkout")
class TestConceptDocument:
    text = CONCEPT.read_text(encoding="utf-8") if CONCEPT.exists() else ""

    def test_it_names_every_fixture(self):
        for name in FIXTURES:
            assert name in self.text, name

    def test_it_states_the_precedence_chain(self):
        assert "defaults < system < user < project < env < developer < CLI" in self.text

    def test_it_states_the_spec_version(self):
        assert f"spec version {SPEC_VERSION}" in self.text.lower()

    def test_it_uses_the_same_status_vocabulary_as_the_implementation(self):
        for state in DeveloperState:
            assert state.value in self.text, state
        for state in DotenvState:
            assert f"`{state.value}`" in self.text, state

    def test_it_quotes_every_guard_reason_the_spec_relies_on(self):
        reasons = {
            case["expect"]["reason"]
            for case in cases("guard.json")
            if case["expect"]["reason"] and not case["expect"]["reason"].startswith("disabled by")
        }
        assert reasons
        for reason in reasons:
            assert reason in self.text, reason
        assert "disabled by" in self.text

    def test_it_lists_the_type_tokens_the_fixtures_use(self):
        for token in PYTYPES:
            assert f"`{token}`" in self.text, token

    @pytest.mark.skipif(
        not IN_CHECKOUT,
        reason="link targets assume the git checkout's layout (docs/python/...), not the sdist's flattened one",
    )
    def test_its_relative_links_resolve(self):
        def slug(title):
            return re.sub(r"[^\w\- ]", "", title.lower().strip()).replace(" ", "-")

        for target in re.findall(
            r"\]\(([^)\s]+)\)", re.sub(r"```.*?```", "", self.text, flags=re.S)
        ):
            if target.startswith(("http://", "https://")):
                continue
            file, _, anchor = target.partition("#")
            resolved = (CONCEPT.parent / file) if file else CONCEPT
            assert resolved.exists(), target
            if anchor and resolved.suffix == ".md":
                headings = re.findall(
                    r"^#{1,6} (.+)$",
                    re.sub(r"```.*?```", "", resolved.read_text(encoding="utf-8"), flags=re.S),
                    re.M,
                )
                assert anchor in {slug(h) for h in headings}, target

    def test_it_lists_the_quick_reference_of_bare_env_characters(self):
        assert "[\\w./:@%+,-]" in self.text or "letters, digits" in self.text.lower()


def test_the_python_package_declares_the_spec_version_it_implements():
    # Bumping the spec's version is a deliberate act, in the fixtures and the docs together.
    versions = {load(name)["spec_version"] for name in FIXTURES}
    assert versions == {SPEC_VERSION}
