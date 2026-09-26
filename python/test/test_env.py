import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conclude.env import load_dotenv, load_env

ENV_VARS = {"name": "MYAPP_NAME", "count": "MYAPP_COUNT"}


def test_load_env_reads_present_vars_only():
    environ = {"MYAPP_NAME": "alice", "UNRELATED": "x"}
    assert load_env(ENV_VARS, environ) == {"name": "alice"}


def test_load_env_missing_vars_absent_not_none():
    environ = {}
    result = load_env(ENV_VARS, environ)
    assert result == {}
    assert "count" not in result


def test_load_env_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("MYAPP_NAME", "from-os-environ")
    monkeypatch.delenv("MYAPP_COUNT", raising=False)
    assert load_env(ENV_VARS) == {"name": "from-os-environ"}


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_load_dotenv_basic_parsing(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "NAME=alice",
                "export COUNT=5",
                "QUOTED_SINGLE='literal $not_expanded'",
                'QUOTED_DOUBLE="line1\\nline2"',
                "  SPACED  =  value  ",
            ]
        )
    )
    result = load_dotenv(path)
    assert result["NAME"] == "alice"
    assert result["COUNT"] == "5"
    assert result["QUOTED_SINGLE"] == "literal $not_expanded"
    assert result["QUOTED_DOUBLE"] == "line1\nline2"
    assert result["SPACED"] == "value"


def test_load_dotenv_ignores_lines_without_equals(tmp_path):
    path = tmp_path / ".env"
    path.write_text("NAME=alice\nnot a valid line\n")
    result = load_dotenv(path)
    assert result == {"NAME": "alice"}


def test_load_dotenv_double_quoted_non_ascii_not_corrupted(tmp_path):
    # The historical bug: double-quoted values were decoded via
    # text.encode("utf-8").decode("unicode_escape"), which corrupts
    # any non-ASCII character (see test_casters.py's equivalent test
    # for cast_escaped_str, which shared the same bug).
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                'GREETING="café"',
                'JAPANESE="日本語"',
                'MIXED="café\\nmore"',
                "SINGLE_QUOTED='日本語'",  # single-quoted: always literal anyway
            ]
        )
    )
    result = load_dotenv(path)
    assert result["GREETING"] == "café"
    assert result["JAPANESE"] == "日本語"
    assert result["MIXED"] == "café\nmore"
    assert result["SINGLE_QUOTED"] == "日本語"


def test_load_env_dotenv_fills_in_missing_vars(tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("MYAPP_NAME=from-dotenv\nMYAPP_COUNT=9\n")
    result = load_env(ENV_VARS, {}, dotenv_path=dotenv_path)
    assert result == {"name": "from-dotenv", "count": "9"}


def test_load_env_real_environ_wins_over_dotenv(tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("MYAPP_NAME=from-dotenv\n")
    environ = {"MYAPP_NAME": "from-real-environ"}
    result = load_env(ENV_VARS, environ, dotenv_path=dotenv_path)
    assert result["name"] == "from-real-environ"


def test_load_env_no_dotenv_path_ignores_dotenv_files(tmp_path, monkeypatch):
    # Without dotenv_path, load_env never even looks for a .env file.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MYAPP_NAME=from-dotenv\n")
    assert load_env(ENV_VARS, {}) == {}


# --- encoding: .env files are UTF-8 everywhere ----------------------------------------


def test_load_dotenv_ignores_a_leading_byte_order_mark(tmp_path):
    # What Windows Notepad writes: without this the first name would be
    # "\ufeffMYAPP_FIRST" and that variable would silently go missing.
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfMYAPP_FIRST=one\nMYAPP_SECOND=two\n")
    assert load_dotenv(path) == {"MYAPP_FIRST": "one", "MYAPP_SECOND": "two"}


def test_load_dotenv_reads_utf8_whatever_the_platform_default_encoding(tmp_path):
    # Run in a child interpreter whose default text encoding is ASCII (the C
    # locale, UTF-8 mode off) -- the same situation as cp1252 on Windows.
    path = tmp_path / ".env"
    path.write_bytes("MYAPP_NAME=café\nMYAPP_EMOJI='🎉'\n".encode())
    code = (
        "import json, locale, pathlib, sys\n"
        "from conclude import load_dotenv\n"
        "print(json.dumps([locale.getencoding(), load_dotenv(pathlib.Path(sys.argv[1]))]))\n"
    )
    env = {**os.environ, "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0"}
    env.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code, str(path)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    encoding, values = json.loads(result.stdout)
    if encoding.lower().replace("-", "").replace("_", "") in {"utf8", "cp65001"}:
        pytest.skip("could not make the child's default text encoding non-UTF-8 here")
    assert values == {"MYAPP_NAME": "café", "MYAPP_EMOJI": "🎉"}


def test_load_dotenv_always_passes_an_explicit_encoding(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes(b"MYAPP_A=1\n")
    seen = []
    original = Path.read_text

    def spy(self, encoding=None, errors=None, **kwargs):
        seen.append(encoding)
        return original(self, encoding=encoding, errors=errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    load_dotenv(path)
    assert seen and all(encoding and encoding.lower().startswith("utf-8") for encoding in seen)
