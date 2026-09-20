"""Guards against documentation drift: the README's quickstart runs, the
guide's printed examples are what the code really prints, the reference
covers the whole public API, and every link and anchor resolves."""

import dataclasses
import importlib.util
import re
import shlex
import sys
from pathlib import Path

import pytest

import conclude
from conclude import App

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guide.md"
REFERENCE = ROOT / "docs" / "reference.md"
CHANGELOG = ROOT / "CHANGELOG.md"
DOCS = [README, GUIDE, REFERENCE]
BASE_URL = "https://github.com/tanakapayam/conclude/blob/main/"

pytestmark = pytest.mark.skipif(
    not all(path.exists() for path in [*DOCS, CHANGELOG]),
    reason="documentation files are not part of this checkout",
)


def fenced_blocks(text):
    """``[(language, code)]`` for every fenced code block, in order."""
    blocks, lang, lines = [], None, []
    for line in text.splitlines():
        if line.startswith("```"):
            if lang is None:
                lang, lines = line[3:].strip(), []
            else:
                blocks.append((lang, "\n".join(lines)))
                lang = None
        elif lang is not None:
            lines.append(line)
    return blocks


def slug(title):
    """GitHub's heading anchor for ``title``."""
    return re.sub(r"[^\w\- ]", "", title.lower().strip()).replace(" ", "-")


def anchors(path):
    text = path.read_text(encoding="utf-8")
    without_code = "\n".join(
        line for line in re.sub(r"```.*?```", "", text, flags=re.S).splitlines()
    )
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", without_code, re.M)}


# --- README quickstart --------------------------------------------------------


def test_readme_quickstart_runs_and_prints_what_the_readme_says(tmp_path, monkeypatch, capsys):
    blocks = fenced_blocks(README.read_text(encoding="utf-8"))
    code = next(code for lang, code in blocks if lang == "python")
    shell = next(code for lang, code in blocks if code.startswith("$ "))
    command_line, expected = shell.splitlines()[0][2:], "\n".join(shell.splitlines()[1:])

    tokens = shlex.split(command_line)
    env = {}
    while "=" in tokens[0]:
        key, value = tokens.pop(0).split("=", 1)
        env[key] = value
    program, argv = tokens[0], tokens[1:]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", [program, *argv])

    exec(compile(code, "README quickstart", "exec"), {"__name__": "__main__"})
    assert capsys.readouterr().out.strip() == expected.strip()


# --- guide examples ---------------------------------------------------------------


def guide_app_and_defaults():
    blocks = fenced_blocks(GUIDE.read_text(encoding="utf-8"))
    code = next(
        c for lang, c in blocks if lang == "python" and '"retries": 3' in c and "DEFAULTS = {" in c
    )
    namespace = {"conclude": conclude}
    exec(compile(code, "guide section 2", "exec"), namespace)
    return namespace["app"], namespace["DEFAULTS"]


def test_guide_format_examples_match_real_output():
    app, _ = guide_app_and_defaults()
    text = GUIDE.read_text(encoding="utf-8")
    section = text[text.index("## 10. Generating docs") : text.index("## 11. Putting it together")]
    pairs = re.findall(r"```python\nprint\(app\.(\w+)\(\)\)\n```\n\n```\n(.*?)\n```", section, re.S)
    assert [name for name, _ in pairs] == ["format_env", "format_toml", "format_cli"]
    for name, expected in pairs:
        assert getattr(app, name)() == expected, name


def test_guide_describe_sources_sample_matches_real_output():
    _, defaults = guide_app_and_defaults()
    text = GUIDE.read_text(encoding="utf-8")
    sample = next(
        code
        for lang, code in fenced_blocks(text)
        if "config sources:" in code and "system config" in code
    )
    expected = sample[sample.index("config sources:") :]
    app = App(
        "remind",
        defaults,
        config_home_path=Path("/Users/payam/.config/remind/config.toml"),
        config_cwd_path=None,
    )
    assert app.describe_sources(environ={}) == expected


