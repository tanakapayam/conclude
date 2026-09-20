import pytest

from conclude.infer import Opt, effective_defaults, infer_caster, infer_casters, opt


def test_opt_repr_and_type():
    o = opt(str)
    assert isinstance(o, Opt)
    assert o.type is str
    assert repr(o) == "opt(str)"


def test_effective_defaults_unwraps_opt():
    defaults = {"filename": opt(str), "size": 1, "shuffle": False}
    assert effective_defaults(defaults) == {"filename": None, "size": 1, "shuffle": False}


def test_infer_caster_known_types():
    assert infer_caster(bool)("true") is True
    assert infer_caster(int)("5") == 5
    assert infer_caster(float)("1.5") == 1.5
    assert infer_caster(str)("x") == "x"
    assert infer_caster(list)("a,b") == ["a", "b"]


def test_infer_caster_unknown_type_raises():
    class Custom:
        pass

    with pytest.raises(TypeError):
        infer_caster(Custom)


def test_infer_casters_from_defaults():
    defaults = {
        "filename": opt(str),
        "front": opt(list),
        "shuffle": False,
        "size": 1,
        "filter_col": "Filter",
    }
    casters = infer_casters(defaults)
    assert casters["filename"]("x") == "x"
    assert casters["front"]("a,b") == ["a", "b"]
    assert casters["shuffle"]("yes") is True
    assert casters["size"]("3") == 3
    assert casters["filter_col"]("Continent") == "Continent"


def test_infer_casters_overrides_specific_key():
    defaults = {"size": 1, "filename": opt(str)}

    def custom_size_caster(value):
        return f"custom:{value}"

    casters = infer_casters(defaults, overrides={"size": custom_size_caster})
    assert casters["size"]("3") == "custom:3"
    # filename still inferred normally
    assert casters["filename"]("x") == "x"
