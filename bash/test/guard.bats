#!/usr/bin/env bats
# Runs every case in spec/guard.json against conclude_check_guard.
#
# Each case's `files` describes a fresh tree; a key ending in "/" is a
# directory, otherwise a file with the given content. Where a case's
# `.git` is a real directory, this harness actually runs `git init -q`
# there first (a bare, un-initialized ".git/" marker makes real git
# refuse to run at all -- see the design note above conclude_check_guard
# in src/conclude.sh). Where `.git` is a *file* (the worktree/submodule
# case), the fixture's literal "gitdir: /elsewhere" content is replaced
# with a pointer to a real, separately-initialized git directory: the
# case is testing "does a .git *file* still count", not that exact path,
# and real git needs somewhere real to follow.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/guard.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
  WORK="${BATS_TEST_TMPDIR}/work"
  mkdir -p "$WORK"
}

build_case_tree() {
  local dir=$1 idx=$2
  mkdir -p "$dir"
  local has_git_dir has_git_file
  has_git_dir=$(jq -r ".cases[$idx].files | has(\".git/\")" "$SPEC_FILE")
  has_git_file=$(jq -r ".cases[$idx].files | has(\".git\")" "$SPEC_FILE")

  [[ $has_git_dir == true ]] && (cd "$dir" && git init -q)

  local key
  while IFS= read -r key; do
    [[ $key == ".git/" ]] && continue
    if [[ $key == ".git" && $has_git_file == true ]]; then
      local realgit="${dir}.realgit"
      mkdir -p "$realgit" && (cd "$realgit" && git init -q)
      printf 'gitdir: %s/.git\n' "$realgit" >"$dir/.git"
      continue
    fi
    if [[ $key == */ ]]; then
      mkdir -p "$dir/$key"
    else
      mkdir -p "$dir/$(dirname -- "$key")"
      local content
      content=$(jq -r --arg k "$key" ".cases[$idx].files[\$k] + \"\u0001\"" "$SPEC_FILE") || true
      content=${content%$'\x01'}
      printf '%s' "$content" >"$dir/$key"
    fi
  done < <(jq -r ".cases[$idx].files | keys[]" "$SPEC_FILE")
}

@test "guard: every case in spec/guard.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name target kill_switch_var failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    target=$(jq -r ".cases[$i].target" "$SPEC_FILE")
    kill_switch_var=$(jq -r ".cases[$i].kill_switch_var // \"\"" "$SPEC_FILE")

    local dir="${WORK}/case_${i}"
    build_case_tree "$dir" "$i"

    local -a env_keys=()
    local ek
    while IFS= read -r ek; do
      [[ -z $ek ]] && continue
      env_keys+=("$ek")
      export "$ek=$(jq -r --arg k "$ek" ".cases[$i].env[\$k]" "$SPEC_FILE")"
    done < <(jq -r ".cases[$i].env // {} | keys[]" "$SPEC_FILE")

    local active reason
    conclude_check_guard "${dir}/${target}" "$kill_switch_var" active reason

    for ek in "${env_keys[@]-}"; do
      [[ -n $ek ]] && unset "$ek"
    done

    local expected_active expected_reason
    expected_active=$(jq -r ".cases[$i].expect.active" "$SPEC_FILE")
    expected_reason=$(jq -r ".cases[$i].expect.reason // \"\"" "$SPEC_FILE")

    if [[ $active != "$expected_active" ]]; then
      echo "[$name] active: expected $expected_active, got $active (reason: '$reason')"
      failures=$((failures + 1))
    fi
    if [[ $reason != "$expected_reason" ]]; then
      echo "[$name] reason: expected '$expected_reason', got '$reason'"
      failures=$((failures + 1))
    fi
  done

  [ "$failures" -eq 0 ]
}
