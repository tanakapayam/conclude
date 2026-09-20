import pytest

from conclude.formatters import (
    format_bool,
    format_list,
    format_scalar,
    infer_formatter,
    infer_formatters,
)
from conclude.infer import opt


def test_format_bool():
    assert format_bool(True) == ""
    assert format_bool(False) is None


def test_format_scalar():
    assert format_scalar(5) == "5"
    assert format_scalar("hello world") == "'hello world'"
    assert format_scalar(1.5) == "1.5"


def test_format_list():
    assert format_list(["a", "b"]) == "a,b"
    assert format_list(["has space", "b"]) == "'has space,b'"


def test_infer_formatter_known_types():
    assert infer_formatter(bool)(True) == ""
    assert infer_formatter(int)(5) == "5"
    assert infer_formatter(str)("x") == "x"
    assert infer_formatter(list)(["a", "b"]) == "a,b"


def test_infer_formatter_unknown_type_raises():
    class Custom:
        pass

    with pytest.raises(TypeError):
        infer_formatter(Custom)


def test_infer_formatters_from_defaults():
    defaults = {"filename": opt(str), "front": opt(list), "shuffle": False, "size": 1}
    formatters = infer_formatters(defaults)
    assert formatters["filename"]("cards.csv") == "cards.csv"
    assert formatters["front"](["A", "B"]) == "A,B"
    assert formatters["shuffle"](True) == ""
    assert formatters["size"](3) == "3"


def test_infer_formatters_override():
    defaults = {"size": 1}

    def custom(value):
        return f"custom:{value}"

    formatters = infer_formatters(defaults, overrides={"size": custom})
    assert formatters["size"](3) == "custom:3"
