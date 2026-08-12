import pytest

from fprime_gds.executables.base_url import BaseUrlParser, normalize_base_url, with_base_url


@pytest.mark.parametrize(
    "value, expected",
    [
        ("", ""),
        ("/", ""),
        ("gds", "/gds"),
        ("/gds", "/gds"),
        ("/mission/gds/", "/mission/gds"),
    ],
)
def test_normalize_base_url(value, expected):
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/gds",
        "//example.com/gds",
        "/gds?mode=test",
        "/gds#fragment",
        "/gds//nested",
        "/gds/../other",
        "/gds/%2e%2e/other",
        "/gds/%2fother",
    ],
)
def test_normalize_base_url_rejects_non_path_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        normalize_base_url(value)


def test_with_base_url_preserves_root_routes_and_prefixes_nested_routes():
    assert with_base_url("", "/channels") == "/channels"
    assert with_base_url("/mission/gds", "/channels") == "/mission/gds/channels"
    assert with_base_url("/mission/gds", "/") == "/mission/gds/"


def test_base_url_parser_normalizes_command_line_value():
    parser = BaseUrlParser().get_parser()
    args = parser.parse_args(["--base-url", "mission/gds/"])
    assert args.base_url == "/mission/gds"