def test_guide_names_all_four_developer_states():
    text = GUIDE.read_text(encoding="utf-8")
    for state in conclude.DeveloperState:
        assert state.value in text


def test_precedence_chain_is_stated_consistently():
    chain = "defaults < system < user < project < env < developer < CLI"
    assert chain in README.read_text(encoding="utf-8")
    assert chain in GUIDE.read_text(encoding="utf-8")
    assert chain in REFERENCE.read_text(encoding="utf-8")


# --- the reference covers the whole public API ------------------------------------


def mentioned(name, text):
    """Whether ``name`` appears, as a whole word, inside an inline code span."""
    spans = re.findall(r"`([^`\n]+)`", text)
    pattern = re.compile(rf"(?<![\w.]){re.escape(name)}(?!\w)")
    return any(pattern.search(span) for span in spans)


def test_reference_covers_everything_in_all():
    text = REFERENCE.read_text(encoding="utf-8")
    missing = [name for name in conclude.__all__ if not mentioned(name, text)]
    assert not missing


def test_reference_covers_every_public_app_member():
    text = REFERENCE.read_text(encoding="utf-8")
    members = [field.name for field in dataclasses.fields(App)]
    members += [n for n in vars(App) if not n.startswith("_") and n not in members]
    missing = [name for name in members if not mentioned(name, text)]
    assert not missing


def test_reference_lists_every_module():
    text = REFERENCE.read_text(encoding="utf-8")
    modules = {p.stem for p in (ROOT / "src" / "conclude").glob("*.py")} - {"__init__", "app"}
    missing = sorted(m for m in modules if f"conclude.{m}" not in text)
    assert not missing


def test_docs_only_name_things_that_exist():
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for name in set(re.findall(r"`conclude\.([A-Za-z_]\w*)", text)):
            assert hasattr(conclude, name) or importlib.util.find_spec(f"conclude.{name}"), (
                path.name,
                name,
            )
        for lang, code in fenced_blocks(text):
            if lang == "python":
                for name in set(re.findall(r"\bapp\.(\w+)\(", code)):
                    assert hasattr(App, name), (path.name, name)


# --- links and cross-references ---------------------------------------------------


def links(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    return re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text)


def resolve_link(source, target):
    """``(file, anchor)`` for a link that points into this repository,
    or ``None`` for an external one."""
    target, _, anchor = target.partition("#")
    if target.startswith(BASE_URL):
        return ROOT / target[len(BASE_URL) :], anchor
    if target.startswith(("http://", "https://", "mailto:")):
        return None
    return (source.parent / target if target else source), anchor


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_links_resolve(path):
    for target in links(path):
        resolved = resolve_link(path, target)
        if resolved is None:
            continue
        file, anchor = resolved
        assert file.exists(), (path.name, target)
        if anchor and file.suffix == ".md":
            assert anchor in anchors(file), (path.name, target)


def test_readme_links_are_absolute_so_they_work_on_pypi():
    for target in links(README):
        assert target.startswith(("https://", "http://")), target


@pytest.mark.parametrize("path", [GUIDE, REFERENCE], ids=lambda p: p.name)
def test_section_references_are_links(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    unlinked = re.findall(r"(?<!\[)\bsections?\s+\d+", text)
    assert not unlinked


# --- release hygiene -------------------------------------------------------------


def test_changelog_has_an_entry_for_the_current_version():
    assert f"## [{conclude.__version__}]" in CHANGELOG.read_text(encoding="utf-8")


def test_guide_documents_the_strict_dotenv_option_and_its_row_states():
    text = GUIDE.read_text(encoding="utf-8")
    assert "dotenv_require_gitignored=True" in text
    for phrase in ["active (gitignored)", "inactive (", "app.dotenv_status()"]:
        assert phrase in text


def test_guide_documents_the_dotenv_developer_file():
    text = " ".join(GUIDE.read_text(encoding="utf-8").split())  # prose wraps across lines
    assert 'config = ".env.local"' in text
    for phrase in ["only `.toml` is TOML", "docker compose", "no tables", "format_env()"]:
        assert phrase in text
