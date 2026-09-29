#!/usr/bin/env bash
# Build GNU Bash from source, for CI: the runner images ship Bash 5.2, and
# conclude.sh needs 5.3.
#
#   scripts/install-bash.sh [VERSION] [PREFIX]      (defaults: 5.3, ~/bash-VERSION)
#
# BASH_TARBALL_URL overrides where the tarball comes from (a mirror, or a
# local copy for testing this script); it must unpack to bash-VERSION/.
#
# Prints the tarball's sha256 so it can be pinned: set BASH_TARBALL_SHA256
# (in the workflow's env) to that value and the build refuses any other
# tarball. Until it is set the build still works, but trusts whatever the
# GNU mirror serves. On a GitHub runner the new bash is put first on PATH
# for the rest of the job.
set -euo pipefail

version=${1:-5.3}
prefix=${2:-$HOME/bash-$version}
url=${BASH_TARBALL_URL:-https://ftpmirror.gnu.org/gnu/bash/bash-$version.tar.gz}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl -fsSL --retry 5 --retry-delay 3 -o "$work/bash.tar" "$url"
actual=$(sha256sum "$work/bash.tar" | cut -d' ' -f1)
echo "bash-$version tarball sha256: $actual"
if [[ -n ${BASH_TARBALL_SHA256-} && $actual != "$BASH_TARBALL_SHA256" ]]; then
  echo "::error::the bash-$version tarball is $actual, expected $BASH_TARBALL_SHA256" >&2
  exit 1
fi

tar -xf "$work/bash.tar" -C "$work"
(
  cd "$work/bash-$version"
  # GCC 14+ (and Clang 16+) made C23 the default C standard, which
  # redefined an empty "f()" declaration to mean "takes no arguments"
  # instead of C17's "unspecified arguments" -- breaking old K&R-style
  # declarations like the ones in bash's own build-time helper,
  # mkbuiltins.c ("too many arguments to function 'xmalloc'"). This hits
  # bash 5.2 and older; -std=gnu17 restores the old meaning and is a
  # no-op on a compiler whose default was already gnu17. An existing
  # CFLAGS is respected if the caller set one.
  ./configure --prefix="$prefix" CFLAGS="${CFLAGS:--std=gnu17}" >/dev/null
  make -j"$(nproc)" >/dev/null
  make install >/dev/null
)

# shellcheck disable=SC2016 # $BASH_VERSION is meant to expand in the *new* bash
installed=$("$prefix/bin/bash" -c 'echo "$BASH_VERSION"')
[[ $installed == "$version"* ]] || {
  echo "::error::built bash reports $installed, wanted $version" >&2
  exit 1
}
echo "installed bash $installed in $prefix"
[[ -z ${GITHUB_PATH-} ]] || echo "$prefix/bin" >>"$GITHUB_PATH"
