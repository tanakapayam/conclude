#!/usr/bin/env bash
# conclude.sh -- Bash port of `conclude` (see docs/concept.md at the repo root).
#
# "Declare your defaults once. Conclude derives the interfaces through
# which those settings can be configured."
#
# Requires Bash 5.3+. Source this file at the top of a script:
#
#   source -p "$BASH_PACKAGES" conclude.sh
#
# Everything in this file is namespaced under the `conclude_` prefix
# (public API) or `_conclude_` prefix (internal, do not call directly).
# Internal state is kept in associative arrays keyed "$app:$key" rather
# than one array per app, since Bash has no nested associative arrays.
#
# Needs nothing but Bash, coreutils, awk (fractional numbers only) and,
# for the developer/.env guard, git. Layout, top to bottom: naming,
# casters, dotenv, config/TOML, guard, merge and resolve, introspection,
# templates and invocation. See docs/bash/ for the guide and reference.

# shellcheck disable=SC2034,SC2004
# ^ SC2034 ("appears unused") and SC2004 ("$ unnecessary in arithmetic")
#   are both false positives for this file's core calling convention: a
#   caller declares an associative array and passes its *name*, and the
#   function reads or fills it through a nameref -- shellcheck can't see
#   through that, so it flags the array as unused and its `$key`
#   subscripts as arithmetic (associative subscripts need the `$`).

# shellcheck disable=SC2317
# ^ `exit 1` is the fallback for when this file is executed rather than
#   sourced (`return` fails outside a function/sourced script).
if (( BASH_VERSINFO[0] < 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] < 3) )); then
  printf 'conclude.sh: requires Bash 5.3+, running %s\n' "$BASH_VERSION" >&2
  return 1 2>/dev/null || exit 1
fi

# The version of this file; the release workflow checks it against the
# release tag and CHANGELOG.md, so bump all three together.
CONCLUDE_VERSION="0.2.0"

# --- naming (spec/naming.json) --------------------------------------------
#
# Each layer's conventional name for a setting, derived from the app name
# and the setting's key alone, so an app writes each name exactly once.

# _conclude_sanitize_ident TEXT
#   Replace every character that isn't [0-9A-Za-z_] with "_", one output
#   character per *codepoint* of input, matching the Python/Node behavior
#   (Python's `re` and JS strings are both codepoint-oriented). Bash's own
#   bracket-expression matching is locale-dependent: under a byte-oriented
#   locale (e.g. LC_CTYPE=POSIX/C, common in minimal containers) a
#   multi-byte UTF-8 character is matched byte-by-byte, producing one "_"
#   per byte instead of one per codepoint -- e.g. "café" would sanitize to
#   "caf__" (2 bytes for "é") instead of "caf_" (1 codepoint). Forcing
#   LC_CTYPE=C.UTF-8 for just this function's scope (via `local`, which
#   Bash honors for its own multibyte handling even without `export`, and
#   which never leaks to the caller) makes the result locale-independent.
_conclude_sanitize_ident() {
  local LC_CTYPE=C.UTF-8
  local text=$1
  printf '%s' "${text//[^0-9A-Za-z_]/_}"
}

# conclude_cli_flag_name KEY
#   "filter_col" -> "--filter-col"
conclude_cli_flag_name() {
  local key=$1
  printf -- '--%s' "${key//_/-}"
}

# conclude_env_var_name APP KEY
#   ("remind", "retries") -> "REMIND_RETRIES"
#   Non-identifier characters in either part become "_" first (so a
#   hyphenated app name like "my-app" doesn't produce the shell-illegal
#   "MY-APP_..."), and a leading digit gets a "_" prefix (a shell
#   identifier can't start with one).
conclude_env_var_name() {
  local app=$1 key=$2
  local name
  name=$(_conclude_sanitize_ident "$app")_$(_conclude_sanitize_ident "$key")
  name=${name^^}
  if [[ $name == [0-9]* ]]; then
    name="_${name}"
  fi
  printf '%s' "$name"
}

# conclude_config_key_name KEY
#   Always just KEY itself -- a config file's keys already are the
#   defaults dict's keys. Provided for symmetry so callers never have to
#   special-case "no translation needed" for this one layer.
conclude_config_key_name() {
  printf '%s' "$1"
}

# --- casters (spec/casters.json) -------------------------------------------
#
# Turning a raw string from any layer into a setting's declared type.
# Exit-code convention, uniform across every type (this is the one thing
# Bash needs that the other ports don't, since a Bash function can't
# distinguish "the value is an empty string" from "there is no value" by
# its return alone):
#
#   0  -- value cast successfully; printed on stdout (for `list`, one
#         item per line -- possibly zero lines, which is a real empty
#         list and different from "unset")
#   1  -- the input doesn't parse as the declared type; nothing printed,
#         a message goes to stderr
#   2  -- "unset" (the spec's `output: null`); nothing printed
#
# `bool` never returns 2 -- an absent bool already means false, the same
# way it does in Python's cast_bool, so there is no separate unset state
# for it (see "bool: empty string is false" in the fixture: false, not
# null, unlike every other type's empty-string case).
#
# `list`'s native-array fixture cases (a TOML array given directly,
# e.g. `["a", " b ", ""]`) have no Bash equivalent here: a Bash caller
# only ever has a string. When the TOML config-table loader is built, it
# is what will turn a TOML array into the same comma-separated string
# convention before it ever reaches this caster -- so those cases are
# intentionally out of scope for `conclude_cast` itself.

_conclude_trim() {
  local s=$1
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

_conclude_cast_bool() {
  local raw=$1 text
  text=$(_conclude_trim "$raw")
  text=${text,,}
  if [[ -z $text ]]; then
    printf 'false'
    return 0
  fi
  case $text in
    1 | true | yes | on | y)
      printf 'true'
      return 0
      ;;
    0 | false | no | off | n)
      printf 'false'
      return 0
      ;;
    *)
      printf 'conclude: expected a boolean (true/false/yes/no/on/off/1/0/y/n), got %q\n' "$raw" >&2
      return 1
      ;;
  esac
}

# Canonicalize a bare (optionally signed) integer digit string: drop a
# leading "+", strip redundant leading zeros, and fold "-0" to "0" --
# matching what Python's int() -> str() round-trip would print.
_conclude_canonical_int() {
  local s=$1 sign=""
  if [[ $s == -* ]]; then
    sign="-"
    s=${s#-}
  elif [[ $s == +* ]]; then
    s=${s#+}
  fi
  while [[ ${#s} -gt 1 && $s == 0* ]]; do
    s=${s:1}
  done
  [[ $s == 0 ]] && sign=""
  printf '%s%s' "$sign" "$s"
}

# Shared by `int` and `float`: both accept a whole or fractional number
# and print the same canonical text (whole numbers print with no
# trailing ".0" either way -- see spec/casters.json, e.g. "int: native
# whole number" 5.0 -> 5 and "float: whole number" "5" -> 5). A bare
# integer, or one with a redundant all-zero decimal tail ("5", "5.00"),
# is handled in pure Bash without ever going through floating point, so
# an integer too large for a double's 53 exact bits is never at risk of
# silent precision loss -- the same reasoning as Python's
# _try_parse_exact_int. Anything else (a genuine fraction, scientific
# notation) is handed to `awk` for the actual arithmetic: Bash has no
# floating-point support at all, and reimplementing IEEE-double parsing
# and formatting by hand in shell would be a much worse bet than calling
# the one tool that's already guaranteed to be on the system for exactly
# this.
_conclude_cast_number() {
  local raw=$1 text
  [[ -z $raw ]] && return 2
  text=$(_conclude_trim "$raw")
  if [[ -z $text ]]; then
    printf 'conclude: expected a number, got %q\n' "$raw" >&2
    return 1
  fi
  local num_re='^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
  if [[ ! $text =~ $num_re ]]; then
    printf 'conclude: expected a number, got %q\n' "$raw" >&2
    return 1
  fi
  local int_re='^([+-]?[0-9]+)$' tz_re='^([+-]?[0-9]+)\.0*$'
  if [[ $text =~ $int_re ]] || [[ $text =~ $tz_re ]]; then
    _conclude_canonical_int "${BASH_REMATCH[1]}"
    return 0
  fi
  awk -v v="$text" 'BEGIN { x = v + 0; if (x == int(x)) printf "%d", x; else printf "%.15g", x }'
  return 0
}

_conclude_cast_str() {
  local raw=$1
  [[ -z $raw ]] && return 2
  printf '%s' "$raw"
}

_conclude_cast_list() {
  local raw=$1
  [[ -z $raw ]] && return 2
  local IFS=','
  local -a parts
  read -ra parts <<<"$raw"
  local item trimmed first=1
  for item in "${parts[@]}"; do
    trimmed=$(_conclude_trim "$item")
    [[ -z $trimmed ]] && continue
    if [[ $first -eq 1 ]]; then
      printf '%s' "$trimmed"
      first=0
    else
      printf '\n%s' "$trimmed"
    fi
  done
  return 0
}

# conclude_cast TYPE VALUE -- see the exit-code convention above.
conclude_cast() {
  local type=$1 raw=$2
  case $type in
    bool) _conclude_cast_bool "$raw" ;;
    int | float) _conclude_cast_number "$raw" ;;
    str) _conclude_cast_str "$raw" ;;
    list) _conclude_cast_list "$raw" ;;
    *)
      printf 'conclude: unknown type %q\n' "$type" >&2
      return 1
      ;;
  esac
}

