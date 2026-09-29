#!/usr/bin/env bats
# Runs every case in spec/invocation.json against
# conclude_format_invocation.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/invocation.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

jq_scalar() {
  jq -r "(${1}) as \$v | if \$v == null then \"__CONCLUDE_NULL__\" elif (\$v|type)==\"array\" then (\$v|join(\",\")) else (\$v|tostring) end" "$SPEC_FILE"
}

@test "invocation: every case in spec/invocation.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name app failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    app="app_${i}" # a fresh app name per case avoids any declaration bleed

    conclude_init "$app"
    local key type default
    while IFS=$'\t' read -r key type; do
      [[ -z $key ]] && continue
      default=$(jq_scalar ".cases[$i].settings[] | select(.key==\"$key\") | .default")
      if [[ $default == __CONCLUDE_NULL__ ]]; then
        conclude_define "$app" "$key" "$type"
      else
        conclude_define "$app" "$key" "$type" "$default"
      fi
    done < <(jq -r ".cases[$i].settings[] | [.key, .type] | @tsv" "$SPEC_FILE")

    local -A resolved=()
    while IFS= read -r key; do
      [[ -z $key ]] && continue
      default=$(jq_scalar ".cases[$i].resolved[\"$key\"]")
      [[ $default == __CONCLUDE_NULL__ ]] && default=""
      resolved[$key]=$default
    done < <(jq -r ".cases[$i].resolved // {} | keys[]" "$SPEC_FILE")

    local -a args=()
    local prog
    prog=$(jq -r ".cases[$i].options.prog // \"\"" "$SPEC_FILE")
    [[ -n $prog ]] && args+=(--prog "$prog")

    local skip_list always_list
    skip_list=$(jq -r ".cases[$i].options.skip // [] | join(\",\")" "$SPEC_FILE")
    [[ -n $skip_list ]] && args+=(--skip "$skip_list")
    always_list=$(jq -r ".cases[$i].options.always_include // [] | join(\",\")" "$SPEC_FILE")
    [[ -n $always_list ]] && args+=(--always-include "$always_list")

    while IFS= read -r key; do
      [[ -z $key ]] && continue
      default=$(jq_scalar ".cases[$i].options.compare_defaults[\"$key\"]")
      [[ $default == __CONCLUDE_NULL__ ]] && default=""
      args+=(--compare-default "${key}=${default}")
    done < <(jq -r ".cases[$i].options.compare_defaults // {} | keys[]" "$SPEC_FILE")

    local out
    conclude_format_invocation "$app" resolved out "${args[@]}"

    local expected
    expected=$(jq -r ".cases[$i].expect" "$SPEC_FILE")
    if [[ $out != "$expected" ]]; then
      echo "[$name] expected $(printf '%q' "$expected"), got $(printf '%q' "$out")"
      failures=$((failures + 1))
    fi
  done

  [ "$failures" -eq 0 ]
}
