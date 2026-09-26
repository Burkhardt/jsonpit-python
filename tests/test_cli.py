"""
Unit and integration tests for the jpit developer CLI and Pit-Grep engine.
"""

from __future__ import annotations

import contextlib
import io
import json
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
	assert "0.1.1" in f_out.getvalue()
