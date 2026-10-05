# Releasing conclude (Python)

Releases build once, check those exact files, and only then upload them, with a person in
between (`.github/workflows/python-publish.yml`):

```
release published (tag python-v<version>)
   |
   v
 ci ---> build ---> stage (3.11 - 3.14) ---> publish-pypi
          |          |                          |
          |          | the files are still      | waits for a reviewer to approve the `pypi`
          |          | the ones built, hold     | environment, re-checks the fingerprint, uploads
          |          | every module, and        | with trusted publishing (no stored token), then
          |          | install and run in       | installs the release back from PyPI and compares
          |          | clean environments       | hashes and provenance
          |
          +-- one sdist + wheel, built once, uploaded as an artifact and promoted unchanged
```

Why: a version on PyPI can never be replaced, and a wheel that leaves out a new module
imports fine from a checkout and breaks for everyone else. The stage catches that first.
Why one set of files: `scripts/release.py integrity` fingerprints them at build time, and
the stage and the upload each recompute it from the artifact they downloaded, so what was
checked is byte-for-byte what is uploaded.

Unlike the Node package there is no staging *registry*: GitHub Packages has no PyPI
registry, and TestPyPI never accepts a file name twice (not even after a delete), so it
cannot stage the real version without burning it. The stage is therefore the checks
themselves, in `scripts/release.py` (standard library only; `python scripts/release.py -h`).

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
4. The workflow builds and stages on every supported Python. When it is green,
   `publish-pypi` waits for a reviewer to **approve the `pypi` deployment**; approve it
   when you are happy.
5. After the upload, the last steps install the release back from PyPI and compare its
   hashes (and provenance) with what was built. If one of them is red, **do not re-run
   it**: the upload is done and cannot be undone. Look at <https://pypi.org/project/conclude/>,
   yank the release there if it is broken (Manage, Options, Yank), and publish a fixed
   version. A red "listing" or "download" step right after an upload is usually the index
   still catching up; the script retries for about five minutes before it gives up.

## Rehearsing

- **Actions, Python Publish, Run workflow**:
  - `dry-run` (the default) builds and stages, and uploads nothing.
  - `testpypi` also uploads to TestPyPI and installs it back, under a throwaway version
    (`1.1.0` becomes `1.1.0.dev<run*100+attempt>`, below the real release and different for
    every run and re-run). It never touches the `pypi` environment or a real version.
  - `pypi` publishes for real from a manual run; prefer publishing a GitHub Release.
- **Locally**, on the files `uv build` leaves in `dist/` (CI does exactly this on every
  change, in the `build` job of `python-ci.yml`):

  ```
  cd python
  uv build
  python scripts/release.py integrity dist
  python scripts/release.py verify-install dist
  ```

  `verify-install` installs the wheel (offline) and the sdist into fresh virtual
  environments, checks that both hold every file under `src/conclude/`, and runs a short
  smoke test of what was installed. To check a release that is already on an index, put
  its two files in a directory and run
  `python scripts/release.py verify-published <dir> --index https://pypi.org --expect-provenance`.

## Trying a rehearsal version

```
pip install -i https://test.pypi.org/simple/ "conclude==<the 1.1.0.devNNNN the run printed>"
```
