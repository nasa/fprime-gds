"""Regression tests for nasa/fprime#5451: parse_json must not drop
parameters whose explicit value is falsy (0, 0.0, False, "")."""
from pathlib import Path

import pytest

from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.tools.params import parse_json

DICT_FILE = Path(__file__).parent / "resources" / "simple_dictionary.json"


@pytest.fixture()
def name_dict():
    loader = PrmJsonLoader(str(DICT_FILE.resolve()))
    _, name_dict, _ = loader.construct_dicts(str(DICT_FILE.resolve()))
    assert name_dict, "test dictionary should define at least one parameter"
    return name_dict


def _first_param(name_dict):
    fqn, template = next(iter(name_dict.items()))
    return fqn, template


@pytest.mark.parametrize("falsy_value", [0, 0.0, False, ""])
def test_explicit_falsy_value_is_kept(name_dict, falsy_value):
    fqn, template = _first_param(name_dict)
    param_value_json = {template.comp_name: {template.prm_name: falsy_value}}

    result = parse_json(param_value_json, name_dict, False)

    matches = [val for tmpl, val in result if tmpl is template]
    assert matches == [falsy_value], (
        f"explicit value {falsy_value!r} for {fqn} was dropped"
    )


def test_explicit_falsy_overrides_default(name_dict):
    """With implicit defaults enabled, an explicit falsy value must win
    over the dictionary default instead of vanishing entirely."""
    fqn, template = _first_param(name_dict)
    param_value_json = {template.comp_name: {template.prm_name: 0}}

    result = parse_json(param_value_json, name_dict, True)

    matches = [val for tmpl, val in result if tmpl is template]
    assert matches == [0], f"falsy override for {fqn} was dropped"
