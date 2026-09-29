#!/usr/bin/env bats
# Runs every case in spec/dotenv.json against conclude_parse_dotenv.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "dotenv: every case in spec/dotenv.json" {
  local file="${SPEC_DIR}/dotenv.json"
  local count
  count=$(jq '.cases | length' "$file")

  local i name text expected_count actual_count failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$file")
    text=$(jq -r ".cases[$i].text" "$file")

    local -A vars=()
    conclude_parse_dotenv "$text" vars

    expected_count=$(jq -r ".cases[$i].expect | length" "$file")
    actual_count=${#vars[@]}
    if [[ $actual_count -ne $expected_count ]]; then
      echo "[$name] expected $expected_count key(s), got $actual_count: ${!vars[*]}"
      failures=$((failures + 1))
      continue
    fi

    local key expected_value actual_value
    # The trailing \u0001 marker stops command substitution's automatic
    # trailing-newline stripping from eating a real trailing newline that
    # is itself part of the expected value (see the \n-decoding cases).
    while IFS= read -r key; do
      [[ -z $key ]] && continue
      expected_value=$(jq -r --arg k "$key" ".cases[$i].expect[\$k] + \"\u0001\"" "$file")
      expected_value=${expected_value%$'\x01'}
      actual_value=${vars[$key]-__CONCLUDE_TEST_MISSING__}
      if [[ $actual_value != "$expected_value" ]]; then
        echo "[$name] key '$key': expected '$expected_value', got '$actual_value'"
        failures=$((failures + 1))
      fi
    done < <(jq -r ".cases[$i].expect | keys[]" "$file")
  done

  [ "$failures" -eq 0 ]
}
