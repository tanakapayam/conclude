#!/usr/bin/env bats
# Runs every case in spec/merge.json against conclude_merge_layers.
#
# A native-array raw value (a defaults declaration or a "config" layer
# value given directly as a JSON array, e.g. ["x", " y "]) is joined
# into conclude_cast's comma-separated convention here in the harness --
# see the comment above conclude_merge_layers in src/conclude.sh for why
# that's the caller's job, not this function's.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/merge.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

# jq_scalar EXPR -- EXPR must yield a JSON value (or be absent/null).
# Echoes "__CONCLUDE_NULL__" for null/absent, else the value as text
# (arrays comma-joined, everything else via tostring).
jq_scalar() {
  jq -r "(${1}) as \$v | if \$v == null then \"__CONCLUDE_NULL__\" elif (\$v|type)==\"array\" then (\$v|join(\",\")) else (\$v|tostring) end" "$SPEC_FILE"
}

# fill_object_layer OUTVAR JQPATH -- JQPATH is an object-valued jq
# expression (e.g. ".cases[3].layers.config"); populates OUTVAR with
# every non-null key from it.
fill_object_layer() {
  local -n _out=$1
  local path=$2
  _out=()
  local key val
  while IFS= read -r key; do
    [[ -z $key ]] && continue
    val=$(jq_scalar "${path}[\"${key}\"]")
    [[ $val == __CONCLUDE_NULL__ ]] && continue
    _out[$key]=$val
  done < <(jq -r "${path} // {} | keys[]" "$SPEC_FILE")
}

@test "merge: every case in spec/merge.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name is_error failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    is_error=$(jq -r ".cases[$i].error // false" "$SPEC_FILE")

    local -A types=() defaults=() config=() env=() developer=() cli=() result=()
    local key val
    while IFS=$'\t' read -r key val; do
      [[ -z $key ]] && continue
      types[$key]=$val
    done < <(jq -r ".cases[$i].settings[] | [.key, .type] | @tsv" "$SPEC_FILE")

    while IFS= read -r key; do
      [[ -z $key ]] && continue
      val=$(jq_scalar ".cases[$i].settings[] | select(.key==\"$key\") | .default")
      [[ $val == __CONCLUDE_NULL__ ]] && continue
      defaults[$key]=$val
    done < <(jq -r ".cases[$i].settings[].key" "$SPEC_FILE")

    fill_object_layer config ".cases[$i].layers.config"
    fill_object_layer env ".cases[$i].layers.env"
    fill_object_layer developer ".cases[$i].layers.developer"
    fill_object_layer cli ".cases[$i].layers.cli"

    local status
    conclude_merge_layers types result defaults config env developer cli && status=0 || status=$?

    if [[ $is_error == true ]]; then
      if [[ $status -ne 1 ]]; then
        echo "[$name] expected an error (exit 1), got exit $status"
        failures=$((failures + 1))
      fi
      continue
    fi

    if [[ $status -ne 0 ]]; then
      echo "[$name] expected success, got exit $status"
      failures=$((failures + 1))
      continue
    fi

    local expected_count actual_count
    expected_count=$(jq -r ".cases[$i].expect | length" "$SPEC_FILE")
    actual_count=${#result[@]}
    if [[ $actual_count -ne $expected_count ]]; then
      echo "[$name] expected $expected_count key(s), got $actual_count: ${!result[*]-}"
      failures=$((failures + 1))
      continue
    fi

    local expected actual
    while IFS= read -r key; do
      [[ -z $key ]] && continue
      expected=$(jq_scalar ".cases[$i].expect[\"$key\"]")
      [[ $expected == __CONCLUDE_NULL__ ]] && expected=""
      actual=${result[$key]-__CONCLUDE_TEST_MISSING__}
      actual=${actual//$'\n'/,}
      if [[ $actual != "$expected" ]]; then
        echo "[$name] key '$key': expected '$expected', got '$actual'"
        failures=$((failures + 1))
      fi
    done < <(jq -r ".cases[$i].expect | keys[]" "$SPEC_FILE")
  done

  [ "$failures" -eq 0 ]
}
