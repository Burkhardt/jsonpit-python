"""
Discovers and executes all declarative cross-engine parity suites in tests/suites/.
"""

from __future__ import annotations

import shutil
import os
from pathlib import Path

from tests.sequence_runner import SequenceRunner

SUITES_DIR = Path(__file__).resolve().parent / "suites"


def test_declarative_parity_suites() -> None:
	"""Runs destructive cloud-backed parity suites only when explicitly requested."""
	if os.getenv("RAIKEEP_RUN_SEQUENCE_SUITES") != "1":
		return
	if not shutil.which("pits") or not shutil.which("jpit"):
		return

	runner = SequenceRunner()
	for suite_file in sorted(SUITES_DIR.glob("*.json5")):
		res = runner.run_suite(suite_file)
		assert res.failed == 0, f"Suite '{res.name}' had {res.failed} failure(s)."
