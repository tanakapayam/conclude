# Releasing conclude (Python)

```
release published (tag python-v<version>)
   |
   v
 ci ---> build ---> publish-testpypi   (workflow_dispatch, target testpypi: a dry run)
          |          |
          |          +-> publish-pypi   waits for a reviewer to approve the `pypi`
          |                             environment, then publishes with trusted
          |                             publishing (no stored token)
          |
          +-- one sdist + wheel, built once, uploaded as an artifact and promoted unchanged
```

TestPyPI is the dry run here (there is no separate staging registry, unlike the Node
package's GitHub Packages stage): `workflow_dispatch` with `target: testpypi` builds,
checks, and publishes to TestPyPI, and installs nothing back automatically -- try it
yourself with `pip install -i https://test.pypi.org/simple/ conclude`. A real release
(`target: pypi`, or a published GitHub Release) is checked, gated behind a required
reviewer on the `pypi` environment, then published to PyPI.

## One-time setup

1. **Environments** (repository Settings, Environments):
   - `testpypi`: no protection needed.
   - `pypi`: add yourself (or a team) under *Required reviewers*; that is the approval
     gate.
2. **Trusted publisher**, on both <https://pypi.org> and <https://test.pypi.org>, for the
   project `conclude`: this repository, workflow **`python-publish.yml`**, environment
   `pypi` (`testpypi` on TestPyPI). For a project that does not exist yet, use
   "Publishing" -> "Add a new pending publisher".
3. Nothing to store: publishing uses OIDC. No PyPI token exists.

> **If this workflow was ever registered under a different filename** (for example the
> project's original `publish.yml`, before this repository moved every language into its
> own top-level directory): trusted publishing is matched by *workflow filename*, so the
> existing entries on PyPI and TestPyPI must be updated to `python-publish.yml` -- edit
> them under "Publishing" on each site -- or the next release fails with a permission
> error, not a helpful one.

## Releasing

1. Bump `__version__` in `src/conclude/__init__.py` (the single source of truth; see
   `[tool.hatch.version]` in `pyproject.toml`), and the version in
   `docs/python/comparison.md`'s "Verified" line if it's stale. Put a dated entry in
   `CHANGELOG.md` (the release is refused while it says *Unreleased*).
2. Merge to `main`.
3. Create a GitHub Release from a new tag `python-v<version>` on `main`.
4. `publish-pypi` waits for a reviewer to **approve the `pypi` deployment**; approve it
   when you are happy.

## Rehearsing

Actions, Publish, Run workflow, target `testpypi` -- builds, checks, and publishes to
TestPyPI without touching the `pypi` environment or a real version on PyPI.
