#!/usr/bin/env bats
# conclude_resolve has no spec/*.json fixture of its own -- what a command
# line gives a setting is spec/cli.json (see cli.bats), but real file-path
# wiring is language-specific by nature (this is exactly
# the seam argparse/Node's parser/this bash parser all differ at), unlike
# every other module in this test suite. These are hand-written
# integration checks instead, covering the precedence chain this module
# claims: defaults < user config < project config(+siblings) < env < cli.

setup() {
  source "${BATS_TEST_DIRNAME}/../src/conclude.sh"
  WORK="${BATS_TEST_TMPDIR}/proj"
  mkdir -p "$WORK"
  cd "$WORK" || exit 1
  export HOME="${BATS_TEST_TMPDIR}/home"
  mkdir -p "$HOME"
  unset XDG_CONFIG_HOME
}

define_myapp() {
  conclude_init myapp
  conclude_define myapp host str localhost
  conclude_define myapp port int 8080
  conclude_define myapp debug bool false
  conclude_define myapp filter_col str
}

@test "resolve: defaults alone, nothing else configured" {
  define_myapp
  conclude_resolve myapp --
  [ "${CONCLUDE[host]}" = localhost ]
  [ "${CONCLUDE[port]}" = 8080 ]
  [ "${CONCLUDE[debug]}" = false ]
  [ "${CONCLUDE[filter_col]}" = "" ]
  [ "$MYAPP_HOST" = localhost ]
  [ "$MYAPP_PORT" = 8080 ]
}

@test "resolve: a CLI flag beats every other layer" {
  define_myapp
  mkdir -p "$HOME/.config/myapp"
  printf '[myapp]\nhost = "from-user"\n' >"$HOME/.config/myapp/config.toml"
  printf '[myapp]\nhost = "from-project"\n' >.config.toml
  MYAPP_HOST=from-env conclude_resolve myapp -- --host from-cli
  [ "${CONCLUDE[host]}" = from-cli ]
}

@test "resolve: env beats project config, which beats user config" {
  define_myapp
  mkdir -p "$HOME/.config/myapp"
  printf '[myapp]\nhost = "from-user"\nport = 1111\n' >"$HOME/.config/myapp/config.toml"
  printf '[myapp]\nhost = "from-project"\n' >.config.toml
  MYAPP_HOST=from-env conclude_resolve myapp --
  [ "${CONCLUDE[host]}" = from-env ]  # env beats project
  [ "${CONCLUDE[port]}" = 1111 ]      # user config still applies where nothing overrides it
}

@test "resolve: a sibling file beats the plain project config" {
  define_myapp
  printf '[myapp]\nhost = "from-project"\n' >.config.toml
  printf '[myapp]\nhost = "from-sibling"\n' >.config.b.toml
  conclude_resolve myapp --
  [ "${CONCLUDE[host]}" = from-sibling ]
}

@test "resolve: --no-siblings drops the sibling file" {
  define_myapp
  printf '[myapp]\nhost = "from-project"\n' >.config.toml
  printf '[myapp]\nhost = "from-sibling"\n' >.config.b.toml
  conclude_resolve myapp --no-siblings --
  [ "${CONCLUDE[host]}" = from-project ]
}

@test "resolve: a bare boolean flag turns it on" {
  define_myapp
  conclude_resolve myapp -- --debug
  [ "${CONCLUDE[debug]}" = true ]
}

@test "resolve: an unrecognized CLI argument is an error" {
  define_myapp
  run conclude_resolve myapp -- --nonexistent x
  [ "$status" -eq 1 ]
}

@test "resolve: a bad CLI value is an error" {
  define_myapp
  run conclude_resolve myapp -- --port not-a-number
  [ "$status" -eq 1 ]
}

@test "resolve: --flag=value syntax works for non-bool settings" {
  define_myapp
  conclude_resolve myapp -- --port=9999
  [ "${CONCLUDE[port]}" = 9999 ]
}

# --- developer layer --------------------------------------------------------

init_git_with_ignore() {
  git init -q
  printf '%s\n' "$@" >.gitignore
}

@test "resolve: an active developer .toml file beats env but loses to the CLI" {
  define_myapp
  init_git_with_ignore .developer.toml
  printf '[myapp]\nhost = "from-developer"\nport = 2222\n' >.developer.toml
  MYAPP_HOST=from-env conclude_resolve myapp --developer-file .developer.toml -- --port 3333
  [ "${CONCLUDE[host]}" = from-developer ]
  [ "${CONCLUDE[port]}" = 3333 ]
}

