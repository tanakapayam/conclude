#!/usr/bin/env bats
# spec/gitignore.json's own "ignored" verdicts were produced by
# `git check-ignore --no-index`, and conclude_check_guard's ignore step
# is that same command -- so this test builds the one real working tree
# the fixture describes and checks every listed path against it, mostly
# as a sanity check that our invocation (flags, cwd, path handling)
# matches the fixture's own methodology exactly.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/gitignore.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "gitignore: spec/gitignore.json against real git" {
  local case_count
  case_count=$(jq '.cases | length' "$SPEC_FILE")

  local ci failures=0
  for ((ci = 0; ci < case_count; ci++)); do
    local dir="${BATS_TEST_TMPDIR}/tree_${ci}"
    mkdir -p "$dir"
    (cd "$dir" && git init -q)

    local key
    while IFS= read -r key; do
      mkdir -p "$dir/$(dirname -- "$key")"
      local content
      content=$(jq -r --arg k "$key" ".cases[$ci].files[\$k] + \"\u0001\"" "$SPEC_FILE") || true
      content=${content%$'\x01'}
      printf '%s' "$content" >"$dir/$key"
    done < <(jq -r ".cases[$ci].files | keys[]" "$SPEC_FILE")

    local path_count
    path_count=$(jq -r ".cases[$ci].paths | length" "$SPEC_FILE")

    local pi path expected_ignored actual_ignored status
    for ((pi = 0; pi < path_count; pi++)); do
      path=$(jq -r ".cases[$ci].paths[$pi].path" "$SPEC_FILE")
      expected_ignored=$(jq -r ".cases[$ci].paths[$pi].ignored" "$SPEC_FILE")
      mkdir -p "$dir/$(dirname -- "$path")"
      [[ -e "$dir/$path" ]] || : >"$dir/$path"

      if git -C "$dir" check-ignore --no-index --quiet -- "$dir/$path" 2>/dev/null; then
        actual_ignored=true
      else
        actual_ignored=false
      fi

      if [[ $actual_ignored != "$expected_ignored" ]]; then
        echo "[$path] expected ignored=$expected_ignored, got $actual_ignored"
        failures=$((failures + 1))
      fi
    done
  done

  [ "$failures" -eq 0 ]
}
