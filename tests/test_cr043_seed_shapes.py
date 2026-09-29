"""
CR043 Acceptance Tests: Seed and Ingest Shapes with 100% C# Parity.
Specification: doc/CR/CR043_AfricaStage_to_RAIkeep_Improve-pits-seed-array-error-message.md
Reference: RAIkeep/PitSeeder/pits/Program.cs (feat(4.4.3): accept single-entity seed payloads)
"""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from jsonpit import Pit, PitItem, parse_and_validate_seed_payload
from jsonpit.cli import main as cli_main


def test_seed_accepts_single_root_entity_with_id() -> None:
	"""CR043 Scenario 1: A root object with non-empty string 'Id' seeds as a single entity."""
	temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_single_"))
	try:
		source_file = temp_dir / "PerformLive.json5"
		source_file.write_text(
			"""{
  "Id": "PerformLive",
  "Kind": "UC",
  "Name": "Perform Live Show",
  "Note": "Live stage performance at an AfricaStage venue."
}""",
			encoding="utf-8",
		)

		# 1. Direct API test
		validated = parse_and_validate_seed_payload(source_file.read_text(encoding="utf-8"), str(source_file))
		assert len(validated) == 1
		assert validated[0]["Id"] == "PerformLive"
		assert validated[0]["Kind"] == "UC"

		# 2. CLI seed test
		exit_code = cli_main(["seed", "Activity", "--source", str(source_file), "-r", str(temp_dir), "-n"])
		assert exit_code == 0

		# 3. Verify Pit contents
		pit_dir = temp_dir / "Activity"
		assert pit_dir.exists()
		with Pit.open("Activity", root=str(temp_dir)) as pit:
			assert len(pit) == 1
			item = pit.get("PerformLive")
			assert item is not None
			assert item["Id"] == "PerformLive"
			assert item["Kind"] == "UC"
			assert item["Name"] == "Perform Live Show"
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)


def test_seed_accepts_keyed_entity_map() -> None:
	"""CR043 Scenario 2: Keyed entity map { "Id1": { ... }, "Id2": { ... } } seeds all items."""
	temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_map_"))
	try:
		source_file = temp_dir / "keyed_map.json5"
		source_file.write_text(
			"""{
  "Item1": { "Id": "Item1", "Kind": "Obj" },
  "Item2": { "Id": "Item2", "Kind": "Obj" }
}""",
			encoding="utf-8",
		)

		exit_code = cli_main(["put", "Object", "-s", str(source_file), "-r", str(temp_dir), "-n"])
		assert exit_code == 0

		with Pit.open("Object", root=str(temp_dir)) as pit:
			assert len(pit) == 2
			item1 = pit.get("Item1")
			item2 = pit.get("Item2")
			assert item1 is not None and item1["Kind"] == "Obj"
			assert item2 is not None and item2["Kind"] == "Obj"
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)


def test_seed_accepts_standard_array() -> None:
	"""CR043 Scenario 3: Standard root JSON array of entity objects."""
	temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_array_"))
	try:
		source_file = temp_dir / "array.json"
		source_file.write_text(
			"""[
  { "Id": "Item1", "Kind": "Obj" },
  { "Id": "Item2", "Kind": "Obj" }
]""",
			encoding="utf-8",
		)

		exit_code = cli_main(["seed", "Object", str(source_file), "-r", str(temp_dir), "-n"])
		assert exit_code == 0

		with Pit.open("Object", root=str(temp_dir)) as pit:
			assert len(pit) == 2
			assert "Item1" in pit
			assert "Item2" in pit
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)


def test_seed_rejects_invalid_single_root_with_three_way_diagnostic() -> None:
	"""CR043 Scenario 4: Invalid root objects that fail all 3 shapes emit the 3-way diagnostic."""
	invalid_payloads = [
		'{ "Title": "InvalidNoId", "Count": 42 }',
		'{ "Kind": "UC", "Name": "Missing Id" }',
		'{ "Id": "", "Kind": "UC" }',
		'{ "Id": "   ", "Kind": "UC" }',
		'{ "Id": 42, "Kind": "UC" }',
		'{ "id": "lowercase-is-not-Id", "Kind": "UC" }',
	]

	for payload in invalid_payloads:
		temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_inv_"))
		try:
			source_file = temp_dir / "invalid.json5"
			source_file.write_text(payload, encoding="utf-8")

			stderr_buf = io.StringIO()
			with patch("sys.stderr", stderr_buf):
				exit_code = cli_main(["seed", "Activity", "--source", str(source_file), "-r", str(temp_dir), "-n"])

			assert exit_code == 1
			err_output = stderr_buf.getvalue()
			assert "JSON array of entities" in err_output
			assert "single entity object with a non-empty 'Id'" in err_output
			assert "keyed map of entity objects" in err_output

			# Pre-flight invariant: Pit directory must NOT have been created!
			pit_dir = temp_dir / "Activity"
			assert not pit_dir.exists(), f"Pit directory {pit_dir} was erroneously created on validation failure!"
		finally:
			shutil.rmtree(temp_dir, ignore_errors=True)


def test_seed_rejects_entity_without_id_before_opening_pit() -> None:
	"""CR043 Scenario 5a: An entity without a non-empty string 'Id' inside array or map."""
	invalid_payloads = [
		'[{ "Name": "Missing Id" }]',
		'{ "Item1": { "Name": "Missing Id" } }',
	]

	for payload in invalid_payloads:
		temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_noid_"))
		try:
			source_file = temp_dir / "missing_id.json5"
			source_file.write_text(payload, encoding="utf-8")

			stderr_buf = io.StringIO()
			with patch("sys.stderr", stderr_buf):
				exit_code = cli_main(["seed", "Activity", "--source", str(source_file), "-r", str(temp_dir), "-n"])

			assert exit_code == 1
			err_output = stderr_buf.getvalue()
			assert "entity without a non-empty string 'Id'" in err_output

			# Pre-flight invariant: Pit directory must NOT have been created!
			pit_dir = temp_dir / "Activity"
			assert not pit_dir.exists(), f"Pit directory {pit_dir} was erroneously created!"
		finally:
			shutil.rmtree(temp_dir, ignore_errors=True)


def test_seed_rejects_non_object_array_entry_before_opening_pit() -> None:
	"""CR043 Scenario 5b: Array contains a primitive or non-object entry."""
	temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr043_nonobj_"))
	try:
		source_file = temp_dir / "non_object.json"
		source_file.write_text('[{ "Id": "Valid" }, "InvalidString"]', encoding="utf-8")

		stderr_buf = io.StringIO()
		with patch("sys.stderr", stderr_buf):
			exit_code = cli_main(["seed", "Activity", "--source", str(source_file), "-r", str(temp_dir), "-n"])

		assert exit_code == 1
		err_output = stderr_buf.getvalue()
		assert "may contain only JSON objects" in err_output

		# Pre-flight invariant: Pit directory must NOT have been created!
		pit_dir = temp_dir / "Activity"
		assert not pit_dir.exists(), f"Pit directory {pit_dir} was erroneously created!"
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)
