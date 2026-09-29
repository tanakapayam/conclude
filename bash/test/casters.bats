#!/usr/bin/env bats
# Runs spec/casters.json against conclude_cast. jq is a test-only
# dependency -- conclude.sh itself never uses it.
#
# Skipped by design: cases where .input is a native JSON array (the
# "native list" cases). A Bash caller only ever has a string; see the
# comment above conclude_cast in src/conclude.sh for why those cases
# don't apply here.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "casters: every applicable case in spec/casters.json" {
  local file="${SPEC_DIR}/casters.json"
  local count
  count=$(jq '.cases | length' "$file")

  local i name type input_type input is_error is_unset expected actual status
  local failures=0 skipped=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$file")
    type=$(jq -r ".cases[$i].type" "$file")
    input_type=$(jq -r ".cases[$i].input | type" "$file")

    if [[ $input_type == array ]]; then
      skipped=$((skipped + 1))
      continue
    fi

    is_error=$(jq -r ".cases[$i].error // false" "$file")
    is_unset=$(jq -r "(.cases[$i] | has(\"output\")) and (.cases[$i].output == null)" "$file")

    if [[ $input_type == "null" ]]; then
      input=""
    else
      input=$(jq -r ".cases[$i].input" "$file")
    fi

    if [[ $type == list ]]; then
      actual=$(conclude_cast "$type" "$input") && status=0 || status=$?
      actual=${actual//$'\n'/,}
      expected=$(jq -r ".cases[$i].output // [] | join(\",\")" "$file")
    else
      actual=$(conclude_cast "$type" "$input") && status=0 || status=$?
      expected=$(jq -r ".cases[$i].output" "$file")
    fi

    if [[ $is_error == true ]]; then
      if [[ $status -ne 1 ]]; then
        echo "[$name] expected an error (exit 1), got exit $status (output: '$actual')"
        failures=$((failures + 1))
      fi
    elif [[ $is_unset == true ]]; then
      if [[ $status -ne 2 ]]; then
        echo "[$name] expected unset (exit 2), got exit $status (output: '$actual')"
        failures=$((failures + 1))
      fi
    else
      if [[ $status -ne 0 ]]; then
        echo "[$name] expected success, got exit $status"
        failures=$((failures + 1))
      elif [[ $actual != "$expected" ]]; then
        echo "[$name] expected '$expected', got '$actual'"
        failures=$((failures + 1))
      fi
    fi
  done

  echo "# skipped $skipped native-array case(s) -- not applicable to a string-only caller" >&3
  [ "$failures" -eq 0 ]
}