# conclude_decode_backslash_escapes TEXT
#   Decodes just \n \t \r \\ \" -- left-to-right, one match at a time --
#   leaving every other character, including any non-ASCII one, and any
#   other backslash sequence (\x41, \q, a trailing lone \) exactly as
#   written. A left-to-right scan (rather than a global substitution per
#   escape) matters here for the same reason it does in Python: it's the
#   only way to get input like a literal backslash-backslash-n right
#   without the substitutions stepping on each other.
#   Forces LC_CTYPE=C.UTF-8 for this function's scope so `${text:i:1}`
#   walks whole codepoints rather than raw bytes under a byte-oriented
#   locale -- the same fix as _conclude_sanitize_ident, needed here for
#   the same reason (see its comment above).
conclude_decode_backslash_escapes() {
  local LC_CTYPE=C.UTF-8
  local text=$1 i=0 len out='' ch next
  len=${#text}
  while ((i < len)); do
    ch=${text:i:1}
    # shellcheck disable=SC1003 # a lone backslash in quotes is the point
    if [[ $ch == '\' ]]; then
      next=${text:i+1:1}
      case $next in
        n)
          out+=$'\n'
          i=$((i + 2))
          ;;
        t)
          out+=$'\t'
          i=$((i + 2))
          ;;
        r)
          out+=$'\r'
          i=$((i + 2))
          ;;
        '\')
          out+='\'
          i=$((i + 2))
          ;;
        '"')
          out+='"'
          i=$((i + 2))
          ;;
        *)
          out+="$ch"
          i=$((i + 1))
          ;;
      esac
    else
      out+="$ch"
      i=$((i + 1))
    fi
  done
  printf '%s' "$out"
}

# --- dotenv (spec/dotenv.json) ---------------------------------------------
#
# The .env dialect: parses only, never `source`s the file (see naming.sh's
# comment on why bash-native `source`ing a .env is off the table entirely --
# a value like `A=$(rm -rf ~)` would execute). Values may legitimately
# contain embedded newlines (a double-quoted "\n" decodes to a real one),
# so unlike the caster functions above, these hand results back through a
# caller-supplied associative array (a nameref) rather than stdout -- a
# newline-delimited stdout convention would be ambiguous the moment a
# value itself contains one.
#
#   declare -A vars
#   conclude_parse_dotenv "$text" vars
#
# The output array name must not be `_cd_out` (the internal nameref
# variable) -- Bash namerefs can't safely alias a variable that shares
# their own local name.

