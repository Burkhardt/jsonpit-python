"""
Acceptance and Cross-Parity Tests for CR049:
Live ID Validation (Prohibit template markers '{' and '<' in entity IDs).
Exercises 100% lockstep parity with C# pits / JsonPit v4.4.6.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile

from jsonpit import Pit, PitItem
from jsonpit.cli import main


def test_cr049_a01_template_marker_id_rejected_with_exact_diagnostic() -> None:
	"""A01: Attempt to seed entity with Id containing '{' or '<' fails before mutation."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_root = Path(tmpdir)
		seed_file = pit_root / "invalid.json"
		seed_file.write_text(json.dumps([{"Id": "{AdminPersonId}", "Name": "Admin"}]), encoding="utf-8")

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			rc = main(["put", "Object", str(seed_file), "-r", str(pit_root)])

		assert rc == 1
		err = f_err.getvalue()
		expected = "error: Entity Id '{AdminPersonId}' contains a prohibited template marker ('{' or '<'). Resolve template placeholders before writing to a Pit.\n"
		assert err == expected
		assert not (pit_root / "Object").exists()


def test_cr049_a02_batch_atomicity_rejects_all_before_mutation() -> None:
	"""A02: Batch containing valid entity followed by '{InvalidId}' commits 0 entities."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_root = Path(tmpdir)
		batch_file = pit_root / "batch.json"
		batch_file.write_text(
			json.dumps([{"Id": "ValidEntity", "Name": "OK"}, {"Id": "<Pending>", "Name": "Wait"}]),
			encoding="utf-8",
		)

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			rc = main(["put", "Object", str(batch_file), "-r", str(pit_root)])

		assert rc == 1
		assert "error: Entity Id '<Pending>' contains a prohibited template marker ('{' or '<')." in f_err.getvalue()
		assert not (pit_root / "Object").exists()


def test_cr049_a03_braces_in_attributes_accepted() -> None:
	"""A03: Braces or angle brackets in Note or Name are permitted."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_root = Path(tmpdir)
		payload_file = pit_root / "item.json"
		payload_file.write_text(
			json.dumps({"Id": "Import001", "Class": "ImageImport", "Note": "{value}<tag>"}),
			encoding="utf-8",
		)

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			rc = main(["put", "Object", str(payload_file), "-r", str(pit_root)])

		assert rc == 0
		with Pit.open(pit_root / "Object", read_only=True) as pit:
			assert "Import001" in pit
			item = pit["Import001"]
			assert item["Note"] == "{value}<tag>"


def test_cr049_a04_direct_library_call_rejects_placeholder_id() -> None:
	"""A04: Direct Python library calls: pit.add(itemWithPlaceholderId) throws ValueError."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir) / "TestPit"
		with Pit.open(pit_dir, read_only=False) as pit:
			item = PitItem({"Id": "Person{Suffix}", "Name": "Test"})
			try:
				pit.add(item)
				assert False, "Should have thrown ValueError"
			except ValueError as ex:
				assert "contains a prohibited template marker" in str(ex)


def test_cr049_a05_historical_placeholder_can_load_and_be_deleted() -> None:
	"""A05: Existing historical pit containing placeholder records loads cleanly and can be deleted."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir) / "HistoricalPit"
		pit_dir.mkdir(parents=True)
		# Write a legacy .pit file with a placeholder entity
		historical_payload = [[{"Id": "{LegacyPlaceholder}", "Name": "Old", "Modified": "2026-01-01T00:00:00Z"}]]
		(pit_dir / "HistoricalPit.pit").write_text(json.dumps(historical_payload), encoding="utf-8")

		# Loading succeeds
		with Pit.open(pit_dir, read_only=False) as pit:
			assert "{LegacyPlaceholder}" in pit
			# Can delete it
			pit.delete_item("{LegacyPlaceholder}")
			assert "{LegacyPlaceholder}" not in pit
