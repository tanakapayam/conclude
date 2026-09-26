"""Guards for docs/python/comparison.md: it says when it was verified, its
tables are well-formed, the README points at it, and everything it
claims about conclude itself is backed by the code."""

import dataclasses
import datetime
import re
import tomllib
from pathlib import Path

import pytest

import conclude
from conclude import App

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # python/
# In a git checkout, docs/ is a sibling of python/, one level up, and this
# package's own docs live under docs/python/. In a built sdist -- or an
# install from one -- everything was flattened in alongside this package
# instead (see hatch_build.py): one level less deep, and with no separate
# "python" segment (its docs/python/*.md become the sdist's docs/*.md).
IN_CHECKOUT = (PACKAGE_ROOT.parent / "spec").is_dir()
REPO_ROOT = PACKAGE_ROOT.parent if IN_CHECKOUT else PACKAGE_ROOT
DOCS_DIR = REPO_ROOT / "docs" / "python" if IN_CHECKOUT else REPO_ROOT / "docs"
COMPARISON = DOCS_DIR / "comparison.md"
GUIDE = DOCS_DIR / "guide.md"
README = PACKAGE_ROOT / "README.md"
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"
BASE_URL = "https://github.com/tanakapayam/conclude/blob/main/"

COMPARED = ["ConfigArgParse", "jsonargparse", "pydantic-settings", "Dynaconf", "python-decouple"]

pytestmark = pytest.mark.skipif(
    not (COMPARISON.exists() and README.exists()),
    reason="documentation files are not part of this checkout",
)


def read(path):
    return path.read_text(encoding="utf-8")


def tables(text):
    """``[[row, ...], ...]`` (each row a list of stripped cells) for every markdown table."""
    found, current = [], []
    for line in text.splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):  # skip the divider row
                current.append(cells)
        elif current:
            found.append(current)
            current = []
    if current:
        found.append(current)
    return found


def slug(title):
    return re.sub(r"[^\w\- ]", "", title.lower().strip()).replace(" ", "-")


def capabilities():
    """The capability table as ``{capability: {column: cell}}``."""
    table = next(t for t in tables(read(COMPARISON)) if t[0][0] == "Capability")
    header = table[0]
    return {row[0]: dict(zip(header[1:], row[1:], strict=True)) for row in table[1:]}


def test_says_when_it_was_verified():
    match = re.search(r"\*\*Verified (\d{4}-\d{2}-\d{2})\*\*", read(COMPARISON))
    assert match, "the comparison must carry a **Verified YYYY-MM-DD** date"
    datetime.date.fromisoformat(match.group(1))


def test_states_the_versions_it_checked():
    text = read(COMPARISON)
    assert f"conclude {conclude.__version__}" in text
    for name in COMPARED:
        assert re.search(rf"{re.escape(name)} \d+\.\d+", text), name


def test_every_table_row_has_the_same_number_of_columns():
    for table in tables(read(COMPARISON)):
        assert len({len(row) for row in table}) == 1, table[0]


def test_the_capability_table_has_a_column_for_every_library():
    table = next(t for t in tables(read(COMPARISON)) if t[0][0] == "Capability")
    assert table[0][1:] == ["conclude", *COMPARED]


def test_the_what_you_write_table_has_a_column_for_every_library():
    table = next(t for t in tables(read(COMPARISON)) if t[0][0] == "conclude")
    assert table[0] == ["conclude", *COMPARED]


def test_the_zero_dependency_claim_matches_pyproject():
    project = tomllib.loads(read(PYPROJECT))["project"]
    assert project["dependencies"] == []
    row = capabilities()["Hard runtime dependencies (PyPI metadata)"]
    assert row["conclude"] == "0"


def test_the_readme_links_to_the_comparison():
    assert f"{BASE_URL}docs/python/comparison.md" in read(README)


def test_the_readme_table_names_every_compared_library():
    text = read(README)
    section = text[text.index("## Where it fits") : text.index("## Design principles")]
    for name in [*COMPARED, "argparse", "python-dotenv", "Hydra"]:
        assert name in section, name


def test_relative_links_resolve():
    text = read(COMPARISON)
    guide_anchors = {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", read(GUIDE), re.M)}
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://")):
            continue
        file, _, anchor = target.partition("#")
        assert (COMPARISON.parent / file).exists(), target
        if anchor:
            assert anchor in guide_anchors, target


# --- what the table claims about conclude is backed by the code -----------------------


def test_the_claims_about_conclude_are_backed_by_the_api():
    rows = capabilities()
    yes = {name: row["conclude"] for name, row in rows.items()}
    fields = {f.name for f in dataclasses.fields(App)}
    assert yes["Environment variables"] == "yes" and hasattr(App, "load_env")
    assert yes["Your program's CLI flags"] == "yes" and hasattr(App, "add_arguments")
    assert yes["TOML files"] == "yes" and hasattr(App, "load_config_files")
    assert yes["`.env` files"] == "yes" and "dotenv_path" in fields
    assert yes["Verifies a private file is gitignored before reading"] == "yes"
    assert "dotenv_require_gitignored" in fields and hasattr(App, "developer_status")
    assert {"format_env", "format_toml", "format_cli"} <= set(dir(App))
    assert {"config_system_path", "config_home_path", "config_cwd_path"} <= fields


def test_what_conclude_does_not_do_is_really_not_there():
    rows = capabilities()
    for capability in [
        "YAML, JSON or INI files",
        "External secret backends",
        "Named environments (development, production, ...)",
    ]:
        assert rows[capability]["conclude"].startswith("--"), capability
    assert not any(name in {"yaml", "json"} for name in dir(conclude))
