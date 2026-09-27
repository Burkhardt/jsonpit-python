"""
Discovers and executes all declarative cross-engine parity suites in tests/suites/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.sequence_runner import SequenceRunner

SUITES_DIR = Path(__file__).resolve().parent / "suites"


def test_declarative_parity_suites() -> None:
	"""Runs all JSON5 sequence suites if pits and jpit are present on PATH."""
	if not shutil.which("pits") or not shutil.which("jpit"):
		return

	runner = SequenceRunner()
	for suite_file in sorted(SUITES_DIR.glob("*.json5")):
		res = runner.run_suite(suite_file)
		assert res.failed == 0, f"Suite '{res.name}' had {res.failed} failure(s)."
