"""
Unit and integration tests for the jpit developer CLI and Pit-Grep engine.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jsonpit.cli import main

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "Person.pit"


class _CaptureResult:
	def __init__(self, out: str, err: str) -> None:
		self.out = out
		self.err = err


@contextlib.contextmanager
def _capture_output(capsys: Any = None) -> Any:
	if capsys is not None:
		yield capsys
	else:
		f_out = io.StringIO()
		f_err = io.StringIO()
		with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
			yield _CaptureResult(f_out.getvalue(), f_err.getvalue())


def test_cli_list_command(capsys: Any = None) -> None:
	f_out = io.StringIO()
	f_err = io.StringIO()
	with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
		code = main(["list", str(FIXTURE_PATH)])
	assert code == 0
	out = f_out.getvalue()
	assert "Adele" in out
	assert "7010" in out
	assert "Dr. Rainer Burkhardt" in out


def test_cli_get_command(capsys: Any = None) -> None:
	f_out = io.StringIO()
	f_err = io.StringIO()
	with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
		code = main(["get", str(FIXTURE_PATH), "7010"])
	assert code == 0
	data = json.loads(f_out.getvalue())
	assert data["Name"] == "Adele"
	assert data["Class"] == "Agent"


def test_cli_grep_living_state(capsys: Any = None) -> None:
	f_out = io.StringIO()
	f_err = io.StringIO()
	with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
		code = main(["grep", str(FIXTURE_PATH), "Smalltalk"])
	assert code == 0
	out = f_out.getvalue()
	assert "Adele" in out
	assert "Alan" in out


def test_cli_grep_json_output(capsys: Any = None) -> None:
	f_out = io.StringIO()
	f_err = io.StringIO()
	with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
		code = main(["grep", str(FIXTURE_PATH), "Goldberg", "--json"])
	assert code == 0
	results = json.loads(f_out.getvalue())
	assert len(results) >= 1
	assert any(r["Id"] == "7010" and r["Name"] == "Adele" for r in results)


def test_cli_put_and_set_lifecycle(capsys: Any = None) -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_path = Path(td) / "TestPit.pit"

		# Ingest JSON5 via set
		f_out = io.StringIO()
		with contextlib.redirect_stdout(f_out):
			code = main(["set", str(pit_path), "User1", "{ Name: 'Alice', Role: 'Architect' }"])
		assert code == 0

		# Verify get
		f_out = io.StringIO()
		with contextlib.redirect_stdout(f_out):
			code = main(["get", str(pit_path), "User1"])
		assert code == 0
		data = json.loads(f_out.getvalue())
		assert data["Name"] == "Alice"
		assert data["Role"] == "Architect"

		# Tombstone entity
		f_out = io.StringIO()
		with contextlib.redirect_stdout(f_out):
			code = main(["del", str(pit_path), "User1", "--by", "Adele"])
		assert code == 0

		# Should now be deleted
		f_err = io.StringIO()
		with contextlib.redirect_stderr(f_err):
			code = main(["get", str(pit_path), "User1"])
		assert code == 1


def test_cli_status_command(capsys: Any = None) -> None:
	f_out = io.StringIO()
	with contextlib.redirect_stdout(f_out):
		code = main(["status", str(FIXTURE_PATH)])
	assert code == 0
	out = f_out.getvalue()
	assert "Pit Status" in out
	assert "Master Lease" in out


def test_cli_version_flag(capsys: Any = None) -> None:
	f_out = io.StringIO()
	try:
		with contextlib.redirect_stdout(f_out):
			main(["-v"])
	except SystemExit as ex:
		assert ex.code == 0
	from jsonpit import __version__
	assert __version__ in f_out.getvalue()


def test_cli_flexible_option_placement(capsys: Any = None) -> None:
	# Leading option: jpit -r AIA grep Adele <pit>
	f_out1 = io.StringIO()
	with contextlib.redirect_stdout(f_out1):
		code1 = main(["-r", "AIA", "grep", "Adele", str(FIXTURE_PATH)])
	assert code1 == 0
	assert "Adele" in f_out1.getvalue()

	# Trailing option: jpit grep Adele <pit> --root AIA
	f_out2 = io.StringIO()
	with contextlib.redirect_stdout(f_out2):
		code2 = main(["grep", "Adele", str(FIXTURE_PATH), "--root", "AIA"])
	assert code2 == 0
	assert "Adele" in f_out2.getvalue()


def test_read_operation_never_creates_directories(capsys: Any = None) -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		non_existent_pit = Path(tmp_dir) / "GhostPit"
		assert not non_existent_pit.exists()

		f_err = io.StringIO()
		with contextlib.redirect_stderr(f_err):
			code = main(["get", str(non_existent_pit), "GhostEntity"])
		assert code == 1
		assert not non_existent_pit.exists(), "Read operation must never create ghost directory!"

		with contextlib.redirect_stderr(f_err):
			code = main(["grep", "Ghost", str(non_existent_pit)])
		assert code == 1
		assert not non_existent_pit.exists(), "Grep must never create ghost directory!"


def test_disallow_manual_modified_or_deleted(capsys: Any = None) -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		# Setting Deleted must fail
		f_err1 = io.StringIO()
		with contextlib.redirect_stderr(f_err1):
			code1 = main(["set", str(pit_dir), "Item1", '{"Deleted": true}'])
		assert code1 == 1
		assert "Use 'jpit del'" in f_err1.getvalue()

		# Setting Modified must fail
		f_err2 = io.StringIO()
		with contextlib.redirect_stderr(f_err2):
			code2 = main(["set", str(pit_dir), "Item1", '{"Modified": "2026-01-01T00:00:00Z"}'])
		assert code2 == 1
		assert "Cannot manually update protected attribute 'Modified'" in f_err2.getvalue()

		# del-prop on protected attribute must fail
		f_err3 = io.StringIO()
		with contextlib.redirect_stderr(f_err3):
			code3 = main(["del-prop", str(pit_dir), "Item1", "Deleted"])
		assert code3 == 1
		assert "Cannot tombstone protected attribute 'Deleted'" in f_err3.getvalue()


def test_cli_pits_discovery_and_delegation() -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		root = Path(tmp_dir)
		# Create four mock pits to test positional color sequence
		(root / "PitAlpha").mkdir()
		(root / "PitAlpha" / "PitAlpha.pit").write_text("{}", encoding="utf-8")
		(root / "PitBeta").mkdir()
		(root / "PitBeta" / "PitBeta.pit").write_text("{}", encoding="utf-8")
		(root / "PitGamma").mkdir()
		(root / "PitGamma" / "PitGamma.pit").write_text("{}", encoding="utf-8")
		(root / "PitDelta").mkdir()
		(root / "PitDelta" / "PitDelta.pit").write_text("{}", encoding="utf-8")

		# 1. Test jpit pits -r <root>
		f_out = io.StringIO()
		with contextlib.redirect_stdout(f_out):
			code = main(["pits", "-r", str(root)])
		assert code == 0
		out = f_out.getvalue()
		assert "PitAlpha" in out
		assert "PitBeta" in out
		assert "PitGamma" in out
		assert "PitDelta" in out

		# 2. Test jpit pits -r <root> --json
		f_out_json = io.StringIO()
		with contextlib.redirect_stdout(f_out_json):
			code = main(["pits", "-r", str(root), "--json"])
		assert code == 0
		data = json.loads(f_out_json.getvalue())
		assert data == ["PitAlpha", "PitBeta", "PitDelta", "PitGamma"]

		# 3. Test jpit list -r <root> delegation
		f_out_list = io.StringIO()
		with contextlib.redirect_stdout(f_out_list):
			code = main(["list", "-r", str(root)])
		assert code == 0
		assert "PitAlpha" in f_out_list.getvalue()

		# 4. Test jpit -r <root> -h dynamic help line with positional colors
		f_out_help = io.StringIO()
		old_term = os.environ.get("TERM")
		try:
			os.environ["TERM"] = "xterm-256color"
			with contextlib.redirect_stdout(f_out_help):
				code = main(["-r", str(root), "-h"])
		finally:
			if old_term is None:
				os.environ.pop("TERM", None)
			else:
				os.environ["TERM"] = old_term

		assert code == 0
		help_out = f_out_help.getvalue()
		assert "PitNames" in help_out
		assert f"(current: {root})" in help_out
		assert "PitAlpha" in help_out
		assert "PitBeta" in help_out
		# 3rd option (idx 2) is blue (\033[94m), 4th option (idx 3) is red (\033[91m)
		from jsonpit.cli import C_BRIGHT_BLUE, C_BRIGHT_RED
		assert C_BRIGHT_BLUE in help_out
		assert C_BRIGHT_RED in help_out

		# 5. Verify main help does NOT display (CR024)
		assert "(CR024)" not in help_out

		# 6. Verify jpit --retain-window -h detailed help and hyperlinks
		f_out_rw = io.StringIO()
		with contextlib.redirect_stdout(f_out_rw):
			code_rw = main(["--retain-window", "-h"])
		assert code_rw == 0
		rw_out = f_out_rw.getvalue()
		assert "Option:    --retain-window" in rw_out
		assert "CR024" in rw_out
		assert "doc/CR/CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md:45" in rw_out
		assert "#L45" in rw_out
		assert "#3---retain-window-compatibility-exception" in rw_out


