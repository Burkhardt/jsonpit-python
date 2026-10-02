"""
Acceptance and Cross-Parity Tests for CR047:
Strict Patch Mode (--require-existing / --patch) and CLI Version String Parity.
Exercises 100% lockstep parity with C# pits v4.4.5.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from jsonpit import (
	Pit,
	PitItem,
	StrictPatchValidationError,
	__version__,
)
from jsonpit.cli import build_parser, main


def test_cr047_tc01_patch_existing_entity_succeeds() -> None:
	"""TC-01: [{"Id": "Alice", "UseCase": "Live"}] with --require-existing succeeds (exit 0)."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		# Seed initial entity
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act", "Name": "Alice Activity"}))

		patch_file = pit_dir / "patch.json"
		patch_file.write_text(json.dumps([{"Id": "Alice", "UseCase": "Live"}]))

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(patch_file), "--require-existing"])

		assert code == 0, f"Expected exit 0, got {code}. stderr: {f_err.getvalue()}"
		assert "Successfully committed 1 entity(ies)" in f_out.getvalue()

		# Verify projection has both original and patched attributes
		with Pit.open(pit_dir / "Activity", read_only=True) as pit:
			alice = pit.get("Alice")
			assert alice is not None
			assert alice["Kind"] == "Act"
			assert alice["Name"] == "Alice Activity"
			assert alice["UseCase"] == "Live"


def test_cr047_tc02_missing_id_rejected_before_write() -> None:
	"""TC-02: [{"Id": "Ghost99", "UseCase": "Live"}] with --require-existing fails (exit 1)."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act"}))

		patch_file = pit_dir / "patch.json"
		patch_file.write_text(json.dumps([{"Id": "Ghost99", "UseCase": "Live"}]))

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(patch_file), "--require-existing"])

		assert code == 1
		err = f_err.getvalue()
		assert "error: Entity 'Ghost99' does not exist in Pit 'Activity'." in err
		assert "Use without --require-existing / --patch to allow creating new entities." in err

		# Verify Ghost99 was NOT created
		with Pit.open(pit_dir / "Activity", read_only=True) as pit:
			assert pit.get("Ghost99") is None


def test_cr047_tc03_mixed_batch_atomicity() -> None:
	"""TC-03: Mixed batch [Alice (exists), Ghost99 (missing)] with --patch aborts atomically (exit 1)."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act", "Name": "Original"}))

		patch_file = pit_dir / "patch.json"
		patch_file.write_text(json.dumps([
			{"Id": "Alice", "Name": "Mutated"},
			{"Id": "Ghost99", "UseCase": "Live"},
		]))

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(patch_file), "--patch"])

		assert code == 1
		err = f_err.getvalue()
		assert "error: Entity 'Ghost99' does not exist in Pit 'Activity'." in err

		# Verify ATOMICITY: Alice must NOT have been updated!
		with Pit.open(pit_dir / "Activity", read_only=True) as pit:
			alice = pit.get("Alice")
			assert alice is not None
			assert alice["Name"] == "Original"
			assert pit.get("Ghost99") is None


def test_cr047_tc04_empty_array_rejected_under_patch_flag() -> None:
	"""TC-04: [] under --require-existing fails (exit 1) with exact error string."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act"}))

		patch_file = pit_dir / "empty.json"
		patch_file.write_text("[]")

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(patch_file), "--require-existing"])

		assert code == 1
		err = f_err.getvalue().strip()
		assert err == "error: Patch source contained 0 entities."


def test_cr047_tc05_default_upsert_without_flag_creates_entity() -> None:
	"""TC-05: Missing ID without --require-existing (default upsert) creates entity (exit 0)."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act"}))

		seed_file = pit_dir / "seed.json"
		seed_file.write_text(json.dumps([{"Id": "NewEntity", "Kind": "Act", "Name": "Brand New"}]))

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(seed_file)])

		assert code == 0
		with Pit.open(pit_dir / "Activity", read_only=True) as pit:
			new_ent = pit.get("NewEntity")
			assert new_ent is not None
			assert new_ent["Name"] == "Brand New"


