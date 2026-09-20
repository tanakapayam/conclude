from conclude.naming import cli_flag_name, config_key_name, env_var_name


def test_cli_flag_name():
    assert cli_flag_name("filename") == "--filename"
    assert cli_flag_name("filter_col") == "--filter-col"
    assert cli_flag_name("middle_timer") == "--middle-timer"


def test_env_var_name():
    assert env_var_name("remind", "retries") == "REMIND_RETRIES"
    assert env_var_name("myapp", "size") == "MYAPP_SIZE"


def test_env_var_name_sanitizes_hyphenated_app_name():
    # A hyphenated app name is a normal CLI-tool naming convention
    # ("my-app"), but a hyphen isn't legal in a shell env var name --
    # it should become an underscore, not survive into the result.
    assert env_var_name("my-app", "foo_bar") == "MY_APP_FOO_BAR"
    assert "-" not in env_var_name("my-app", "foo_bar")


def test_env_var_name_sanitizes_other_non_identifier_chars():
    assert env_var_name("my app", "foo.bar") == "MY_APP_FOO_BAR"


def test_env_var_name_prefixes_underscore_for_leading_digit():
    # A shell identifier can't start with a digit, even though it can
    # contain one -- "123app" alone would otherwise sanitize straight
    # into the shell-illegal "123APP_FOO".
    assert env_var_name("123app", "foo") == "_123APP_FOO"
    assert not env_var_name("123app", "foo")[0].isdigit()


def test_env_var_name_digit_only_app_name():
    assert env_var_name("123", "456") == "_123_456"


def test_env_var_name_digit_leading_key_is_fine_without_prefix():
    # Only the *overall* name's first character has to be non-digit --
    # a key starting with a digit is fine once it's not in that
    # leading position (i.e. app_name isn't empty/digit-leading).
    result = env_var_name("remind", "2fa_enabled")
    assert result == "REMIND_2FA_ENABLED"
    assert not result[0].isdigit()


def test_env_var_name_hyphen_and_underscore_collide():
    # Documented limitation: two different app names that only differ
    # by which non-identifier character occupies the same position
    # sanitize to the same result.
    assert env_var_name("my-app", "x") == env_var_name("my_app", "x")


def test_config_key_name_is_identity():
    assert config_key_name("filter_col") == "filter_col"
    assert config_key_name("size") == "size"
