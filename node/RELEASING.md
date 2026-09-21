# Releasing @tanakapayam/conclude

Releases go through two stages with a person in between (`.github/workflows/node-publish.yml`):

```
release published (tag node-v<version>)
   |
   v
 ci ---> build ---> stage ---------------> production
          |          |                       |
          |          | GitHub Packages       | waits for a reviewer to approve the `npm` environment,
          |          | (staging): publish    | checks it is the staged tarball, publishes it to npmjs.com
          |          | the tarball, install  | with provenance, installs it back from npm
          |          | it back, check it     |
          |
          +-- one tarball, built once, uploaded as an artifact and promoted unchanged
```

Why staging: a version published to npmjs.com can never be replaced, and 0.1.0 shipped without its build
output. Staging catches that first, on a registry where a mistake costs nothing. Why one tarball: what was
staged and checked is byte-for-byte what is published (production compares integrities before it publishes).

## One-time setup

1. **Environments** (repository Settings, Environments):
   - `npm-staging`: no protection needed.
   - `npm`: add yourself (or a team) under *Required reviewers*; that is the approval gate. Restrict
     *Deployment branches and tags* to the tag pattern `node-v*`.
2. **npmjs.com trusted publisher** for `@tanakapayam/conclude`: this repository, workflow
   `node-publish.yml`, environment `npm`. (Nothing about the staging environment or GitHub Packages
   needs configuring: the first staged publish creates the package under this repository.)
3. Nothing to store: staging uses the workflow's own token, production uses OIDC. No npm token exists.

## Releasing

1. Bump `version` in `node/package.json` and `node/package-lock.json` (`npm version <v> --no-git-tag-version`),
   and put a dated entry in `node/CHANGELOG.md` (the release is refused while it says *Unreleased*).
2. Merge to `main`.
3. Create a GitHub Release from a new tag `node-v<version>` on `main`.
4. The workflow builds and stages. Look at the run summary (and the package under the repository's
   *Packages*), then **approve the `npm` deployment** when you are happy.
5. Production publishes the staged tarball and installs it back from npm; a red job at that point means
   the published package is not what was staged: publish a fixed version and
   `npm deprecate @tanakapayam/conclude@<bad-version> "<why>"`.

## Rehearsing

- **Actions, Node Publish, Run workflow**: `dry-run` builds and packs; `staging` also stages on GitHub
  Packages under a throwaway `<version>-staging.<run>.<attempt>` version. Production never runs from a
  manual run.
- **Locally, no network account needed**: start a throwaway registry and rehearse against it. CI does
  exactly this on every change (`staging rehearsal` in `node-ci.yml`).

  ```
  cd node
  npx verdaccio@6.10.4 --config scripts/verdaccio.yaml --listen 127.0.0.1:4873 &
  REHEARSAL_REGISTRY=http://127.0.0.1:4873 npm run rehearse
  ```

## Trying a staged version

GitHub Packages needs a token even to install a public package:

```
@tanakapayam:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=<a token with read:packages>
```

then `npm install @tanakapayam/conclude@<version>`. Staged versions on GitHub Packages are independent
of npmjs.com, so a rehearsal or a rejected release never uses up a real version there.
