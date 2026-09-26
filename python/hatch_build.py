"""A hatchling build hook: pulls the language-neutral spec/ and docs/concept.md,
and this package's own docs/python/, into the sdist.

All three live outside this directory, at the repository root, since this
repository holds an implementation of conclude per language (this package,
plus node/ and any that come after it) with the shared spec and per-language
docs kept alongside them rather than duplicated into each one. hatchling's
project root is always wherever pyproject.toml is -- here, python/ -- so
those paths are otherwise outside its reach; force_include is hatchling's
supported way to pull in files, or whole directories, from outside the
project root. sdist only: the wheel needs none of this at runtime.

docs/python/*.md is flattened to the sdist's own docs/*.md (alongside the
force-included docs/concept.md), so the sdist's docs/ ends up looking like a
trimmed copy of the repository's docs/ with only the node/ subdirectory
missing -- see test/test_docs.py and test/test_comparison.py, which handle
running from either layout.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class SiblingDocsHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "sdist":
            return
        repo_root = Path(self.root).parent
        force_include = build_data.setdefault("force_include", {})
        force_include[str(repo_root / "spec")] = "spec"
        force_include[str(repo_root / "docs" / "concept.md")] = "docs/concept.md"
        force_include[str(repo_root / "docs" / "python")] = "docs"
