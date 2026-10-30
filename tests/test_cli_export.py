import contextlib
import io
import json
from pathlib import Path

import pytest

from jsonpit import Pit, PitItem
from jsonpit.cli import main


def run(*args: str) -> tuple[int, str, str]:
	output, error = io.StringIO(), io.StringIO()
	with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
		code = main(list(args))
	return code, output.getvalue(), error.getvalue()


def seed(root: Path, name: str, item: dict) -> None:
	with Pit.open(root / name, read_only=False, unflagged=True) as pit:
		pit.add(PitItem(item))


def test_directory_export_uses_the_pit_name_and_preserves_source(tmp_path: Path) -> None:
	seed(tmp_path, "Person", {"Id": "Customer1", "Name": "Example"})
	source = tmp_path / "Person" / "Person.pit"
	before = source.read_bytes()
	destination = tmp_path / "exports"
	code, output, error = run("export", "Person", "-r", str(tmp_path), "--out-dir", str(destination))
	assert code == 0, error
	assert json.loads((destination / "Person.json").read_text())[0]["Id"] == "Customer1"
	assert "Exported Person" in output
	assert source.read_bytes() == before
	assert not list((tmp_path / "Person").glob("*.flag"))


def test_stdout_and_unadvertised_file_output(tmp_path: Path) -> None:
	seed(tmp_path, "Person", {"Id": "Customer1"})
	code, output, error = run("export", "Person", "--pitroot", str(tmp_path), "--json")
	assert code == 0, error
	assert json.loads(output)[0]["Id"] == "Customer1"
	destination = tmp_path / "old-name.json"
	code, _, error = run("export", str(tmp_path / "Person"), "--out", str(destination))
	assert code == 0, error
	assert json.loads(destination.read_text()) == json.loads(output)


@pytest.mark.parametrize("mode", [[], ["--json", "--out-dir"], ["--out-dir", "--out"]])
def test_conflicting_or_missing_modes_fail_before_io(tmp_path: Path, mode: list[str]) -> None:
	args = ["export", "Person", "-r", str(tmp_path)]
	for token in mode:
		args.append(token)
		if token != "--json": args.append(str(tmp_path / "exports"))
	code, _, error = run(*args)
	assert code == 1
	assert "exactly one output mode" in error
	assert list(tmp_path.iterdir()) == []


def test_point_in_time_directory_export_uses_the_csharp_envelope(tmp_path: Path) -> None:
	seed(tmp_path, "Person", {"Id": "Customer1"})
	destination = tmp_path / "exports"
	code, _, error = run("export", "Person", "-r", str(tmp_path), "--out-dir", str(destination),
		"--at", "2030-01-01T02:00:00+02:00")
	assert code == 0, error
	document = json.loads((destination / "Person.json").read_text())
	assert document["_export"]["at"] == "2030-01-01T00:00:00.0000000Z"
	assert document["_export"]["exported"].endswith("Z")
	assert document["data"][0]["Id"] == "Customer1"


def test_wwwa_directory_export_resolves_references_like_pits(tmp_path: Path) -> None:
	seed(tmp_path, "Person", {"Id": "Customer1"})
	seed(tmp_path, "Object", {"Id": "Order1"})
	seed(tmp_path, "Place", {"Id": "Office1"})
	seed(tmp_path, "Activity", {"Id": "CreateOrder1", "Who": {"Owner": "Customer1"},
		"What": {"Orders": ["Order1"], "Missing": "Unknown"}, "Where": {"Office": "Office1"}})
	destination = tmp_path / "exports"
	code, _, error = run("export", "--wwwa", "-r", str(tmp_path), "--out-dir", str(destination))
	assert code == 0, error
	document = json.loads((destination / "wwwa.json").read_text())
	assert set(document) == {"Person", "Object", "Place", "Activity"}
	activity = document["Activity"][0]
	assert activity["Owner"]["Id"] == "Customer1"
	assert activity["Orders"][0]["Id"] == "Order1"
	assert activity["Office"]["Id"] == "Office1"
	assert activity["What"] == {"Missing": "Unknown"}
	assert "Who" not in activity and "Where" not in activity
