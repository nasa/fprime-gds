"""Regression tests for the dictionary merge CLI's deployment name option."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fprime_gds.executables.dictionary_merge import parse_arguments


@pytest.fixture
def dictionaries(tmp_path):
    """Create two minimal dictionaries with distinct commands and matching types."""
    metadata = {
        "deploymentName": "Primary",
        "projectVersion": "1.0.0",
        "frameworkVersion": "4.0.0",
        "dictionarySpecVersion": "1.0.0",
    }
    first = {
        "metadata": metadata,
        "typeDefinitions": [{"qualifiedName": "Example.Count", "kind": "integer"}],
        "constants": [],
        "commands": [{"name": "First.NO_OP", "opcode": 1}],
        "parameters": [],
        "events": [],
        "telemetryChannels": [],
        "records": [],
        "containers": [],
        "telemetryPacketSets": [],
    }
    second = copy.deepcopy(first)
    second["metadata"]["deploymentName"] = "Secondary"
    second["commands"] = [{"name": "Second.NO_OP", "opcode": 2}]
    paths = [tmp_path / "first.json", tmp_path / "second.json"]
    for path, dictionary in zip(paths, [first, second]):
        path.write_text(json.dumps(dictionary), encoding="utf-8")
    return paths, first, second


def run_merge(paths, output, *options):
    """Run the real CLI without altering the test process's argument state."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "fprime_gds.executables.dictionary_merge",
            "--output",
            str(output),
            *options,
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("name", ["Mission", "_Mission", "Mission_2", "_"])
def test_named_merge_preserves_dictionary_contents(dictionaries, tmp_path, name):
    """Valid ASCII identifiers become the merged deployment name."""
    paths, first, second = dictionaries
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "merged.json"
    result = run_merge(paths, output, "--name", name)
    assert result.returncode == 0, result.stderr
    merged = json.loads(output.read_text(encoding="utf-8"))
    assert merged["metadata"]["deploymentName"] == name
    assert merged["commands"] == first["commands"] + second["commands"]
    assert merged["typeDefinitions"] == first["typeDefinitions"]
    assert [path.read_bytes() for path in paths] == originals


@pytest.mark.parametrize(
    "name",
    [
        "",
        "2Mission",
        "bad-name",
        "name.suffix",
        "name suffix",
        "name!",
        "name\n",
        "équipe",
    ],
)
def test_invalid_name_is_rejected_before_writing(dictionaries, tmp_path, name):
    """Reject the complete invalid identifier without truncating an output file."""
    paths, _, _ = dictionaries
    output = tmp_path / "merged.json"
    output.write_text("existing output", encoding="utf-8")
    result = run_merge(paths, output, "--name", name)
    assert result.returncode != 0
    assert "is an invalid identifier" in result.stderr
    assert output.read_text(encoding="utf-8") == "existing output"


def test_parse_named_dictionary_arguments(dictionaries, monkeypatch, tmp_path):
    """The parser accepts a valid name and retains its Path arguments."""
    paths, _, _ = dictionaries
    output = tmp_path / "named.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fprime-merge-dictionary",
            "--name",
            "Merged",
            "--output",
            str(output),
            *map(str, paths),
        ],
    )
    args = parse_arguments()
    assert args.name == "Merged"
    assert args.dictionary1 == paths[0]
    assert args.dictionary2 == paths[1]
    assert args.output == output
    assert isinstance(args.output, Path)


def test_default_name_is_unchanged(dictionaries, tmp_path):
    """Omitting the name continues to derive it from both deployments."""
    paths, _, _ = dictionaries
    output = tmp_path / "merged.json"
    result = run_merge(paths, output)
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(output.read_text())["metadata"]["deploymentName"]
        == "Primary_Secondary_merged"
    )


@pytest.mark.parametrize("permissive", [False, True])
def test_named_merge_preserves_metadata_validation(dictionaries, tmp_path, permissive):
    """A requested name does not bypass the existing metadata compatibility check."""
    paths, _, second = dictionaries
    second["metadata"]["projectVersion"] = "2.0.0"
    paths[1].write_text(json.dumps(second))
    output = tmp_path / "merged.json"
    options = ["--name", "Combined", *(["--permissive"] if permissive else [])]
    result = run_merge(paths, output, *options)
    if permissive:
        assert result.returncode == 0, result.stderr
        assert (
            json.loads(output.read_text())["metadata"]["deploymentName"] == "Combined"
        )
    else:
        assert result.returncode != 0
        assert "Inconsistent metadata" in result.stderr
        assert not output.exists()
