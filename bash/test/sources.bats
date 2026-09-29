#!/usr/bin/env bats
# Runs every case in spec/sources.json against conclude_describe_sources.
# {root} in options/expect stands for a fresh working directory built per
# case, same file-tree convention as guard.bats (and the same real-git
# bootstrapping, for the same reason: see the note above
# conclude_check_guard in src/conclude.sh).

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/sources.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

build_case_tree() {
  local dir=$1 idx=$2
  mkdir -p "$dir"
  local has_git_dir
  has_git_dir=$(jq -r ".cases[$idx].files | has(\".git/\")" "$SPEC_FILE")
  [[ $has_git_dir == true ]] && (cd "$dir" && git init -q)

  local key
  while IFS= read -r key; do
    [[ $key == ".git/" ]] && continue
    if [[ $key == */ ]]; then
      mkdir -p "$dir/$key"
    else
      mkdir -p "$dir/$(dirname -- "$key")"
      local content
      content=$(jq -r --arg k "$key" ".cases[$idx].files[\$k] + \"\u0001\"" "$SPEC_FILE") || true
      content=${content%$'\x01'}
      printf '%s' "$content" >"$dir/$key"
    fi
  done < <(jq -r ".cases[$idx].files // {} | keys[]" "$SPEC_FILE")
}

@test "sources: every case in spec/sources.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name app failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    app=$(jq -r ".cases[$i].app" "$SPEC_FILE")

    local root="${BATS_TEST_TMPDIR}/case_${i}"
    build_case_tree "$root" "$i"

    # {root} substitution, applied to every options.* path string.
    sub_root() { printf '%s' "${1//\{root\}/$root}"; }

    local -a args=()
    local val
    val=$(jq -r '.cases['"$i"'].options.system' "$SPEC_FILE")
    [[ $val != null ]] && args+=(--system "$(sub_root "$val")")
    val=$(jq -r '.cases['"$i"'].options.user' "$SPEC_FILE")
    [[ $val != null ]] && args+=(--user "$(sub_root "$val")")
    val=$(jq -r '.cases['"$i"'].options.project' "$SPEC_FILE")
    [[ $val != null ]] && args+=(--project "$(sub_root "$val")")
    val=$(jq -r '.cases['"$i"'].options.aux' "$SPEC_FILE")
    [[ $val != null ]] && args+=(--aux "$val")

    val=$(jq -r '.cases['"$i"'].options.dotenv.path' "$SPEC_FILE")
    [[ $val != null ]] && args+=(--dotenv "$(sub_root "$val")")
    val=$(jq -r '.cases['"$i"'].options.dotenv.require_gitignored' "$SPEC_FILE")
    [[ $val == true ]] && args+=(--dotenv-require-gitignored)

    local dev_type
    dev_type=$(jq -r '.cases['"$i"'].options.developer | type' "$SPEC_FILE")
    if [[ $dev_type == object ]]; then
      val=$(jq -r '.cases['"$i"'].options.developer.file' "$SPEC_FILE")
      args+=(--developer-file "${root}/${val}")
    fi

    local -a env_keys=()
    local ek
    while IFS= read -r ek; do
      [[ -z $ek ]] && continue
      env_keys+=("$ek")
      export "$ek=$(jq -r --arg k "$ek" '.cases['"$i"'].env[$k]' "$SPEC_FILE")"
    done < <(jq -r ".cases[$i].env // {} | keys[]" "$SPEC_FILE")

    local out
    conclude_describe_sources "$app" out "${args[@]}"

    for ek in "${env_keys[@]-}"; do
      [[ -n $ek ]] && unset "$ek"
    done

    local expected
    expected=$(jq -r ".cases[$i].expect" "$SPEC_FILE")
    expected=$(sub_root "$expected")

    if [[ $out != "$expected" ]]; then
      echo "[$name]"
      echo "expected: $(printf '%q' "$expected")"
      echo "got:      $(printf '%q' "$out")"
      failures=$((failures + 1))
    fi
  done

  [ "$failures" -eq 0 ]
}
