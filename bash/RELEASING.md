# Releasing conclude.sh

A release attaches one file, `conclude.sh`, and its checksum, `conclude.sh.sha256`,
to a GitHub Release. Two stages with a person in between
(`.github/workflows/bash-publish.yml`):

```
release published (tag bash-v<version>)
   |
   v
 ci ---> build ----------------------> production
           |                              |
           | guard the release, run       | waits for a reviewer to approve the
           | scripts/smoke.sh on the      | `bash-release` environment, checks the
           | exact file, upload it        | file is the one that was built, attaches
           | and its sha256               | both files, downloads them back from the
           |                              | public URL and checks the checksum
```

An asset is never replaced: attaching a file name that already exists on the
release fails. What users pinned a version to cannot change under them. If a
release is wrong, publish a new version.

## One-time setup

1. **Environment** (repository Settings, Environments): create `bash-release`,
   add yourself (or a team) under *Required reviewers* (that is the approval
   gate), and restrict *Deployment branches and tags* to the tag pattern
   `bash-v*`.
2. **Recommended:** pin the Bash 5.3 source. CI and the release build Bash 5.3
   from the GNU tarball, because the runner images ship 5.2. The build prints the
   tarball's sha256; set it as a repository *variable* named
   `BASH_TARBALL_SHA256` (Settings, Secrets and variables, Actions, Variables)
   and the build refuses any other tarball. Until you do, it trusts whatever the
   GNU mirror serves.
3. Nothing to store: the workflow uses its own token to attach assets.

## Releasing

1. Bump `CONCLUDE_VERSION` in `bash/src/conclude.sh`, and put a dated entry in
   `bash/CHANGELOG.md` (the release is refused while it says *Unreleased*, and
   CI fails if the version has no entry at all).
2. Merge to `main`.
3. Create a GitHub Release from a new tag `bash-v<version>` on `main`.
4. The workflow checks and builds. Look at the run summary, then **approve the
   `bash-release` deployment** when you are happy.
5. Production attaches the files and downloads them back. A red job at that point
   means what users would get is not what was built.

The tag, `CONCLUDE_VERSION` and the CHANGELOG entry must all agree; the workflow
checks each.

## Rehearsing

- **Actions, Bash Publish, Run workflow** builds and checks everything and
  attaches nothing. Production never runs from a manual run.
- **Locally:**

  ```sh
  cd bash
  shellcheck src/conclude.sh scripts/*.sh
  shellcheck --shell=bats test/*.bats
  scripts/smoke.sh                      # packaging safeguards on the one file
  bats test/                            # needs bats-core and jq
  ```

  `scripts/install-bash.sh 5.3 ~/bash-5.3` builds a Bash 5.3 into a prefix if
  your machine does not have one; put its `bin` first on `PATH` to run the
  above with it.

## What `scripts/smoke.sh` guards

The file is a library that gets sourced into someone else's script, so the smoke
test checks, in a clean process with the file copied somewhere it has no
neighbours, that it: parses; contains no call to `python`, `node`, `npm`, `jq`
or `yq`; sources silently; leaves the caller's shell options exactly as it found
them; defines nothing outside the `conclude_`/`_conclude_` functions and
`CONCLUDE`/`CONCLUDE_VERSION`/`_CONCLUDE_` variables; reports a semantic
`CONCLUDE_VERSION` (equal to the tag's, in the release); and runs the README's
quickstart end to end.

## Installing a release

```sh
version=0.1.0
base=https://github.com/tanakapayam/conclude/releases/download/bash-v$version
curl -fsSLO "$base/conclude.sh" && curl -fsSLO "$base/conclude.sh.sha256"
sha256sum -c conclude.sh.sha256
```

Use the versioned URL. `releases/latest` is the newest release of the whole
repository, which is whichever language was released last.
