#!/usr/bin/env bats
# Runs every case in spec/naming.json against conclude_cli_flag_name,
# conclude_env_var_name and conclude_config_key_name. jq is a test-only
# dependency -- conclude.sh itself never uses it.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "naming: every case in spec/naming.json" {
  local file="${SPEC_DIR}/naming.json"
  local count
  count=$(jq '.cases | length' "$file")

  local i name app key expected_env expected_cli expected_config actual failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$file")
    app=$(jq -r ".cases[$i].app" "$file")
    key=$(jq -r ".cases[$i].key" "$file")
    expected_env=$(jq -r ".cases[$i].env_var" "$file")
    expected_cli=$(jq -r ".cases[$i].cli_flag" "$file")
    expected_config=$(jq -r ".cases[$i].config_key" "$file")

    actual=$(conclude_env_var_name "$app" "$key")
    if [[ $actual != "$expected_env" ]]; then
      echo "[$name] env_var: expected '$expected_env', got '$actual'"
      failures=$((failures + 1))
    fi

    actual=$(conclude_cli_flag_name "$key")
    if [[ $actual != "$expected_cli" ]]; then
      echo "[$name] cli_flag: expected '$expected_cli', got '$actual'"
      failures=$((failures + 1))
    fi

    actual=$(conclude_config_key_name "$key")
    if [[ $actual != "$expected_config" ]]; then
      echo "[$name] config_key: expected '$expected_config', got '$actual'"
      failures=$((failures + 1))
    fi
  done

  [ "$failures" -eq 0 ]
}