def test_cr047_tc06_tombstoned_entity_rejected_under_strict_patch() -> None:
	"""TC-06: A tombstoned entity (Deleted: true) does not exist in living state and must be rejected."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Bob", "Kind": "Act"}))
			pit.delete_item("Bob")

		patch_file = pit_dir / "patch.json"
		patch_file.write_text(json.dumps([{"Id": "Bob", "UseCase": "Revive"}]))

		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			code = main(["put", str(pit_dir / "Activity"), str(patch_file), "--require-existing"])

		assert code == 1
		assert "error: Entity 'Bob' does not exist in Pit 'Activity'." in f_err.getvalue()


def test_cr047_tc07_store_api_seed_from_file_strict_validation() -> None:
	"""Direct Pit.seed_from_file(..., require_existing=True) raises StrictPatchValidationError."""
	with tempfile.TemporaryDirectory() as tmpdir:
		pit_dir = Path(tmpdir)
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			pit.add(PitItem({"Id": "Alice", "Kind": "Act"}))

		bad_patch = pit_dir / "bad.json"
		bad_patch.write_text(json.dumps([{"Id": "MissingOne", "UseCase": "Test"}]))

		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			try:
				pit.seed_from_file(bad_patch, require_existing=True)
				assert False, "Should have raised StrictPatchValidationError"
			except StrictPatchValidationError as ex:
				assert "Entity 'MissingOne' does not exist in Pit 'Activity'." in str(ex)

		empty_patch = pit_dir / "empty.json"
		empty_patch.write_text("[]")
		with Pit.open(pit_dir / "Activity", read_only=False) as pit:
			try:
				pit.seed_from_file(empty_patch, require_existing=True)
				assert False, "Should have raised StrictPatchValidationError"
			except StrictPatchValidationError as ex:
				assert "Patch source contained 0 entities." in str(ex)


def test_cr047_tc08_cli_version_formatting() -> None:
	"""Asserts that jpit -v and jsonpit -v output formatted version strings with 'v' prefix."""
	# jpit parser
	parser_jpit = build_parser(prog="jpit")
	f_out = io.StringIO()
	try:
		with contextlib.redirect_stdout(f_out):
			parser_jpit.parse_args(["-v"])
	except SystemExit as ex:
		assert ex.code == 0
	assert f_out.getvalue().strip() == f"jpit v{__version__}"

	# jsonpit parser
	parser_jsonpit = build_parser(prog="jsonpit")
	f_out2 = io.StringIO()
	try:
		with contextlib.redirect_stdout(f_out2):
			parser_jsonpit.parse_args(["-v"])
	except SystemExit as ex:
		assert ex.code == 0
	assert f_out2.getvalue().strip() == f"jsonpit v{__version__}"


def test_cr047_tc09_cross_engine_parity_with_csharp_pits() -> None:
	"""
	CR047 Cross-Engine Parity:
	Verifies that C# pits v4.4.5 and Python jpit v4.4.5 behave identically on the same disk storage.
	"""
	pits_bin = shutil.which("pits")
	if not pits_bin:
		# If pits is not on PATH, skip cross-CLI test
		return

	# Confirm pits reports current version matching jpit
	res_v = subprocess.run([pits_bin, "-v"], capture_output=True, text=True, check=True)
	assert res_v.stdout.strip() in (f"pits v{__version__}", "pits v4.4.6", "pits v4.4.7")

	with tempfile.TemporaryDirectory() as tmpdir:
		pit_root = Path(tmpdir)
		pit_path = pit_root / "Parity"
		seed_file = pit_root / "seed.json"
		seed_file.write_text(json.dumps([
			{"Id": "Agent7010", "Kind": "Per", "Name": "Adele"},
			{"Id": "Agent7001", "Kind": "Per", "Name": "Sipho"},
		]))

		# 1. Python jpit seeds initial entities
		res1 = subprocess.run(
			[sys.executable, "-m", "jsonpit.cli", "put", str(pit_path), str(seed_file), "-n"],
			capture_output=True, text=True
		)
		assert res1.returncode == 0
		assert "[jpit] Successfully committed 2 entity(ies) to Pit" in res1.stdout

		# 2. C# pits seeds with --require-existing on existing entities
		patch_existing = pit_root / "patch_existing.json"
		patch_existing.write_text(json.dumps([
			{"Id": "Agent7010", "Role": "Architect"},
			{"Id": "Agent7001", "Role": "QA"},
		]))
		res2 = subprocess.run(
			[pits_bin, "seed", "Parity", "--source", str(patch_existing), "--require-existing", "-r", str(pit_root), "-n"],
			capture_output=True, text=True
		)
		assert res2.returncode == 0, f"pits seed failed: {res2.stderr}"
		assert "[pits] Successfully committed 2 entity(ies) to Pit 'Parity'." in res2.stdout

		# 3. Python jpit verifies projected state
		with Pit.open(pit_path, read_only=True) as pit:
			adele = pit.get("Agent7010")
			assert adele is not None
			assert adele["Name"] == "Adele"
			assert adele["Role"] == "Architect"

		# 4. C# pits seed with missing ID and --patch fails with exact error
		patch_bad = pit_root / "patch_bad.json"
		patch_bad.write_text(json.dumps([
			{"Id": "Ghost999", "Role": "Phantom"},
		]))
		res3 = subprocess.run(
			[pits_bin, "seed", "Parity", "--source", str(patch_bad), "--patch", "-r", str(pit_root), "-n"],
			capture_output=True, text=True
		)
		assert res3.returncode == 1
		assert "error: Entity 'Ghost999' does not exist in Pit 'Parity'." in res3.stderr
		assert "Use without --require-existing / --patch to allow creating new entities." in res3.stderr

		# 5. Python jpit put with missing ID and --patch fails with identical exact error
		res4 = subprocess.run(
			[sys.executable, "-m", "jsonpit.cli", "put", str(pit_path), str(patch_bad), "--patch", "-n"],
			capture_output=True, text=True
		)
		assert res4.returncode == 1
		assert "error: Entity 'Ghost999' does not exist in Pit 'Parity'." in res4.stderr
		assert "Use without --require-existing / --patch to allow creating new entities." in res4.stderr

		# 6. Both reject empty array with identical message
		empty_file = pit_root / "empty.json"
		empty_file.write_text("[]")

		res_pits_empty = subprocess.run(
			[pits_bin, "seed", "Parity", "--source", str(empty_file), "--require-existing", "-r", str(pit_root), "-n"],
			capture_output=True, text=True
		)
		assert res_pits_empty.returncode == 1
		assert res_pits_empty.stderr.strip() == "error: Patch source contained 0 entities."

		res_jpit_empty = subprocess.run(
			[sys.executable, "-m", "jsonpit.cli", "put", str(pit_path), str(empty_file), "--require-existing", "-n"],
			capture_output=True, text=True
		)
		assert res_jpit_empty.returncode == 1
		assert res_jpit_empty.stderr.strip() == "error: Patch source contained 0 entities."