@test "resolve: a developer file that isn't gitignored is skipped" {
  define_myapp
  init_git_with_ignore other
  printf '[myapp]\nhost = "from-developer"\n' >.developer.toml
  MYAPP_HOST=from-env conclude_resolve myapp --developer-file .developer.toml --
  [ "${CONCLUDE[host]}" = from-env ]
}

@test "resolve: the developer kill switch turns the layer off" {
  define_myapp
  init_git_with_ignore .developer.toml
  printf '[myapp]\nhost = "from-developer"\n' >.developer.toml
  MYAPP_DEVELOPER_CONFIG=off MYAPP_HOST=from-env \
    conclude_resolve myapp --developer-file .developer.toml --
  [ "${CONCLUDE[host]}" = from-env ]
}

@test "resolve: a non-.toml developer file is read as dotenv" {
  define_myapp
  init_git_with_ignore .env.local
  printf 'MYAPP_HOST=from-dotenv\nMYAPP_PORT=4444\n' >.env.local
  conclude_resolve myapp --developer-file .env.local --
  [ "${CONCLUDE[host]}" = from-dotenv ]
  [ "${CONCLUDE[port]}" = 4444 ]
}

# --- table selection, and resolve -> invocation round trip -------------------

@test "resolve: --table selects a different table, and a second level overlays it" {
  define_myapp
  printf '[other]\nhost = "from-other"\n[other.deck]\nport = 7\n' >.config.toml
  conclude_resolve myapp --table other --table deck --
  [ "${CONCLUDE[host]}" = from-other ]
  [ "${CONCLUDE[port]}" = 7 ]
}

@test "resolve: --table with three levels is an error" {
  define_myapp
  run conclude_resolve myapp --table a --table b --table c --
  [ "$status" -eq 1 ]
}

@test "resolve: a resolved run round-trips through format_invocation, lists included" {
  conclude_init myapp
  conclude_define myapp host str localhost
  conclude_define myapp tags list "a,b"
  conclude_define myapp debug bool false
  conclude_resolve myapp -- --tags "x, y z" --debug
  local out=""
  conclude_format_invocation myapp CONCLUDE out --prog myapp
  [ "$out" = "myapp --tags='x,y z' --debug" ]
  # ...and a run that changes nothing writes nothing. (conclude_resolve
  # exports every setting, so a second run in the same shell would read
  # the first run's values back as its env layer -- clear them first.)
  unset MYAPP_HOST MYAPP_TAGS MYAPP_DEBUG
  conclude_resolve myapp --
  conclude_format_invocation myapp CONCLUDE out --prog myapp
  [ "$out" = "myapp" ]
}

@test "resolve: --bool=false is an error, not a silent true" {
  define_myapp
  run conclude_resolve myapp -- --debug=false
  [ "$status" -eq 1 ]
}

# --- opt-in --help-flag / conclude_format_help ------------------------------

@test "resolve: -h/--help do nothing unless --help-flag is given" {
  define_myapp
  run conclude_resolve myapp -- -h
  # not opted in: -h is just an unrecognized argument, same as any other typo
  [ "$status" -eq 1 ]
}

@test "resolve: --help-flag makes -h print help and return 2, touching nothing" {
  define_myapp
  MYAPP_HOST=should-not-be-seen
  run conclude_resolve myapp --help-flag -- -h
  [ "$status" -eq 2 ]
  [[ $output == "Usage: myapp"* ]]
  [[ $output == *"--host <HOST>"* ]]
  [[ $output == *"config sources:"* ]]
  unset MYAPP_HOST
}

@test "resolve: --help-flag also recognizes --help, and still resolves normally without it" {
  define_myapp
  run conclude_resolve myapp --help-flag -- --help
  [ "$status" -eq 2 ]

  conclude_resolve myapp --help-flag -- --port 9
  [ "${CONCLUDE[port]}" = 9 ]
}

@test "format_help: --before/--after/--no-sources, and --sources-args forwarding" {
  define_myapp
  local out
  conclude_format_help myapp out --prog demo --usage "[options] RECIPIENT" \
    --before "A reminder tool." --after "  RECIPIENT   who to remind" \
    --sources-args --user "$HOME/.config/myapp/config.toml"
  [[ $out == "Usage: demo [options] RECIPIENT"* ]]
  [[ $out == *"A reminder tool."* ]]
  [[ $out == *"RECIPIENT   who to remind"* ]]
  [[ $out == *"$HOME/.config/myapp/config.toml"* ]]

  conclude_format_help myapp out --no-sources
  [[ $out != *"config sources:"* ]]
}

@test "resolve: --help-sources-args stops at the next -- rather than eating it" {
  define_myapp
  conclude_resolve myapp --help-flag \
    --help-sources-args --user "$HOME/.config/myapp/config.toml" \
    -- --port 9
  [ "${CONCLUDE[port]}" = 9 ]
}
# --- the personal control file (~/.config/conclude/control.toml) -----------

