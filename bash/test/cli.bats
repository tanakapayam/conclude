#!/usr/bin/env bats
# Runs every case in spec/cli.json against conclude_parse_cli, and checks that
# conclude_resolve and the formatters refuse flags two settings both claim.
# jq is a test-only dependency -- conclude.sh itself never uses it.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/cli.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
  cd "$BATS_TEST_TMPDIR" || exit 1
  export HOME="${BATS_TEST_TMPDIR}/home"
  mkdir -p "$HOME"
  unset XDG_CONFIG_HOME
}

@test "cli: every case in spec/cli.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name app key type failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    app="app_${i}" # a fresh app name per case avoids any declaration bleed

    # Parsing never looks at a default, so declare each setting by type alone.
    conclude_init "$app"
    while IFS=$'\t' read -r key type; do
      [[ -z $key ]] && continue
      conclude_define "$app" "$key" "$type"
    done < <(jq -r ".cases[$i].settings[] | [.key, .type] | @tsv" "$SPEC_FILE")

    local -a argv=()
    mapfile -t argv < <(jq -r ".cases[$i].argv[]" "$SPEC_FILE")

    local -A parsed=()
    local status=0
    conclude_parse_cli "$app" parsed "${argv[@]}" 2>/dev/null || status=$?

    if [[ $(jq -r ".cases[$i].error // false" "$SPEC_FILE") == true ]]; then
      if ((status == 0)); then
        echo "[$name] expected an error, got success"
        failures=$((failures + 1))
      fi
      continue
    fi
    if ((status != 0)); then
      echo "[$name] expected success, got status $status"
      failures=$((failures + 1))
      continue
    fi

    local -A expected=()
    local value
    while IFS=$'\t' read -r key value; do
      [[ -z $key ]] && continue
      expected[$key]=$value
    done < <(jq -r ".cases[$i].expect | to_entries[] | [.key, (.value | tostring)] | @tsv" "$SPEC_FILE")

    if ((${#parsed[@]} != ${#expected[@]})); then
      echo "[$name] expected ${#expected[@]} setting(s) given, got ${#parsed[@]}"
      failures=$((failures + 1))
    fi
    for key in "${!expected[@]}"; do
      if [[ ! -v parsed[$key] || ${parsed[$key]} != "${expected[$key]}" ]]; then
        echo "[$name] $key: expected '${expected[$key]}', got '${parsed[$key]-<unset>}'"
        failures=$((failures + 1))
      fi
    done
    unset parsed expected argv
  done

  [ "$failures" -eq 0 ]
}

@test "cli: a bool's negation turns off a value a lower layer turned on" {
  conclude_init app
  conclude_define app debug bool false
  APP_DEBUG=true conclude_resolve app -- --no-debug
  [ "${CONCLUDE[debug]}" = false ]
  APP_DEBUG=false conclude_resolve app -- --debug
  [ "${CONCLUDE[debug]}" = true ]
  APP_DEBUG=true conclude_resolve app --
  [ "${CONCLUDE[debug]}" = true ]
}

@test "cli: a flag no setting claims is still an error" {
  conclude_init app
  conclude_define app debug bool false
  run conclude_resolve app -- --no-nope
  [ "$status" -eq 1 ]
  [[ $output == *"unrecognized argument"* ]]
}

@test "cli: resolve, format_cli and format_invocation refuse flags two settings claim" {
  conclude_init app
  conclude_define app cache bool false
  conclude_define app no_cache bool false
  run conclude_resolve app --
  [ "$status" -eq 1 ]
  [[ $output == *"both claim the CLI flag --no-cache"* ]]

  local out
  run conclude_format_cli app out
  [ "$status" -eq 1 ]
  [[ $output == *"both claim the CLI flag --no-cache"* ]]

  local -A resolved=([cache]=true [no_cache]=false)
  run conclude_format_invocation app resolved out
  [ "$status" -eq 1 ]
}

@test "cli: a skipped setting claims no flag" {
  conclude_init app
  conclude_define app cache bool false
  conclude_define app no_cache bool false
  local out
  conclude_format_cli app out --skip no_cache
  [ "$out" = "--cache (default: false)" ]
}

# What conclude_format_invocation writes, conclude_resolve reads back to the
# same configuration -- including a bool whose default is true. Each resolve
# runs in a subshell, because conclude_resolve exports its results and a second
# call in the same shell would read them back as environment-layer values.
_values() {
  (
    conclude_resolve app -- "$@" || exit 1
    local key
    for key in cache debug no_color verbose; do
      printf '%s=%s\n' "$key" "${CONCLUDE[$key]-}"
    done
  )
}

_round_trip() {
  local before after line key value
  before=$(_values "$@") || return 1
  local -A resolved=()
  while IFS='=' read -r key value; do
    resolved[$key]=$value
  done <<<"$before"

  conclude_format_invocation app resolved line
  local -a argv=()
  read -ra argv <<<"$line"
  after=$(_values "${argv[@]}") || return 1

  [[ $before == "$after" ]] || {
    echo "wrote '$line'"
    echo "before: ${before//$'\n'/ }"
    echo "after:  ${after//$'\n'/ }"
    return 1
  }
}

@test "cli: an invocation reads back to the configuration it was written from" {
  conclude_init app
  conclude_define app cache bool true
  conclude_define app debug bool false
  conclude_define app no_color bool false
  conclude_define app verbose bool

  _round_trip
  _round_trip --no-cache
  _round_trip --debug
  _round_trip --no-color
  _round_trip --color
  _round_trip --no-cache --debug --no-color --verbose
  _round_trip --cache --no-debug --color --no-verbose
}
