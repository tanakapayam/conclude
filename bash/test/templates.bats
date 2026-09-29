#!/usr/bin/env bats
# Runs every case in spec/templates.json against conclude_format_env,
# conclude_format_toml, and conclude_format_cli. Each case only checks
# whichever of env/toml/cli its `expect` object actually has.

setup() {
  SPEC_DIR="${BATS_TEST_DIRNAME}/../../spec"
  SPEC_FILE="${SPEC_DIR}/templates.json"
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
}

# define_case_app APP IDX -- runs conclude_init/conclude_define for every
# setting in .cases[IDX].settings, giving APP a fresh declaration.
define_case_app() {
  local app=$1 idx=$2
  conclude_init "$app"
  local key type has_default default
  while IFS=$'\t' read -r key type; do
    [[ -z $key ]] && continue
    has_default=$(jq -r ".cases[$idx].settings[] | select(.key==\"$key\") | (.default != null)" "$SPEC_FILE")
    if [[ $has_default == true ]]; then
      default=$(jq -r ".cases[$idx].settings[] | select(.key==\"$key\") | .default as \$v | if (\$v|type)==\"array\" then (\$v|join(\",\")) else (\$v|tostring) end" "$SPEC_FILE")
      conclude_define "$app" "$key" "$type" "$default"
    else
      conclude_define "$app" "$key" "$type"
    fi
  done < <(jq -r ".cases[$idx].settings[] | [.key, .type] | @tsv" "$SPEC_FILE")
}

@test "templates: every case in spec/templates.json" {
  local count
  count=$(jq '.cases | length' "$SPEC_FILE")

  local i name app failures=0
  for ((i = 0; i < count; i++)); do
    name=$(jq -r ".cases[$i].name" "$SPEC_FILE")
    app=$(jq -r ".cases[$i].app" "$SPEC_FILE")
    define_case_app "$app" "$i"

    local -a opt_args=()
    local skip_list
    skip_list=$(jq -r ".cases[$i].options.skip // [] | join(\",\")" "$SPEC_FILE")
    [[ -n $skip_list ]] && opt_args+=(--skip "$skip_list")

    local dkey
    while IFS= read -r dkey; do
      [[ -z $dkey ]] && continue
      local dval
      dval=$(jq -r --arg k "$dkey" '.cases['"$i"'].options.defaults[$k] as $v | if ($v|type)=="array" then ($v|join(",")) else ($v|tostring) end' "$SPEC_FILE")
      opt_args+=(--default "${dkey}=${dval}")
    done < <(jq -r ".cases[$i].options.defaults // {} | keys[]" "$SPEC_FILE")

    local has_env has_toml has_cli
    has_env=$(jq -r ".cases[$i].expect | has(\"env\")" "$SPEC_FILE")
    has_toml=$(jq -r ".cases[$i].expect | has(\"toml\")" "$SPEC_FILE")
    has_cli=$(jq -r ".cases[$i].expect | has(\"cli\")" "$SPEC_FILE")

    if [[ $has_env == true ]]; then
      local -a env_args=("${opt_args[@]}")
      local ekey
      while IFS= read -r ekey; do
        [[ -z $ekey ]] && continue
        env_args+=(--env-var "${ekey}=$(jq -r --arg k "$ekey" '.cases['"$i"'].options.env_vars[$k]' "$SPEC_FILE")")
      done < <(jq -r ".cases[$i].options.env_vars // {} | keys[]" "$SPEC_FILE")
      local out expected
      conclude_format_env "$app" out "${env_args[@]}"
      expected=$(jq -r ".cases[$i].expect.env" "$SPEC_FILE")
      if [[ $out != "$expected" ]]; then
        echo "[$name] env: expected $(printf '%q' "$expected"), got $(printf '%q' "$out")"
        failures=$((failures + 1))
      fi
    fi

    if [[ $has_toml == true ]]; then
      local -a toml_args=("${opt_args[@]}")
      local header header_present
      header_present=$(jq -r ".cases[$i].options | has(\"header\")" "$SPEC_FILE")
      if [[ $header_present == true ]]; then
        header=$(jq -r ".cases[$i].options.header" "$SPEC_FILE")
      else
        header=true
      fi
      [[ $header == false ]] && toml_args+=(--no-header)
      local table_type
      table_type=$(jq -r ".cases[$i].options | has(\"table\")" "$SPEC_FILE")
      if [[ $table_type == true ]]; then
        table_type=$(jq -r ".cases[$i].options.table | type" "$SPEC_FILE")
        if [[ $table_type == array ]]; then
          local part
          local arr_len
          arr_len=$(jq -r ".cases[$i].options.table | length" "$SPEC_FILE")
          if [[ $arr_len -eq 0 ]]; then
            toml_args+=(--no-header)
          else
            while IFS= read -r part; do
              toml_args+=(--table "$part")
            done < <(jq -r ".cases[$i].options.table[]" "$SPEC_FILE")
          fi
        else
          toml_args+=(--table "$(jq -r ".cases[$i].options.table" "$SPEC_FILE")")
        fi
      fi
      local out expected
      conclude_format_toml "$app" out "${toml_args[@]}"
      expected=$(jq -r ".cases[$i].expect.toml" "$SPEC_FILE")
      if [[ $out != "$expected" ]]; then
        echo "[$name] toml: expected $(printf '%q' "$expected"), got $(printf '%q' "$out")"
        failures=$((failures + 1))
      fi
    fi

    if [[ $has_cli == true ]]; then
      local -a cli_args=("${opt_args[@]}")
      local mkey
      while IFS= read -r mkey; do
        [[ -z $mkey ]] && continue
        local mtype mval
        mtype=$(jq -r --arg k "$mkey" '.cases['"$i"'].options.metavars[$k] | type' "$SPEC_FILE")
        if [[ $mtype == array ]]; then
          mval=$(jq -r --arg k "$mkey" '.cases['"$i"'].options.metavars[$k] | join(",")' "$SPEC_FILE")
        else
          mval=$(jq -r --arg k "$mkey" '.cases['"$i"'].options.metavars[$k]' "$SPEC_FILE")
        fi
        cli_args+=(--metavar "${mkey}=${mval}")
      done < <(jq -r ".cases[$i].options.metavars // {} | keys[]" "$SPEC_FILE")
      local out expected
      conclude_format_cli "$app" out "${cli_args[@]}"
      expected=$(jq -r ".cases[$i].expect.cli" "$SPEC_FILE")
      if [[ $out != "$expected" ]]; then
        echo "[$name] cli: expected $(printf '%q' "$expected"), got $(printf '%q' "$out")"
        failures=$((failures + 1))
      fi
    fi
  done

  [ "$failures" -eq 0 ]
}
