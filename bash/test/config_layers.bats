#!/usr/bin/env bats
# Runs every case in spec/config_layers.json against
# conclude_read_config_table + conclude_cast_table_values, merging layers
# lowest-priority-first: system < user < project < siblings (sorted by
# name, last wins).

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "config_layers: every case in spec/config_layers.json" {
  local file="${SPEC_DIR}/config_layers.json"
  local count
  count=$(jq '.cases | length' "$file")

  local i name is_error failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$file")
    is_error=$(jq -r ".cases[$i].error // false" "$file")

    local -A types=()
    local key type
    while IFS=$'\t' read -r key type; do
      [[ -z $key ]] && continue
      types[$key]=$type
    done < <(jq -r ".cases[$i].settings[] | [.key, .type] | @tsv" "$file")

    local table1 table2
    table1=$(jq -r ".cases[$i].table_path[0]" "$file")
    table2=$(jq -r ".cases[$i].table_path[1] // \"\"" "$file")

    local has_aux aux_type aux_pattern
    has_aux=$(jq -r ".cases[$i] | has(\"aux_pattern\")" "$file")
    if [[ $has_aux == false ]]; then
      aux_pattern=".config.*.toml"
    else
      aux_type=$(jq -r ".cases[$i].aux_pattern | type" "$file")
      if [[ $aux_type == null ]]; then
        aux_pattern=""
      else
        aux_pattern=$(jq -r ".cases[$i].aux_pattern" "$file")
      fi
    fi

    local system_text user_text project_text
    system_text=$(jq -r ".cases[$i].files.system // \"\"" "$file")
    user_text=$(jq -r ".cases[$i].files.user // \"\"" "$file")
    project_text=$(jq -r ".cases[$i].files.project // \"\"" "$file")

    local -a ordered_texts=()
    [[ -n $system_text ]] && ordered_texts+=("$system_text")
    [[ -n $user_text ]] && ordered_texts+=("$user_text")
    [[ -n $project_text ]] && ordered_texts+=("$project_text")

    if [[ -n $aux_pattern ]]; then
      local -a sib_names=()
      while IFS= read -r key; do
        [[ -z $key ]] && continue
        conclude_glob_match "$key" "$aux_pattern" && sib_names+=("$key")
      done < <(jq -r ".cases[$i].files.siblings // {} | keys[]" "$file")
      if ((${#sib_names[@]} > 1)); then
        mapfile -t sib_names < <(printf '%s\n' "${sib_names[@]}" | LC_ALL=C sort)
      fi
      local sib_text
      for key in "${sib_names[@]}"; do
        sib_text=$(jq -r --arg n "$key" ".cases[$i].files.siblings[\$n]" "$file")
        ordered_texts+=("$sib_text")
      done
    fi

    local -A raw=() layer_raw=()
    local text status file_error=0
    for text in "${ordered_texts[@]}"; do
      conclude_read_config_table "$text" layer_raw "$table1" "$table2" && status=0 || status=$?
      if [[ $status -ne 0 ]]; then
        file_error=1
        break
      fi
      local k
      for k in "${!layer_raw[@]}"; do raw[$k]=${layer_raw[$k]}; done
    done

    if [[ $file_error -eq 1 ]]; then
      if [[ $is_error != true ]]; then
        echo "[$name] unexpected error reading config layers"
        failures=$((failures + 1))
      fi
      continue
    fi

    local -A result=()
    conclude_cast_table_values types raw result && status=0 || status=$?

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
    expected_count=$(jq -r ".cases[$i].expect | length" "$file")
    actual_count=${#result[@]}
    if [[ $actual_count -ne $expected_count ]]; then
      echo "[$name] expected $expected_count key(s), got $actual_count: ${!result[*]-}"
      failures=$((failures + 1))
      continue
    fi

    local expected_value actual_value
    while IFS= read -r key; do
      [[ -z $key ]] && continue
      expected_value=$(jq -r --arg k "$key" ".cases[$i].expect[\$k] + \"\u0001\"" "$file" 2>/dev/null) || true
      if [[ -z $expected_value ]]; then
        # .expect[$k] might be a bool/number, which "+" can't concatenate
        # with a string in jq -- fall back to tostring for those.
        expected_value=$(jq -r --arg k "$key" "(.cases[$i].expect[\$k] | tostring) + \"\u0001\"" "$file")
      fi
      expected_value=${expected_value%$'\x01'}
      actual_value=${result[$key]-__CONCLUDE_TEST_MISSING__}
      if [[ $actual_value != "$expected_value" ]]; then
        echo "[$name] key '$key': expected '$expected_value', got '$actual_value'"
        failures=$((failures + 1))
      fi
    done < <(jq -r ".cases[$i].expect | keys[]" "$file")
  done

  [ "$failures" -eq 0 ]
}
