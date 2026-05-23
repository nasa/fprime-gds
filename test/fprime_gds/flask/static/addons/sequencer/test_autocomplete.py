from pathlib import Path


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise AssertionError("Unable to locate repository root")


AUTOCOMPLETE_SOURCE = (
    _repo_root()
    / "src"
    / "fprime_gds"
    / "flask"
    / "static"
    / "addons"
    / "sequencer"
    / "autocomplete.js"
)


def test_absolute_time_snippet_uses_day_placeholder():
    source = AUTOCOMPLETE_SOURCE.read_text(encoding="utf-8")
    legacy_field = "do" + "y"
    legacy_snippet = "A${year}-${" + legacy_field + "}T${hours}:${minutes}:${seconds}"

    assert 'A${year}-${day}T${hours}:${minutes}:${seconds}' in source
    assert legacy_snippet not in source