@test "conclude_resolve_developer_file: no control file at all falls back to .developer.toml" {
  local out
  conclude_resolve_developer_file "" out
  [ "$out" = ".developer.toml" ]
  conclude_resolve_developer_file "app.toml" out
  [ "$out" = "app.toml" ]
}

@test "conclude_resolve_developer_file: control.toml is a fallback by default, not an override" {
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".from-control.toml"\n' >"$HOME/.config/conclude/control.toml"

  local out
  conclude_resolve_developer_file "" out
  [ "$out" = ".from-control.toml" ] # nothing of the app's own to fall back from

  conclude_resolve_developer_file "app.toml" out
  [ "$out" = "app.toml" ] # the app's own choice still wins
}

@test "conclude_resolve_developer_file: override = true wins even over the app's own path" {
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".from-control.toml"\noverride = true\n' \
    >"$HOME/.config/conclude/control.toml"

  local out
  conclude_resolve_developer_file "app.toml" out
  [ "$out" = ".from-control.toml" ]
}

@test "conclude_resolve_developer_file: [control.bash] overlays [control], same as any app table" {
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".general.toml"\n[control.bash]\ndeveloper_file = ".bash-only.toml"\n' \
    >"$HOME/.config/conclude/control.toml"

  local out
  conclude_resolve_developer_file "" out
  [ "$out" = ".bash-only.toml" ]
}

@test "resolve: --developer-opt-in with no path of its own uses control.toml's fallback" {
  define_myapp
  init_git_with_ignore .from-control.toml
  printf '[myapp]\nhost = "from-developer"\n' >.from-control.toml
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".from-control.toml"\n' >"$HOME/.config/conclude/control.toml"

  conclude_resolve myapp --developer-opt-in -- --port 1
  [ "${CONCLUDE[host]}" = from-developer ]
}

@test "resolve: --developer-opt-in with no control.toml at all falls back to .developer.toml" {
  define_myapp
  init_git_with_ignore .developer.toml
  printf '[myapp]\nhost = "from-default-file"\n' >.developer.toml

  conclude_resolve myapp --developer-opt-in -- --port 1
  [ "${CONCLUDE[host]}" = from-default-file ]
}

@test "resolve: control.toml's override overrules the app's own --developer-file" {
  define_myapp
  init_git_with_ignore .app-choice.toml .control-choice.toml
  printf '[myapp]\nhost = "from-app-choice"\n' >.app-choice.toml
  printf '[myapp]\nhost = "from-control-choice"\n' >.control-choice.toml
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".control-choice.toml"\noverride = true\n' \
    >"$HOME/.config/conclude/control.toml"

  conclude_resolve myapp --developer-file .app-choice.toml -- --port 1
  [ "${CONCLUDE[host]}" = from-control-choice ]
}

@test "resolve: without override, the app's own --developer-file still wins over control.toml" {
  define_myapp
  init_git_with_ignore .app-choice.toml .control-choice.toml
  printf '[myapp]\nhost = "from-app-choice"\n' >.app-choice.toml
  printf '[myapp]\nhost = "from-control-choice"\n' >.control-choice.toml
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".control-choice.toml"\n' >"$HOME/.config/conclude/control.toml"

  conclude_resolve myapp --developer-file .app-choice.toml -- --port 1
  [ "${CONCLUDE[host]}" = from-app-choice ]
}

@test "resolve: without --developer-file or --developer-opt-in, control.toml is never consulted" {
  define_myapp
  init_git_with_ignore .from-control.toml
  printf '[myapp]\nhost = "from-developer"\n' >.from-control.toml
  mkdir -p "$HOME/.config/conclude"
  printf '[control]\ndeveloper_file = ".from-control.toml"\noverride = true\n' \
    >"$HOME/.config/conclude/control.toml"

  conclude_resolve myapp -- --port 1
  [ "${CONCLUDE[host]}" = localhost ] # its own default stands; the layer never ran at all
}

@test "resolve: --user-config's default respects XDG_CONFIG_HOME" {
  define_myapp
  export XDG_CONFIG_HOME="${BATS_TEST_TMPDIR}/xdg"
  mkdir -p "$XDG_CONFIG_HOME/myapp"
  printf '[myapp]\nhost = "from-xdg"\n' >"$XDG_CONFIG_HOME/myapp/config.toml"

  conclude_resolve myapp -- --port 1
  [ "${CONCLUDE[host]}" = from-xdg ]
  unset XDG_CONFIG_HOME
}
