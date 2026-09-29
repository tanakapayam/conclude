#!/usr/bin/env bash
# Packaging safeguards for the one file users actually download.
#
#   scripts/smoke.sh [PATH_TO_CONCLUDE_SH] [EXPECTED_VERSION]
#
# PATH defaults to ../src/conclude.sh (this script's sibling directory);
# the publish workflow runs it against the exact file it is about to
# attach to a release. EXPECTED_VERSION, if given, must equal the file's
# CONCLUDE_VERSION (the release workflow passes the tag's version).
#
# What "a library that is sourced into someone else's script" must not do:
#   - print anything, or change the caller's shell options
#   - leave stray variables or functions outside its own namespace
#   - need anything but Bash, coreutils, awk and (for the guard) git
# and it must actually work when nothing but the file itself is present.
# This script checks those, in a clean process, with the file copied
# somewhere it has no neighbours (so it can't lean on the repository).

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
file=${1:-"$here/../src/conclude.sh"}
expected_version=${2-}

fail() {
  printf 'smoke: FAIL: %s\n' "$*" >&2
  exit 1
}
pass() { printf 'smoke: ok: %s\n' "$*"; }

[[ -f $file ]] || fail "no such file: $file"

# 1. Syntax, and no dependency on the tools the library is not allowed to
#    call (comments may mention them; code may not).
bash -n "$file" || fail "syntax error"
pass "syntax"

if grep -vE '^[[:space:]]*#' "$file" | grep -nE '(^|[^[:alnum:]_.-])(python3?|node|npm|jq|yq)([^[:alnum:]_-]|$)'; then
  fail "the library calls a tool it must not depend on (see above)"
fi
pass "no python/node/jq/yq in code"

# 2. Copy it somewhere alone and load it in a clean, non-interactive Bash.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$file" "$work/conclude.sh"

probe=$work/probe.sh
cat >"$probe" <<'PROBE'
_probe_out=
set +o | sort >"$1/options.before"
shopt -p | sort >>"$1/options.before"
compgen -v | sort >"$1/vars.before"
compgen -A function | sort >"$1/funcs.before"

_probe_out=$(source "$1/conclude.sh" 2>&1) || { echo "sourcing failed: $_probe_out"; exit 1; }
[[ -z $_probe_out ]] || { echo "sourcing printed output: $_probe_out"; exit 1; }
source "$1/conclude.sh"

set +o | sort >"$1/options.after"
shopt -p | sort >>"$1/options.after"
compgen -v | sort >"$1/vars.after"
compgen -A function | sort >"$1/funcs.after"

printf '%s\n' "$CONCLUDE_VERSION" >"$1/version"
PROBE

env -i PATH="$PATH" HOME="$work" bash --noprofile --norc "$probe" "$work" ||
  fail "could not source the file in a clean shell"
pass "sources cleanly, silently"

diff -u "$work/options.before" "$work/options.after" >&2 ||
  fail "sourcing changed the caller's shell options (diff above)"
pass "leaves shell options alone"

stray_vars=$(comm -13 "$work/vars.before" "$work/vars.after" |
  grep -vE '^(CONCLUDE|CONCLUDE_VERSION|_CONCLUDE_[A-Z_]+)$' || true)
[[ -z $stray_vars ]] || fail "stray variables outside the CONCLUDE*/_CONCLUDE_ namespace: $stray_vars"
stray_funcs=$(comm -13 "$work/funcs.before" "$work/funcs.after" |
  grep -vE '^_?conclude_' || true)
[[ -z $stray_funcs ]] || fail "stray functions outside the conclude_/_conclude_ namespace: $stray_funcs"
pass "stays inside its namespace"

# 3. The version the file reports.
version=$(<"$work/version")
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$ ]] ||
  fail "CONCLUDE_VERSION '$version' is not a semantic version"
if [[ -n $expected_version && $version != "$expected_version" ]]; then
  fail "CONCLUDE_VERSION is $version, expected $expected_version"
fi
pass "version $version"

# 4. The documented quickstart, end to end, with nothing else present.
cat >"$work/quickstart.sh" <<'QUICKSTART'
set -euo pipefail
source "$1/conclude.sh"
cd "$1"
export HOME="$1/home"
mkdir -p "$HOME"

conclude_init demo
conclude_define demo host str localhost
conclude_define demo port int 8080
conclude_define demo debug bool false
conclude_define demo tags list "a,b"
conclude_define demo note str

MYAPP_UNRELATED=1 DEMO_PORT=9000 conclude_resolve demo -- --host example.org --debug

[[ ${CONCLUDE[host]} == example.org ]]
[[ ${CONCLUDE[port]} == 9000 ]]
[[ ${CONCLUDE[debug]} == true ]]
[[ ${CONCLUDE[tags]} == $'a\nb' ]]
[[ -z ${CONCLUDE[note]} ]]
[[ $DEMO_HOST == example.org ]]

conclude_format_env demo out
[[ $out == *'DEMO_PORT=8080'* ]]
conclude_format_toml demo out
[[ $out == $'[demo]\nhost = "localhost"'* ]]
QUICKSTART
env -i PATH="$PATH" bash --noprofile --norc "$work/quickstart.sh" "$work" ||
  fail "the quickstart failed"
pass "quickstart"

printf 'smoke: all checks passed for %s\n' "$file"