# conclude_parse_dotenv TEXT OUTVAR
conclude_parse_dotenv() {
  local LC_CTYPE=C.UTF-8
  local text=$1 outvar=$2
  local -n _cd_out=$outvar
  _cd_out=()

  # A leading UTF-8 byte-order mark is ignored.
  text=${text#$'\xef\xbb\xbf'}

  # Recognize \r\n and lone \r as line endings too, alongside \n.
  text=${text//$'\r\n'/$'\n'}
  text=${text//$'\r'/$'\n'}

  local -a lines
  mapfile -t lines <<<"$text"

  local raw line key value quote last
  for raw in "${lines[@]}"; do
    line=$(_conclude_trim "$raw")
    [[ -z $line ]] && continue
    [[ $line == '#'* ]] && continue
    if [[ $line == "export "* ]]; then
      line=$(_conclude_trim "${line#export }")
    fi
    [[ $line != *=* ]] && continue

    key=$(_conclude_trim "${line%%=*}")
    value=$(_conclude_trim "${line#*=}")

    if ((${#value} >= 2)); then
      quote=${value:0:1}
      last=${value: -1}
      if [[ ($quote == '"' || $quote == "'") && $quote == "$last" ]]; then
        value=${value:1:${#value}-2}
        if [[ $quote == '"' ]]; then
          # A trailing \u0001 marker keeps command substitution's automatic
          # trailing-newline stripping from eating a real trailing newline
          # that a decoded "\n" put at the end of the value (see
          # spec/dotenv.json's "non-ASCII in double quotes" case).
          local _decoded
          _decoded=$(conclude_decode_backslash_escapes "$value"; printf '\x01')
          value=${_decoded%$'\x01'}
        fi
      fi
    fi

    _cd_out[$key]=$value
  done
}

# conclude_load_dotenv PATH OUTVAR
#   Reads PATH as UTF-8 and parses it. Leaves OUTVAR empty (and returns 0,
#   not an error) if PATH doesn't exist or isn't a regular file -- a
#   missing .env is the normal, expected case, not a failure.
conclude_load_dotenv() {
  local path=$1 outvar=$2
  local -n _cd_load_out=$outvar
  if [[ ! -f $path ]]; then
    _cd_load_out=()
    return 0
  fi
  local text
  text=$(<"$path")
  conclude_parse_dotenv "$text" "$outvar"
}

# --- config / TOML (spec/config_tables.json, spec/config_layers.json) -----
#
# Scoped to exactly what the spec exercises: two-level [app]/[app.child]
# tables with bool/int/float/str values (TOML arrays are explicitly out of
# scope here -- see the note on conclude_cast's `list` type above; when a
# real config file has one, the plan is for whatever calls this module to
# join it into the same comma-separated convention before casting, not for
# this parser to understand TOML array syntax). This is deliberately not a
# general TOML parser.

_CONCLUDE_TOML_HEADER_RE='^\[([A-Za-z0-9_.-]+)\]$'
_CONCLUDE_TOML_KV_RE='^([A-Za-z0-9_-]+)[[:space:]]*=[[:space:]]*(.+)$'
_CONCLUDE_TOML_NUM_RE='^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'

# _conclude_toml_valid_value TEXT
#   Whether TEXT (already trimmed) is a value shape this parser
#   understands: a double- or single-quoted string, true/false, or a
#   number. Anything else -- including a TOML array, inline table, date,
#   or multiline string -- is out of scope and treated as malformed
#   rather than silently misread.
_conclude_toml_valid_value() {
  local v=$1
  [[ $v == "true" || $v == "false" ]] && return 0
  [[ $v =~ $_CONCLUDE_TOML_NUM_RE ]] && return 0
  if ((${#v} >= 2)); then
    local quote=${v:0:1} last=${v: -1}
    [[ ($quote == '"' || $quote == "'") && $quote == "$last" ]] && return 0
  fi
  return 1
}

# _conclude_toml_unquote TEXT
#   TEXT must already have passed _conclude_toml_valid_value. A quoted
#   string loses its surrounding quotes (double-quoted ones also decode
#   backslash escapes, the same handful as .env's -- see
#   conclude_decode_backslash_escapes); true/false/a number pass through
#   unchanged, since that's already the text form conclude_cast expects.
_conclude_toml_unquote() {
  local LC_CTYPE=C.UTF-8
  local v=$1
  if ((${#v} >= 2)); then
    local quote=${v:0:1} last=${v: -1}
    if [[ $quote == "$last" ]]; then
      if [[ $quote == '"' ]]; then
        v=${v:1:${#v}-2}
        local _decoded
        _decoded=$(conclude_decode_backslash_escapes "$v"; printf '\x01')
        printf '%s' "${_decoded%$'\x01'}"
        return
      elif [[ $quote == "'" ]]; then
        printf '%s' "${v:1:${#v}-2}"
        return
      fi
    fi
  fi
  printf '%s' "$v"
}

# conclude_toml_has_table TEXT TABLE_PATH
#   Whether TEXT has a `[TABLE_PATH]` header naming exactly TABLE_PATH
#   (a dot-joined string, e.g. "myapp.deck") -- used by the shorthand
#   table lookup below. Does not validate the rest of the file.
conclude_toml_has_table() {
  local text=$1 target=$2 raw line
  local -a lines
  mapfile -t lines <<<"$text"
  for raw in "${lines[@]}"; do
    line=$(_conclude_trim "$raw")
    if [[ $line =~ $_CONCLUDE_TOML_HEADER_RE ]] && [[ ${BASH_REMATCH[1]} == "$target" ]]; then
      return 0
    fi
  done
  return 1
}

# conclude_read_config_table TEXT OUTVAR TABLE1 [TABLE2]
#   Reads TABLE1 (e.g. "myapp") as the base, and -- if TABLE2 is given --
#   overlays "TABLE1.TABLE2" (e.g. "myapp.deck") on top of it key by key,
#   so a child table's keys override the parent's but a key the child
#   doesn't mention still comes from the parent. Populates OUTVAR (an
#   associative array of raw, still-uncast TOML value text) and returns
#   0. Returns 1 -- OUTVAR's contents are then undefined, don't use them
#   -- if TEXT has a malformed line *anywhere*, even outside the tables
#   being read: a genuinely broken TOML document fails to parse before
#   any specific table is ever reached.
conclude_read_config_table() {
  local text=$1 outvar=$2 table1=$3 table2=${4-}
  local -n _cd_table_out=$outvar
  _cd_table_out=()
  local -A _base=() _child=()
  local target2=""
  [[ -n $table2 ]] && target2="${table1}.${table2}"

  local raw line current="" key value_text
  local -a lines
  mapfile -t lines <<<"$text"
  for raw in "${lines[@]}"; do
    line=$(_conclude_trim "$raw")
    [[ -z $line ]] && continue
    [[ $line == '#'* ]] && continue
    if [[ $line =~ $_CONCLUDE_TOML_HEADER_RE ]]; then
      current=${BASH_REMATCH[1]}
      continue
    fi
    if [[ $line =~ $_CONCLUDE_TOML_KV_RE ]]; then
      key=${BASH_REMATCH[1]}
      value_text=$(_conclude_trim "${BASH_REMATCH[2]}")
      if ! _conclude_toml_valid_value "$value_text"; then
        printf 'conclude: malformed TOML value for %q: %q\n' "$key" "$value_text" >&2
        return 1
      fi
      if [[ $current == "$table1" ]]; then
        _base[$key]=$(_conclude_toml_unquote "$value_text")
      elif [[ -n $target2 && $current == "$target2" ]]; then
        _child[$key]=$(_conclude_toml_unquote "$value_text")
      fi
      continue
    fi
    printf 'conclude: malformed TOML line: %q\n' "$raw" >&2
    return 1
  done

  local k
  for k in "${!_base[@]}"; do _cd_table_out[$k]=${_base[$k]}; done
  for k in "${!_child[@]}"; do _cd_table_out[$k]=${_child[$k]}; done
  return 0
}

# conclude_cast_table_values TYPESVAR RAWVAR OUTVAR
#   TYPESVAR: an associative array of key -> declared type (from an
#   app's `conclude_define` calls). RAWVAR: raw TOML value text, as from
#   conclude_read_config_table. Populates OUTVAR with only the keys
#   TYPESVAR actually declares, cast to their declared type -- an
#   undeclared key in the file is silently ignored (spec: "keys no
#   setting declares are ignored"), and an unset (empty/absent) cast
#   result is left out of OUTVAR entirely rather than stored as empty.
#   Returns 1 if a declared key's value fails to cast.
conclude_cast_table_values() {
  local typesvar=$1 rawvar=$2 outvar=$3
  local -n _cd_types=$typesvar
  local -n _cd_raw=$rawvar
  local -n _cd_cast_out=$outvar
  _cd_cast_out=()
  local key type value status
  for key in "${!_cd_raw[@]}"; do
    [[ -v _cd_types[$key] ]] || continue
    type=${_cd_types[$key]}
    value=$(conclude_cast "$type" "${_cd_raw[$key]}") && status=0 || status=$?
    if [[ $status -eq 1 ]]; then
      printf 'conclude: config key %q: %s\n' "$key" "$value" >&2
      return 1
    elif [[ $status -eq 0 ]]; then
      _cd_cast_out[$key]=$value
    fi
    # status 2 (unset) -> leave the key out of OUTVAR entirely.
  done
  return 0
}

# conclude_glob_match NAME PATTERN -- a plain shell glob match (used for
# the sibling-file pattern, e.g. ".config.*.toml").
conclude_glob_match() {
  # shellcheck disable=SC2053 # the unquoted right-hand side *is* the glob
  [[ $1 == $2 ]]
}

# conclude_parse_table_selection VALUE DEFAULT_TABLE OUTVAR
#   Turns an explicit "PARENT" or "PARENT.CHILD" selection string into a
#   1- or 2-element table path in OUTVAR (an indexed array); an empty or
#   unset VALUE means DEFAULT_TABLE. Errors (returns 1) on a leading,
#   trailing, or doubled dot, or on three or more levels -- this parser
#   only ever supports the two-level [app]/[app.child] shape.
conclude_parse_table_selection() {
  local value=$1 default_table=$2 outvar=$3
  local -n _cd_sel_out=$outvar
  if [[ -z $value ]]; then
    _cd_sel_out=("$default_table")
    return 0
  fi
  if [[ $value == .* || $value == *. || $value == *..* ]]; then
    printf 'conclude: invalid table selection %q\n' "$value" >&2
    return 1
  fi
  local -a parts
  IFS='.' read -ra parts <<<"$value"
  if ((${#parts[@]} > 2)); then
    printf 'conclude: invalid table selection %q (at most two levels)\n' "$value" >&2
    return 1
  fi
  _cd_sel_out=("${parts[@]}")
  return 0
}

# conclude_resolve_table_selection CONFIG_VALUE SHORTHAND DEFAULT_TABLE OUTVAR [-- TEXT...]
#   The full table-selection logic: an explicit CONFIG_VALUE always wins
#   outright (parsed as above). Otherwise, if SHORTHAND is given, the
#   TEXT... arguments (every applicable config file's raw text, in any
#   order -- already filtered for whether siblings are in play) are
#   checked for a top-level `[SHORTHAND]` table first, then for a nested
#   `[DEFAULT_TABLE.SHORTHAND]` one; the first kind found in *any* of
#   them wins. Falls back to DEFAULT_TABLE alone if nothing matches.
conclude_resolve_table_selection() {
  local config_value=$1 shorthand=$2 default_table=$3 outvar=$4
  shift 4
  [[ ${1-} == "--" ]] && shift
  local -n _cd_res_out=$outvar

  if [[ -n $config_value ]]; then
    conclude_parse_table_selection "$config_value" "$default_table" "$outvar"
    return $?
  fi

  if [[ -n $shorthand ]]; then
    local text
    for text in "$@"; do
      if conclude_toml_has_table "$text" "$shorthand"; then
        _cd_res_out=("$shorthand")
        return 0
      fi
    done
    for text in "$@"; do
      if conclude_toml_has_table "$text" "${default_table}.${shorthand}"; then
        _cd_res_out=("$default_table" "$shorthand")
        return 0
      fi
    done
  fi

  _cd_res_out=("$default_table")
  return 0
}

# conclude_load_config_file PATH OUTVAR TABLE1 [TABLE2]
#   Reads PATH from disk and reads TABLE1[.TABLE2] from it, as
#   conclude_read_config_table. Leaves OUTVAR empty (returns 0, not an
#   error) if PATH doesn't exist -- same "missing is normal" convention
#   as conclude_load_dotenv.
conclude_load_config_file() {
  local path=$1 outvar=$2 table1=$3 table2=${4-}
  local -n _cd_file_out=$outvar
  if [[ ! -f $path ]]; then
    _cd_file_out=()
    return 0
  fi
  local text
  text=$(<"$path")
  conclude_read_config_table "$text" "$outvar" "$table1" "$table2"
}

# --- guard (spec/guard.json, spec/gitignore.json) --------------------------
#
# Whether a private local file (the developer-config file, or optionally
# a `.env`) really is private: not switched off, existing, inside a git
# working tree, and ignored by that tree's rules. Checks run in that
# order and the first failure is the reported reason -- this mirrors the
# Python/Node ports' check_guard exactly (same order, same reason
# strings, same {0,off,false,no} kill-switch values, case-insensitive).
#
# Where this module genuinely differs from Python/Node: "inside a git
# working tree" is a plain filesystem walk in pure Bash (look for a
# `.git` file or directory at the target's directory or any ancestor --
# no `git` command involved, since a synthetic or partially-broken .git
# can make real git refuse to run at all, and this check needs to work
# even then). But the actual ignore-rule *matching* -- negation,
# directory patterns swallowing everything beneath them, nested
# .gitignore precedence, `**` -- is handed straight to
# `git check-ignore --no-index` once a root is found, rather than
# reimplemented. See the earlier discussion: that command *is*
# gitignore.json's own oracle, so this is the one port that can match it
# exactly for free instead of approximating it with a pattern-matching
# library the way Python's `pathspec` and Node's `ignore` do.

_CONCLUDE_KILL_SWITCH_VALUES=" 0 off false no "

# conclude_check_guard TARGET [KILL_SWITCH_VAR] ACTIVE_VAR REASON_VAR
#   Never fails -- always returns 0. Sets ACTIVE_VAR to "true"/"false"
#   and REASON_VAR to why not (empty when active).
conclude_check_guard() {
  local target=$1 kill_switch_var=$2 active_var=$3 reason_var=$4
  local -n _cd_guard_active=$active_var
  local -n _cd_guard_reason=$reason_var
  _cd_guard_active=false
  _cd_guard_reason=""

  if [[ -n $kill_switch_var ]]; then
    local raw=${!kill_switch_var-} trimmed
    trimmed=$(_conclude_trim "$raw")
    if [[ $_CONCLUDE_KILL_SWITCH_VALUES == *" ${trimmed,,} "* ]]; then
      _cd_guard_reason="disabled by ${kill_switch_var}=${trimmed}"
      return 0
    fi
  fi

  if [[ ! -f $target ]]; then
    _cd_guard_reason="file not found"
    return 0
  fi

  local absolute dir root=""
  absolute=$(realpath -- "$target")
  dir=$(dirname -- "$absolute")
  while :; do
    if [[ -e "$dir/.git" ]]; then
      root=$dir
      break
    fi
    [[ $dir == / ]] && break
    dir=$(dirname -- "$dir")
  done
  if [[ -z $root ]]; then
    _cd_guard_reason="not inside a git working tree"
    return 0
  fi

  if git -C "$root" check-ignore --no-index --quiet -- "$absolute" 2>/dev/null; then
    _cd_guard_active=true
    return 0
  fi
  _cd_guard_reason="not covered by .gitignore"
  return 0
}

# --- merge / resolve (spec/merge.json, spec/sources.json) ------------------
#
# conclude_init / conclude_define: the app-level state conclude_resolve
# (still a stub -- see below) will eventually read from.

declare -gA _CONCLUDE_DEFAULTS=()
declare -gA _CONCLUDE_TYPES=()
declare -gA _CONCLUDE_APP_NAME=() # keyed by app, value is itself (membership check)

# conclude_init APP
# conclude_init APP -- (re-)initializes APP, clearing any settings a
# previous conclude_init/conclude_define for the same app name declared.
# Re-initializing is deliberate and safe (e.g. re-sourcing this file
# and re-running an app's setup in the same shell) rather than
# accumulating stale declarations from before.
conclude_init() {
  local app=$1
  _CONCLUDE_APP_NAME["$app"]=$app
  _CONCLUDE_ORDER[$app]=""
  local k
  for k in "${!_CONCLUDE_TYPES[@]}"; do
    [[ $k == "$app:"* ]] && unset "_CONCLUDE_TYPES[$k]"
  done
  for k in "${!_CONCLUDE_DEFAULTS[@]}"; do
    [[ $k == "$app:"* ]] && unset "_CONCLUDE_DEFAULTS[$k]"
  done
  return 0
}

# conclude_define APP KEY TYPE [DEFAULT]
#   DEFAULT is genuinely optional -- not just "pass an empty string" --
#   since a setting can have a real empty-string default (see
#   spec/templates.json's "an empty string default") that must render
#   differently from having no default at all. Bash can't tell an
#   omitted argument from an empty one by value, only by $#, so this
#   checks argument *count*: `conclude_define app key str` (3 args) means
#   no default; `conclude_define app key str ""` (4 args, empty) is a
#   real default of "". Declaration order is tracked separately (in
#   _CONCLUDE_ORDER, newline-joined per app) since associative arrays
#   have no defined iteration order but format_env/format_toml/
#   format_cli all render settings in the order they were declared.
declare -gA _CONCLUDE_ORDER=()

conclude_define() {
  local app=$1 key=$2 type=$3
  _CONCLUDE_TYPES["$app:$key"]=$type
  if (($# >= 4)); then
    _CONCLUDE_DEFAULTS["$app:$key"]=$4
  else
    unset "_CONCLUDE_DEFAULTS[$app:$key]"
  fi
  _CONCLUDE_ORDER[$app]+="${key}"$'\n'
}

# _conclude_ordered_keys APP OUTVAR -- declared keys, in declaration order.
_conclude_ordered_keys() {
  local app=$1 outvar=$2
  local -n _cd_ord_out=$outvar
  mapfile -t _cd_ord_out <<<"${_CONCLUDE_ORDER[$app]-}"
  # mapfile leaves one trailing empty element for the final newline.
  if ((${#_cd_ord_out[@]} > 0)) && [[ -z ${_cd_ord_out[-1]} ]]; then
    unset '_cd_ord_out[-1]'
  fi
}
#
# conclude_merge_layers: the actual merge algorithm from spec/merge.json,
# decoupled from where each layer's raw values come from (CLI parsing,
# env vars, a config file, .env, the developer layer -- conclude_resolve
# below is what actually assembles those). Each layer is an associative
# array the *caller* builds; a key's mere presence in one (even set to
# an empty string) means "this layer has an opinion", while a key's
# absence means "no opinion, defer to a lower-priority layer" -- exactly
# mirroring how the Python/Node ports use `None`/`null` for the same
# purpose. That distinction is why this can't just be "loop the layers
# and cast whatever's non-empty": an environment variable explicitly set
# to "" is a real opinion (spec: "an empty environment value is cast,
# not skipped") that can override a lower layer's real value with
# "unset", which is different from the variable never having been set
# at all.
#
# Layers are cast *every time they're visited*, low to high, even a
# layer that a higher one will go on to override -- so a malformed value
# in a layer that ultimately loses still fails the whole resolve (spec:
# "a bad value in a lower layer is still an error"). A raw value that's
# a native list (as a defaults declaration or a config file might
# supply, unlike env/CLI strings) has no bash representation other than
# the same comma-joined convention conclude_cast's `list` type already
# uses -- so, as previously flagged for the config module, whatever
# builds these layer arrays (a real TOML array, one day) is responsible
# for joining it before this point; this function only ever sees strings.

# conclude_merge_layers TYPESVAR OUTVAR LAYER_VAR...
#   TYPESVAR: key -> declared type. LAYER_VAR...: names of associative
#   arrays, lowest priority first (defaults is just the first one).
#   OUTVAR ends up with every key TYPESVAR declares: a plain conclude_cast
#   result for whichever layer won it, or "" if no layer ever set it (a
#   still-unset default, cast or otherwise) -- since a genuine cast
#   result is never itself an empty string (see conclude_cast's
#   contract), "" is an unambiguous stand-in for None/null here.
#   Returns 1 (OUTVAR then undefined) the moment any visited layer's
#   value fails to cast.
conclude_merge_layers() {
  local typesvar=$1 outvar=$2
  shift 2
  local -n _cd_merge_types=$typesvar
  local -n _cd_merge_out=$outvar
  _cd_merge_out=()

  local layer_name key value status
  for layer_name in "$@"; do
    local -n _cd_merge_layer=$layer_name
    for key in "${!_cd_merge_layer[@]}"; do
      [[ -v _cd_merge_types[$key] ]] || continue
      value=$(conclude_cast "${_cd_merge_types[$key]}" "${_cd_merge_layer[$key]}") && status=0 || status=$?
      if [[ $status -eq 1 ]]; then
        printf 'conclude: %q: %s\n' "$key" "$value" >&2
        return 1
      fi
      _cd_merge_out[$key]=$value # status 0 (a value) or 2 (unset -> "")
    done
    unset -n _cd_merge_layer
  done

  for key in "${!_cd_merge_types[@]}"; do
    [[ -v _cd_merge_out[$key] ]] || _cd_merge_out[$key]=""
  done
  return 0
}

declare -gA CONCLUDE=()

# --- the personal control file -----------------------------------------
#
# Bash has no pyproject.toml/package.json for a developer to name their
# own developer-config file in -- so, unlike Python and Node,
# conclude_resolve's developer layer has nothing to discover a path
# from except being told one directly (see --developer-file below). A
# dedicated, per-user file closes that gap: one developer_file setting
# a person can set once for every bash-conclude app on their machine,
# with no project-specific wiring required.
#
# This is deliberately its own small, standalone file -- not read
# through conclude_resolve's own config-file machinery (no system/
# project/env/CLI layering, no app-specific table). It is also,
# deliberately, not yet a cross-language concept: [control.bash] is
# this binding's own section of a file other bindings could one day
# read too, but that's a decision for if and when this proves useful
# beyond Bash, not something to commit the other ports to today.

# _conclude_control_path -- the fixed location of the personal control
# file, respecting XDG_CONFIG_HOME.
_conclude_control_path() {
  printf '%s/conclude/control.toml' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

# conclude_resolve_developer_file PROVIDED_PATH OUTVAR
#   Decides the real developer-config file path once an app has opted
#   into conclude_resolve's developer layer (see --developer-file/
#   --developer-opt-in below). PROVIDED_PATH is the app's own hardcoded
#   choice, or "" if it only opted in without one.
#
#   ~/.config/conclude/control.toml (or $XDG_CONFIG_HOME's equivalent)
#   lets a developer set their own developer_file, under [control] or,
#   more specifically, [control.bash] (which wins if both are set, via
#   the same parent/child overlay conclude_read_config_table already
#   does for an app's own tables). By default that's only a *fallback*
#   for an app with no opinion of its own; setting `override = true`
#   makes the developer's choice win outright, even over an app's
#   explicit --developer-file PATH. override never matters if the app
#   never opted in at all -- it overrides which file is read, not
#   whether the guarded-developer-file mechanism runs in the first
#   place, so a personal dotfile can't make a script that never asked
#   for this start reading one.
#
#   Precedence: control's path (if override=true) > PROVIDED_PATH (if
#   given) > control's path (as a fallback) > ".developer.toml".
#   Never fails outright on a bad control file -- falls back to
#   PROVIDED_PATH (or the default) and reports the problem on stderr,
#   since a typo in a personal dotfile shouldn't be able to break
#   somebody else's script.
conclude_resolve_developer_file() {
  local provided_path=$1 outvar=$2
  local -n _cd_devfile_out=$outvar

  local control_developer="" control_override=false control_path
  control_path=$(_conclude_control_path)
  if [[ -f $control_path ]]; then
    local -A control_raw=() control_cast=()
    local -A control_types=([developer_file]=str [override]=bool)
    if conclude_load_config_file "$control_path" control_raw control bash &&
      conclude_cast_table_values control_types control_raw control_cast; then
      control_developer=${control_cast[developer_file]-}
      control_override=${control_cast[override]-false}
    else
      printf 'conclude: ignoring unreadable control file %q\n' "$control_path" >&2
    fi
  fi

  if [[ -n $control_developer && $control_override == true ]]; then
    _cd_devfile_out=$control_developer
  elif [[ -n $provided_path ]]; then
    _cd_devfile_out=$provided_path
  elif [[ -n $control_developer ]]; then
    _cd_devfile_out=$control_developer
  else
    _cd_devfile_out=".developer.toml"
  fi
  return 0
}

# conclude_resolve APP [options] -- ARGS...
#   Wires together everything above into the real precedence chain:
#     defaults < user config < project config(+siblings) < env
#       < developer config < CLI
#   The developer layer is opt-in via --developer-file/--developer-opt-in
#   (below): unlike Python/Node it doesn't discover the file through a
#   pyproject.toml `tool.conclude.developer` table -- that's three TOML
#   levels deep, past what conclude_read_config_table supports, and the
#   spec deliberately leaves each binding to name the file its own way
#   (spec/sources.json: "the adapter writes its ecosystem's manifest").
#   A personal ~/.config/conclude/control.toml can supply or override the
#   path instead -- see conclude_resolve_developer_file above.
#   Still not wired in, all off by default in Python too: the
#   system-wide config file and the .env fallback.
#
#   Options (all optional, before the literal "--"):
#     --user-config PATH     override $XDG_CONFIG_HOME/APP/config.toml
#                             (or ~/.config/APP/config.toml)
#     --project-config PATH  override ./.config.toml
#     --no-siblings          don't merge .config.*.toml next to it
#     --developer-file PATH  opt into the developer layer with PATH as
#                             this app's own choice (conclude_resolve_
#                             developer_file may still override or
#                             supply it -- see above); read from
#                             whichever path wins, only while it's
#                             guarded (existing, inside a
#                             git tree, gitignored, and MYAPP_DEVELOPER_
#                             CONFIG not set to off/0/false/no)
#     --developer-opt-in     opt into the developer layer with no path of
#                             this app's own -- entirely up to
#                             conclude_resolve_developer_file (a personal
#                             control.toml, or else ".developer.toml")
#     --table PART           (repeatable) explicit table path, as
#                             conclude_resolve_table_selection; default
#                             table is APP
#     --help-flag             opt into recognizing -h/--help anywhere in
#                             ARGS: print conclude_format_help's text and
#                             return 2, before touching any layer. Off
#                             unless given, so a caller that wants -h to
#                             mean something else (or to build its own
#                             help text) is never surprised by this.
#     --help-prog/--help-usage/--help-before/--help-after/
#     --help-sources-args ARGS...
#                             forwarded to conclude_format_help's
#                             --prog/--usage/--before/--after/
#                             --sources-args when --help-flag triggers;
#                             see that function to build help text by
#                             hand instead, e.g. to word it differently
#                             or show it somewhere other than stdout
#
#   On success, populates the CONCLUDE associative array (CONCLUDE[key]
#   for every declared key, "" for unset/None) and exports
#   ${APP^^}_${KEY^^} for each, then returns 0. Returns 1 (nothing
#   exported, CONCLUDE left as it was) the moment any layer's value
#   fails to cast, or a CLI argument doesn't match a declared flag.
#   Returns 2 if --help-flag was given and -h/--help was seen: help was
#   printed, nothing was resolved, and the caller should exit 0 having
#   done no other work -- not treat it as an error.
conclude_resolve() {
  local app=$1
  shift
  local user_config="${XDG_CONFIG_HOME:-$HOME/.config}/${app}/config.toml"
  local project_config="./.config.toml"
  local aux_pattern=".config.*.toml"
  local developer_file="" developer_opt_in=0
  local -a table_parts=()
  local help_flag=0 help_prog="" help_usage="[options]" help_before="" help_after=""
  local -a help_sources_args=()

  while (($#)); do
    case $1 in
      --help-flag)
        help_flag=1
        shift
        ;;
      --help-prog)
        help_prog=$2
        shift 2
        ;;
      --help-usage)
        help_usage=$2
        shift 2
        ;;
      --help-before)
        help_before=$2
        shift 2
        ;;
      --help-after)
        help_after=$2
        shift 2
        ;;
      --help-sources-args)
        # Consumes up to (not including) the next literal "--", so the
        # real ARGS-terminating "--" this whole option loop is looking
        # for is never swallowed, however many tokens describe_sources'
        # own options take.
        shift
        help_sources_args=()
        while (($#)) && [[ $1 != "--" ]]; do
          help_sources_args+=("$1")
          shift
        done
        ;;
      --user-config)
        user_config=$2
        shift 2
        ;;
      --project-config)
        project_config=$2
        shift 2
        ;;
      --no-siblings)
        aux_pattern=""
        shift
        ;;
      --developer-file)
        developer_file=$2
        developer_opt_in=1
        shift 2
        ;;
      --developer-opt-in)
        developer_opt_in=1
        shift
        ;;
      --table)
        table_parts+=("$2")
        shift 2
        ;;
      --)
        shift
        break
        ;;
      *)
        printf 'conclude: unrecognized conclude_resolve option %q\n' "$1" >&2
        return 1
        ;;
    esac
  done

  if ((help_flag)); then
    local help_seen=0 help_arg
    for help_arg in "$@"; do
      if [[ $help_arg == "-h" || $help_arg == "--help" ]]; then
        help_seen=1
        break
      fi
    done
    if ((help_seen)); then
      local -a help_opts=(--usage "$help_usage")
      [[ -n $help_prog ]] && help_opts+=(--prog "$help_prog")
      [[ -n $help_before ]] && help_opts+=(--before "$help_before")
      [[ -n $help_after ]] && help_opts+=(--after "$help_after")
      if ((${#help_sources_args[@]} > 0)); then
        help_opts+=(--sources-args "${help_sources_args[@]}")
      fi
      local help_text
      conclude_format_help "$app" help_text "${help_opts[@]}" || return 1
      printf '%s\n' "$help_text"
      return 2
    fi
  fi

  local -a keys
  _conclude_ordered_keys "$app" keys

  # --- CLI layer: one pass over the remaining args -----------------------
  local -A cli=()
  local -A flag_to_key=()
  local key flag
  for key in "${keys[@]}"; do
    flag_to_key[$(conclude_cli_flag_name "$key")]=$key
  done
  local arg name val has_val
  while (($#)); do
    arg=$1
    if [[ $arg == *=* ]]; then
      name=${arg%%=*}
      val=${arg#*=}
      has_val=1
    else
      name=$arg
      has_val=0
    fi
    if [[ ! -v flag_to_key[$name] ]]; then
      printf 'conclude: unrecognized argument %q\n' "$arg" >&2
      return 1
    fi
    key=${flag_to_key[$name]}
    if [[ ${_CONCLUDE_TYPES["$app:$key"]} == bool ]]; then
      if ((has_val)); then
        printf 'conclude: %q takes no value (a bare flag turns it on; there is no way to turn a bool off)\n' "$name" >&2
        return 1
      fi
      cli[$key]=true
      shift
    elif ((has_val)); then
      cli[$key]=$val
      shift
    else
      if (($# < 2)); then
        printf 'conclude: %q needs a value\n' "$name" >&2
        return 1
      fi
      cli[$key]=$2
      shift 2
    fi
  done

  # --- env layer: real env vars, falling back to nothing (no .env yet) ---
  local -A env=()
  local envname
  for key in "${keys[@]}"; do
    envname=$(conclude_env_var_name "$app" "$key")
    [[ -v $envname ]] && env[$key]=${!envname}
  done

  # --- config layer: user < project(+siblings), merged into one raw map --
  local -a resolved_table
  if ((${#table_parts[@]} > 2)); then
    printf 'conclude: --table takes at most two levels, got %d\n' "${#table_parts[@]}" >&2
    return 1
  elif ((${#table_parts[@]} > 0)); then
    resolved_table=("${table_parts[@]}")
  else
    conclude_resolve_table_selection "" "" "$app" resolved_table || return 1
  fi
  local table1=${resolved_table[0]} table2=${resolved_table[1]-}

  local -A config=() layer_raw=()
  if [[ -f $user_config ]]; then
    conclude_load_config_file "$user_config" layer_raw "$table1" "$table2" || return 1
    for key in "${!layer_raw[@]}"; do config[$key]=${layer_raw[$key]}; done
  fi
  if [[ -f $project_config ]]; then
    conclude_load_config_file "$project_config" layer_raw "$table1" "$table2" || return 1
    for key in "${!layer_raw[@]}"; do config[$key]=${layer_raw[$key]}; done
    if [[ -n $aux_pattern ]]; then
      local -a siblings=()
      local dir base
      dir=$(dirname -- "$project_config")
      while IFS= read -r base; do
        conclude_glob_match "$base" "$aux_pattern" && siblings+=("$dir/$base")
      done < <(cd "$dir" 2>/dev/null && shopt -s dotglob nullglob && printf '%s\n' *)
      # Byte order (LC_ALL=C), like Python's sorted() and JS's default
      # sort: a locale's collation would ignore the leading dots and could
      # reorder siblings, silently changing which one wins.
      if ((${#siblings[@]} > 1)); then
        mapfile -t siblings < <(printf '%s\n' "${siblings[@]}" | LC_ALL=C sort)
      fi
      local sib
      for sib in "${siblings[@]}"; do
        [[ -f $sib ]] || continue
        conclude_load_config_file "$sib" layer_raw "$table1" "$table2" || return 1
        for key in "${!layer_raw[@]}"; do config[$key]=${layer_raw[$key]}; done
      done
    fi
  fi

  # --- developer layer: a private, gitignored file (see conclude_check_guard)
  # that only loads when it's active -- silently empty otherwise, since
  # "inactive" is a normal state (the kill switch, a fresh clone with no
  # file yet), not an error. A .toml file is read like any config file; any
  # other name is a dotenv file, whose NAME=value pairs map back to
  # settings through the same env-var naming the env layer uses.
  local -A developer=()
  if ((developer_opt_in)); then
    local resolved_developer_file
    conclude_resolve_developer_file "$developer_file" resolved_developer_file
    local dev_active dev_reason dev_kill
    dev_kill=$(conclude_env_var_name "$app" "developer_config")
    conclude_check_guard "$resolved_developer_file" "$dev_kill" dev_active dev_reason
    if [[ $dev_active == true ]]; then
      if [[ ${resolved_developer_file,,} == *.toml ]]; then
        conclude_load_config_file "$resolved_developer_file" layer_raw "$table1" "$table2" || return 1
        for key in "${!layer_raw[@]}"; do developer[$key]=${layer_raw[$key]}; done
      else
        local -A dev_dotenv=()
        conclude_load_dotenv "$resolved_developer_file" dev_dotenv
        for key in "${keys[@]}"; do
          envname=$(conclude_env_var_name "$app" "$key")
          [[ -v dev_dotenv[$envname] ]] && developer[$key]=${dev_dotenv[$envname]}
        done
      fi
    fi
  fi

  # --- defaults layer -----------------------------------------------------
  local -A defaults=() types=()
  for key in "${keys[@]}"; do
    [[ -v _CONCLUDE_DEFAULTS["$app:$key"] ]] && defaults[$key]=${_CONCLUDE_DEFAULTS["$app:$key"]}
    types[$key]=${_CONCLUDE_TYPES["$app:$key"]}
  done

  local -A result=()
  conclude_merge_layers types result defaults config env developer cli || return 1

  CONCLUDE=()
  for key in "${keys[@]}"; do
    CONCLUDE[$key]=${result[$key]-}
    export "$(conclude_env_var_name "$app" "$key")=${result[$key]-}"
  done
  return 0
}

# --- introspection ----------------------------------------------------------
#
# Which config sources an app checks at all -- meant for a --help epilog,
# not for describing one resolved run (that's format_invocation's job).
# Never fails: every function here reports a state, it doesn't raise.

# conclude_dotenv_status PATH REQUIRE_GITIGNORED OUTVAR
#   PATH="" means disabled. Without REQUIRE_GITIGNORED ("true"/"false"),
#   a configured path is unconditionally active (matches conclude_resolve
#   not being able to check it exists ahead of time either -- .env is
#   read if and when it's there). With it, PATH must also pass
#   conclude_check_guard (no kill switch -- .env has none, only the
#   developer file does).
conclude_dotenv_status() {
  local path=$1 require_gitignored=$2 outvar=$3
  local -n _cd_dstat=$outvar
  if [[ -z $path ]]; then
    _cd_dstat="disabled"
    return 0
  fi
  if [[ $require_gitignored != true ]]; then
    _cd_dstat=$path
    return 0
  fi
  local active reason
  conclude_check_guard "$path" "" active reason
  if [[ $active == true ]]; then
    _cd_dstat="${path} -- active (gitignored)"
  else
    _cd_dstat="${path} -- inactive (${reason})"
  fi
  return 0
}

# conclude_developer_status APP FILE_PATH OPTED_IN OUTVAR
#   OPTED_IN ("true"/"false"): whether the app turned this layer on at
#   all. FILE_PATH="" with OPTED_IN=true means opted in but no file is
#   configured yet (the exact reason text for *why* is left to whatever
#   names the file -- there's no shared convention to match here, unlike
#   every other case, which the spec is explicit about). A non-empty
#   FILE_PATH is guarded exactly like the .env file, except this one DOES
#   have a kill switch: `<APP>_DEVELOPER_CONFIG` set to
#   off/0/false/no (case-insensitively) deactivates it.
conclude_developer_status() {
  local app=$1 file_path=$2 opted_in=$3 outvar=$4
  local -n _cd_devstat=$outvar
  if [[ $opted_in != true ]]; then
    _cd_devstat="not opted in"
    return 0
  fi
  if [[ -z $file_path ]]; then
    _cd_devstat="not configured"
    return 0
  fi
  local kill_switch_var active reason
  kill_switch_var=$(conclude_env_var_name "$app" "developer_config")
  conclude_check_guard "$file_path" "$kill_switch_var" active reason
  if [[ $active == true ]]; then
    _cd_devstat="${file_path} -- configured, active"
  else
    _cd_devstat="${file_path} -- configured, inactive (${reason})"
  fi
  return 0
}

# conclude_describe_sources APP OUTVAR [options...]
#   --system PATH | --user PATH | --project PATH | --aux PATTERN |
#   --dotenv PATH | --dotenv-require-gitignored |
#   --developer-opted-in | --developer-file PATH
#   Every path option left out renders as "disabled"; --aux only shows
#   up next to a --project path (dropping it, like conclude_resolve's
#   --no-siblings, just means no sibling search). --developer-file
#   implies --developer-opted-in; give --developer-opted-in alone for
#   "opted in, not configured yet".
conclude_describe_sources() {
  local app=$1 outvar=$2
  shift 2
  local -n _cd_desc_out=$outvar
  local system="" user="" project="" aux="" dotenv_path="" dotenv_guarded=false
  local developer_opted_in=false developer_file=""

  while (($#)); do
    case $1 in
      --system)
        system=$2
        shift 2
        ;;
      --user)
        user=$2
        shift 2
        ;;
      --project)
        project=$2
        shift 2
        ;;
      --aux)
        aux=$2
        shift 2
        ;;
      --dotenv)
        dotenv_path=$2
        shift 2
        ;;
      --dotenv-require-gitignored)
        dotenv_guarded=true
        shift
        ;;
      --developer-opted-in)
        developer_opted_in=true
        shift
        ;;
      --developer-file)
        developer_file=$2
        developer_opted_in=true
        shift 2
        ;;
      *)
        printf 'conclude: unrecognized option %q\n' "$1" >&2
        return 1
        ;;
    esac
  done

  local project_text=disabled
  if [[ -n $project ]]; then
    project_text=$project
    if [[ -n $aux ]]; then
      project_text+=", $(dirname -- "$project")/${aux}"
    fi
  fi

  local dotenv_text developer_text
  conclude_dotenv_status "$dotenv_path" "$dotenv_guarded" dotenv_text
  conclude_developer_status "$app" "$developer_file" "$developer_opted_in" developer_text

  local -a labels=("system config" "user config" "project config" ".env file" "developer config")
  local -a values=("${system:-disabled}" "${user:-disabled}" "$project_text" "$dotenv_text" "$developer_text")

  local width=0 label
  for label in "${labels[@]}"; do ((${#label} > width)) && width=${#label}; done

  local -a lines=("config sources:")
  local i padded
  for ((i = 0; i < ${#labels[@]}; i++)); do
    printf -v padded '%-*s' "$width" "${labels[$i]}"
    lines+=("  ${padded}  ${values[$i]}")
  done
  _cd_desc_out=$(
    IFS=$'\n'
    printf '%s' "${lines[*]}"
  )
  return 0
}

# --- templates / invocation --------------------------------------------------
#
# Rendering a setting's default (format_env/format_toml/format_cli) or a
# whole resolved run (format_invocation) as text -- the building blocks
# for a ready-to-fill-in config template or a reproducible command
# line, generated straight from an app's declared settings rather than
# hand-written and left to drift out of sync.
#
# format_env/format_toml/format_cli take options as repeatable flags
# rather than a dict, since that's the natural Bash shape:
#   conclude_format_env APP OUTVAR [--skip k1,k2,...] \
#     [--default KEY=VALUE]... [--env-var KEY=NAME]...
#   conclude_format_toml APP OUTVAR [--no-header] [--table PART]... \
#     [--skip k1,k2,...] [--default KEY=VALUE]...
#   conclude_format_cli APP OUTVAR [--skip k1,k2,...] \
#     [--default KEY=VALUE]... [--metavar KEY=NAME[,NAME2,...]]...
# --table may repeat to build a multi-level path (["myapp","deck"] in
# the other ports is `--table myapp --table deck` here); with it never
# given, the path defaults to just the app name. --no-header covers
# both "no header wanted" and "an empty table path" from the other
# ports' `table=[]`, since both just mean "print no [header] line" --
# there's no separate bash equivalent of passing an empty sequence.
#
# All of this works purely off what conclude_define already recorded
# (_CONCLUDE_TYPES / _CONCLUDE_DEFAULTS / _CONCLUDE_ORDER) -- it never
# needs a resolved run, unlike format_invocation below.

# _conclude_env_bare TEXT -- true if TEXT needs no quoting at all in a
# .env value: word characters (Unicode-aware, so "café" stays bare) plus
# a handful of punctuation marks unremarkable in every .env dialect.
_conclude_env_bare() {
  local LC_CTYPE=C.UTF-8
  local re='^[[:alnum:]_./:@%+,-]*$'
  [[ $1 =~ $re ]]
}

# conclude_format_env_value TEXT -- TEXT as the right-hand side of a
# NAME=value .env line that conclude_load_dotenv reads back as exactly
# TEXT: bare when possible, single-quoted when it has anything else,
# double-quoted with backslash escapes only when it has a single quote
# or a newline/tab/CR (which single quotes can't carry).
conclude_format_env_value() {
  local LC_CTYPE=C.UTF-8
  local text=$1
  if _conclude_env_bare "$text"; then
    printf '%s' "$text"
    return
  fi
  if [[ $text != *"'"* && $text != *$'\n'* && $text != *$'\t'* && $text != *$'\r'* ]]; then
    printf "'%s'" "$text"
    return
  fi
  local out='' i len ch
  len=${#text}
  for ((i = 0; i < len; i++)); do
    ch=${text:i:1}
    # shellcheck disable=SC1003 # a lone backslash in quotes is the point
    case $ch in
      '\') out+='\\' ;;
      '"') out+='\"' ;;
      $'\n') out+='\n' ;;
      $'\t') out+='\t' ;;
      $'\r') out+='\r' ;;
      *) out+=$ch ;;
    esac
  done
  printf '"%s"' "$out"
}

# _conclude_toml_string TEXT -- TEXT as a double-quoted TOML basic
# string: backslash, double quote, \n \t \r escaped by name, and every
# other control character (plus DEL) as \uXXXX -- TOML forbids them
# unescaped in a basic string.
_conclude_toml_string() {
  local LC_CTYPE=C.UTF-8
  local text=$1 out='' i len ch code
  len=${#text}
  for ((i = 0; i < len; i++)); do
    ch=${text:i:1}
    # shellcheck disable=SC1003 # a lone backslash in quotes is the point
    case $ch in
      '\') out+='\\' ;;
      '"') out+='\"' ;;
      $'\n') out+='\n' ;;
      $'\t') out+='\t' ;;
      $'\r') out+='\r' ;;
      *)
        if [[ $ch =~ [[:cntrl:]] ]]; then
          printf -v code '%04X' "'$ch"
          out+="\\u${code}"
        else
          out+=$ch
        fi
        ;;
    esac
  done
  printf '"%s"' "$out"
}

# _conclude_toml_key TEXT -- bare if that's valid TOML key syntax
# (letters, digits, "_"/"-" only, non-empty), quoted otherwise.
_conclude_toml_key() {
  local LC_CTYPE=C.UTF-8
  if [[ $1 =~ ^[A-Za-z0-9_-]+$ ]]; then
    printf '%s' "$1"
  else
    _conclude_toml_string "$1"
  fi
}

# _conclude_toml_render_value TYPE TEXT -- TEXT (conclude_cast's
# canonical form for TYPE) as a native TOML value: true/false and
# numbers as-is, a list as a real ["a", "b"] array (re-split on the
# same comma convention conclude_cast list uses), anything else quoted.
_conclude_toml_render_value() {
  local type=$1 text=$2
  case $type in
    bool | int | float)
      printf '%s' "$text"
      ;;
    list)
      local -a items=()
      [[ -n $text ]] && mapfile -t items <<<"${text//,/$'\n'}"
      local out='[' first=1 item
      for item in "${items[@]}"; do
        [[ $first -eq 1 ]] || out+=', '
        out+=$(_conclude_toml_string "$item")
        first=0
      done
      printf '%s]' "$out"
      ;;
    *)
      _conclude_toml_string "$text"
      ;;
  esac
}

# _conclude_template_opts -- shared option parser for format_env/toml/cli.
# Populates (in the caller's scope): skip_set (assoc, key->1),
# default_overrides (assoc, key->value), plus whatever the specific
# caller also declared (env_var_overrides / metavar_overrides /
# table_parts / no_header). Consumes "$@" up to the first unrecognized
# argument (there shouldn't be one).
_conclude_parse_template_opts() {
  while (($#)); do
    case $1 in
      --skip)
        local k
        IFS=',' read -ra _cd_skip_keys <<<"$2"
        for k in "${_cd_skip_keys[@]}"; do skip_set[$k]=1; done
        shift 2
        ;;
      --default)
        default_overrides[${2%%=*}]=${2#*=}
        shift 2
        ;;
      --env-var)
        env_var_overrides[${2%%=*}]=${2#*=}
        shift 2
        ;;
      --metavar)
        metavar_overrides[${2%%=*}]=${2#*=}
        shift 2
        ;;
      --table)
        table_parts+=("$2")
        shift 2
        ;;
      --no-header)
        no_header=1
        shift
        ;;
      *)
        printf 'conclude: unrecognized option %q\n' "$1" >&2
        return 1
        ;;
    esac
  done
  return 0
}

# _conclude_effective_default APP KEY -- DEFAULT_OVERRIDES_VAR
#   Prints the text to treat as KEY's default: an override if given,
#   else the declared default, else nothing (and returns 1) if KEY has
#   no default at all -- the same "no default" state conclude_define's
#   optional 4th argument records.
_conclude_effective_default() {
  local app=$1 key=$2 overridesvar=$3
  local -n _cd_ov=$overridesvar
  if [[ -v _cd_ov[$key] ]]; then
    printf '%s' "${_cd_ov[$key]}"
    return 0
  fi
  if [[ -v _CONCLUDE_DEFAULTS["$app:$key"] ]]; then
    printf '%s' "${_CONCLUDE_DEFAULTS[$app:$key]}"
    return 0
  fi
  return 1
}

# conclude_format_env APP OUTVAR [options...] -- see the section header.
conclude_format_env() {
  local app=$1 outvar=$2
  shift 2
  local -n _cd_env_out=$outvar
  local -A skip_set=() default_overrides=() env_var_overrides=()
  _conclude_parse_template_opts "$@" || return 1

  local -a keys
  _conclude_ordered_keys "$app" keys
  local lines=() key name default_text
  for key in "${keys[@]}"; do
    [[ -v skip_set[$key] ]] && continue
    name=${env_var_overrides[$key]-$(conclude_env_var_name "$app" "$key")}
    if default_text=$(_conclude_effective_default "$app" "$key" default_overrides); then
      lines+=("${name}=$(conclude_format_env_value "$default_text")")
    else
      lines+=("# ${name}=")
    fi
  done
  _cd_env_out=$(
    IFS=$'\n'
    printf '%s' "${lines[*]-}"
  )
  return 0
}

# conclude_format_toml APP OUTVAR [options...] -- see the section header.
conclude_format_toml() {
  local app=$1 outvar=$2
  shift 2
  local -n _cd_toml_out=$outvar
  local -A skip_set=() default_overrides=()
  local -a table_parts=()
  local no_header=0
  _conclude_parse_template_opts "$@" || return 1

  local -a lines=()
  if ((no_header == 0)); then
    local -a path=("${table_parts[@]}")
    ((${#path[@]} == 0)) && path=("$app")
    local part header='[' first=1
    for part in "${path[@]}"; do
      [[ $first -eq 1 ]] || header+='.'
      header+=$(_conclude_toml_key "$part")
      first=0
    done
    lines+=("${header}]")
  fi

  local -a keys
  _conclude_ordered_keys "$app" keys
  local key name type default_text
  for key in "${keys[@]}"; do
    [[ -v skip_set[$key] ]] && continue
    name=$(_conclude_toml_key "$(conclude_config_key_name "$key")")
    type=${_CONCLUDE_TYPES["$app:$key"]}
    if default_text=$(_conclude_effective_default "$app" "$key" default_overrides); then
      lines+=("${name} = $(_conclude_toml_render_value "$type" "$default_text")")
    else
      lines+=("# ${name} =")
    fi
  done
  _cd_toml_out=$(
    IFS=$'\n'
    printf '%s' "${lines[*]-}"
  )
  return 0
}

# conclude_format_cli APP OUTVAR [options...] -- see the section header.
conclude_format_cli() {
  local app=$1 outvar=$2
  shift 2
  local -n _cd_cli_out=$outvar
  local -A skip_set=() default_overrides=() metavar_overrides=()
  _conclude_parse_template_opts "$@" || return 1

  local -a keys
  _conclude_ordered_keys "$app" keys
  local -a flags=() texts=()
  local key type flag default_text text
  for key in "${keys[@]}"; do
    [[ -v skip_set[$key] ]] && continue
    type=${_CONCLUDE_TYPES["$app:$key"]}
    flag=$(conclude_cli_flag_name "$key")
    if [[ $type != bool ]]; then
      local -a metavars=()
      if [[ -v metavar_overrides[$key] ]]; then
        IFS=',' read -ra metavars <<<"${metavar_overrides[$key]}"
      else
        metavars=("${key^^}")
      fi
      local mv
      for mv in "${metavars[@]}"; do flag+=" <${mv}>"; done
    fi
    if default_text=$(_conclude_effective_default "$app" "$key" default_overrides); then
      if [[ $type == list && -z $default_text ]]; then
        text='""'
      elif [[ -z $default_text ]]; then
        text='""'
      else
        text=$default_text
      fi
    else
      text=none
    fi
    flags+=("$flag")
    texts+=("$text")
  done

  local width=0 i
  for flag in "${flags[@]}"; do ((${#flag} > width)) && width=${#flag}; done
  local -a lines=()
  for ((i = 0; i < ${#flags[@]}; i++)); do
    printf -v flag '%-*s' "$width" "${flags[$i]}"
    lines+=("${flag} (default: ${texts[$i]})")
  done
  _cd_cli_out=$(
    IFS=$'\n'
    printf '%s' "${lines[*]-}"
  )
  return 0
}

# conclude_format_help APP OUTVAR [options] -- a full --help/-h screen,
# built from what's already declared: usage line, every setting from
# conclude_format_cli, and the config sources from conclude_describe_
# sources. It's a convenience over those two, not a replacement for
# them -- call them yourself instead if this shape doesn't fit (say,
# you want the sources block first, or no usage line at all).
#
#   --prog NAME       program name in the usage line (default: APP)
#   --usage TEXT      replaces "[options]" after the program name
#   --before TEXT     inserted between the usage line and the flags --
#                     a one-line description, or docs for a positional
#                     argument conclude doesn't know about
#   --after TEXT      inserted after the flags, before the sources
#                     block -- docs for a flag you added yourself
#   --no-sources      leave the config-sources block out entirely
#   --skip a,b        settings to leave out of the flag list
#   --sources-args -- ARGS...
#                     everything from here on is forwarded verbatim to
#                     conclude_describe_sources as its own options
#                     (--user, --project, --developer-file, ...); must
#                     be last, since it consumes the rest of "$@" --
#                     unlike conclude_resolve's --help-sources-args,
#                     nothing of this function's own can follow it
conclude_format_help() {
  local app=$1 outvar=$2
  shift 2
  local -n _cd_help_out=$outvar
  local prog=$app usage="[options]" before="" after="" skip="" no_sources=0
  local -a sources_args=()

  while (($#)); do
    case $1 in
      --prog)
        prog=$2
        shift 2
        ;;
      --usage)
        usage=$2
        shift 2
        ;;
      --before)
        before=$2
        shift 2
        ;;
      --after)
        after=$2
        shift 2
        ;;
      --skip)
        skip=$2
        shift 2
        ;;
      --no-sources)
        no_sources=1
        shift
        ;;
      --sources-args)
        shift
        sources_args=("$@")
        break
        ;;
      *)
        printf 'conclude: unrecognized option %q\n' "$1" >&2
        return 1
        ;;
    esac
  done

  local -a cli_opts=()
  [[ -n $skip ]] && cli_opts+=(--skip "$skip")
  local cli_text
  conclude_format_cli "$app" cli_text "${cli_opts[@]}" || return 1

  local -a lines=("Usage: ${prog} ${usage}")
  [[ -n $before ]] && lines+=("" "$before")
  lines+=("" "Options:" "$cli_text")
  [[ -n $after ]] && lines+=("" "$after")
  if ((no_sources == 0)); then
    local sources_text
    conclude_describe_sources "$app" sources_text "${sources_args[@]}" || return 1
    lines+=("" "$sources_text")
  fi

  _cd_help_out=$(
    IFS=$'\n'
    printf '%s' "${lines[*]}"
  )
  return 0
}


# shlex.quote (which format_invocation's expected output is generated
# with): empty -> ''; bare if TEXT is only ASCII word characters plus
# @%+=:,./- ; otherwise single-quoted, with each embedded ' escaped as
# '"'"'. Deliberately ASCII-only (LC_ALL=C) even though the .env/TOML
# formatters above are Unicode-aware -- that asymmetry is in the spec
# itself (see "quoting: non-ASCII letters are quoted" in
# spec/invocation.json vs .env/TOML's own "stay bare" cases).
_conclude_shquote() {
  local LC_ALL=C
  local s=$1
  if [[ -z $s ]]; then
    printf "''"
    return
  fi
  if [[ $s =~ [^A-Za-z0-9_@%+=:,./-] ]]; then
    printf "'%s'" "${s//\'/\'\"\'\"\'}"
  else
    printf '%s' "$s"
  fi
}

# conclude_format_invocation APP RESOLVEDVAR OUTVAR [--prog NAME]
#   [--skip k1,k2,...] [--always-include k1,k2,...]
#   [--compare-default KEY=VALUE]...
#   RESOLVEDVAR: an associative array of a resolved run's values, in
#   conclude_cast's canonical text form ("" for unset/None, matching
#   conclude_merge_layers' own convention). Reproduces that run as a
#   standalone, POSIX-shell-quoted command line: a setting is written
#   as `--flag=value` (or a bare `--flag` for an on boolean) unless it
#   equals its default; an off boolean, or an unset value equal to its
#   (also-unset) default, is never written.
conclude_format_invocation() {
  local app=$1 resolvedvar=$2 outvar=$3
  shift 3
  local -n _cd_inv_resolved=$resolvedvar
  local -n _cd_inv_out=$outvar
  local prog=""
  local -A skip_set=() always_set=() compare_overrides=()
  while (($#)); do
    case $1 in
      --prog)
        prog=$2
        shift 2
        ;;
      --skip)
        local k
        IFS=',' read -ra _cd_skip_keys <<<"$2"
        for k in "${_cd_skip_keys[@]}"; do skip_set[$k]=1; done
        shift 2
        ;;
      --always-include)
        local k
        IFS=',' read -ra _cd_inc_keys <<<"$2"
        for k in "${_cd_inc_keys[@]}"; do always_set[$k]=1; done
        shift 2
        ;;
      --compare-default)
        compare_overrides[${2%%=*}]=${2#*=}
        shift 2
        ;;
      *)
        printf 'conclude: unrecognized option %q\n' "$1" >&2
        return 1
        ;;
    esac
  done

  local -a keys parts=()
  _conclude_ordered_keys "$app" keys
  [[ -n $prog ]] && parts+=("$prog")

  local key value default type rendered flag
  for key in "${keys[@]}"; do
    [[ -v skip_set[$key] ]] && continue
    value=${_cd_inv_resolved[$key]-}
    default=$(_conclude_effective_default "$app" "$key" compare_overrides) || default=""
    # A resolved list (CONCLUDE[...]) holds one item per line, while a
    # declared default is comma-joined; compare and quote them alike.
    if [[ ${_CONCLUDE_TYPES["$app:$key"]-} == list ]]; then
      value=${value//$'\n'/,}
    fi
    if [[ $value == "$default" && ! -v always_set[$key] ]]; then
      continue
    fi
    type=${_CONCLUDE_TYPES["$app:$key"]}
    if [[ $type == bool ]]; then
      [[ $value == true ]] || continue
      rendered=""
    else
      rendered=$(_conclude_shquote "$value")
    fi
    flag=$(conclude_cli_flag_name "$key")
    if [[ -z $rendered ]]; then
      parts+=("$flag")
    else
      parts+=("${flag}=${rendered}")
    fi
  done

  _cd_inv_out=$(
    IFS=' '
    printf '%s' "${parts[*]-}"
  )
  return 0
}
