from pathlib import Path


AUTOCOMPLETE_SOURCE = (
    Path(__file__).resolve().parents[6]
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

    assert 'A${year}-${day}T${hours}:${minutes}:${seconds}' in source
    assert 'A${year}-${doy}T${hours}:${minutes}:${seconds}' not in source
