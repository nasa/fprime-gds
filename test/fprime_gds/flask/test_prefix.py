"""Tests for GDS application root / reverse-proxy support."""

from fprime_gds.flask.prefix import ScriptNameMiddleware, normalize_application_root


def test_normalize_application_root_empty():
    assert normalize_application_root("") == ""
    assert normalize_application_root(None) == ""


def test_normalize_application_root_adds_leading_slash():
    assert normalize_application_root("fprime-gds-2") == "/fprime-gds-2"


def test_normalize_application_root_strips_trailing_slash():
    assert normalize_application_root("/fprime-gds-2/") == "/fprime-gds-2"


def test_script_name_middleware_strips_prefix():
    captured = {}

    def app(environ, start_response):
        captured["PATH_INFO"] = environ["PATH_INFO"]
        captured["SCRIPT_NAME"] = environ["SCRIPT_NAME"]
        start_response("200 OK", [])
        return [b""]

    wrapped = ScriptNameMiddleware(app, "/fprime-gds-2")
    wrapped(
        {"PATH_INFO": "/fprime-gds-2/dictionary/commands", "SCRIPT_NAME": ""},
        lambda status, headers: None,
    )
    assert captured["PATH_INFO"] == "/dictionary/commands"
    assert captured["SCRIPT_NAME"] == "/fprime-gds-2"
