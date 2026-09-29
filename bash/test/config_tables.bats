#!/usr/bin/env bats
# Runs every case in spec/config_tables.json against
# conclude_parse_table_selection (op: parse) and
# conclude_resolve_table_selection (op: resolve).

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

@test "config_tables: every case in spec/config_tables.json" {
  local file="${SPEC_DIR}/config_tables.json"
  local count
  count=$(jq '.cases | length' "$file")

  local i name op is_error expected actual status failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$file")
    op=$(jq -r ".cases[$i].op" "$file")
    is_error=$(jq -r ".cases[$i].error // false" "$file")

    local -a out=()

    if [[ $op == parse ]]; then
      local value default_table
      value=$(jq -r ".cases[$i].value // \"\"" "$file")
      default_table=$(jq -r ".cases[$i].default_table" "$file")

      conclude_parse_table_selection "$value" "$default_table" out && status=0 || status=$?

    elif [[ $op == resolve ]]; then
      local config_value shorthand default_table has_aux aux_type aux_pattern
      config_value=$(jq -r ".cases[$i].config_value // \"\"" "$file")
      shorthand=$(jq -r ".cases[$i].shorthand // \"\"" "$file")
      default_table=$(jq -r ".cases[$i].default_table" "$file")

      has_aux=$(jq -r ".cases[$i] | has(\"aux_pattern\")" "$file")
      if [[ $has_aux == false ]]; then
        aux_pattern=".config.*.toml"
      else
        aux_type=$(jq -r ".cases[$i].aux_pattern | type" "$file")
        if [[ $aux_type == null ]]; then
          aux_pattern="" # sentinel: siblings disabled
        else
          aux_pattern=$(jq -r ".cases[$i].aux_pattern" "$file")
        fi
      fi

      local system_text user_text project_text
      system_text=$(jq -r ".cases[$i].files.system // \"\"" "$file")
      user_text=$(jq -r ".cases[$i].files.user // \"\"" "$file")
      project_text=$(jq -r ".cases[$i].files.project // \"\"" "$file")

      local -a texts=()
      [[ -n $system_text ]] && texts+=("$system_text")
      [[ -n $user_text ]] && texts+=("$user_text")
      [[ -n $project_text ]] && texts+=("$project_text")

      if [[ -n $aux_pattern ]]; then
        local sib_name sib_text
        while IFS= read -r sib_name; do
          [[ -z $sib_name ]] && continue
          if conclude_glob_match "$sib_name" "$aux_pattern"; then
            sib_text=$(jq -r --arg n "$sib_name" ".cases[$i].files.siblings[\$n]" "$file")
            texts+=("$sib_text")
          fi
        done < <(jq -r ".cases[$i].files.siblings // {} | keys[]" "$file")
      fi

      conclude_resolve_table_selection "$config_value" "$shorthand" "$default_table" out -- "${texts[@]}" && status=0 || status=$?
    else
      echo "[$name] unknown op '$op'"
      failures=$((failures + 1))
      continue
    fi

    if [[ $is_error == true ]]; then
      if [[ $status -ne 1 ]]; then
        echo "[$name] expected an error (exit 1), got exit $status (out: ${out[*]-})"
        failures=$((failures + 1))
      fi
      continue
    fi

    if [[ $status -ne 0 ]]; then
      echo "[$name] expected success, got exit $status"
      failures=$((failures + 1))
      continue
    fi

    expected=$(jq -r ".cases[$i].expect | join(\",\")" "$file")
    actual=$(
      IFS=,
      echo "${out[*]}"
    )
    if [[ $actual != "$expected" ]]; then
      echo "[$name] expected [$expected], got [$actual]"
      failures=$((failures + 1))
    fi
  done

  [ "$failures" -eq 0 ]
}
