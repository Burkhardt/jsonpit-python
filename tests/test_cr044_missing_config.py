"""
CR044 Acceptance Tests: Missing Configuration Diagnostic and amafu init guidance.
Specification: doc/CR/CR044_AIA_and_jsonpit_to_RAIkeep_Auto-Detect-Cloud-Drives-and-Init-Config.md (§7.4)
Reference: RAIkeep/PitSeeder v4.4.4 (feat: direct missing configuration to Amafu)
"""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from jsonpit import (
	DEFAULT_CONFIG_FILE_LOCATION,
	OsConfig,
	Pit,
	PitItem,
	PitNotFoundError,
	missing_configuration_diagnostic,
)
from jsonpit.cli import main as cli_main


def test_missing_configuration_diagnostic_string() -> None:
	"""Verifies the exact diagnostic string matches C# reference verbatim."""
	expected = (
		"RAIkeep configuration was not found at '~/.config/RAIkeep.json5'. "
		"Run 'amafu init' to detect cloud providers and create it."
	)
	assert missing_configuration_diagnostic() == expected
	assert DEFAULT_CONFIG_FILE_LOCATION == "~/.config/RAIkeep.json5"


def test_missing_config_directs_operator_to_amafu() -> None:
	"""
	CR044 §7.4: When no configuration file exists and no environment overrides are set,
	attempting to open a cloud-scoped pit or running jpit commands without an explicit path
	fails with the exact diagnostic directing the operator to 'amafu init'.
	"""
	with patch.dict("os.environ", {}, clear=True), patch.object(OsConfig, "find_config_file", return_value=None):
		OsConfig.reset()
		try:
			# 1. Programmatic API test
			try:
				Pit.open("Person", cloud="OneDrive", root="AfricaStage")
				assert False, "Pit.open should have raised PitNotFoundError when config is missing"
			except PitNotFoundError as ex:
				expected = (
					"RAIkeep configuration was not found at '~/.config/RAIkeep.json5'. "
					"Run 'amafu init' to detect cloud providers and create it."
				)
				assert str(ex) == expected

			# 2. CLI commands test (get, list, pits, grep)
			expected_msg = (
				"RAIkeep configuration was not found at '~/.config/RAIkeep.json5'. "
				"Run 'amafu init' to detect cloud providers and create it."
			)

			commands = [
				["get", "Person", "Item1", "-n"],
				["list", "Person", "-n"],
				["pits", "-r", "AIA", "-n"],
				["grep", "test", "Person", "-n"],
			]

			for cmd in commands:
				stderr_buf = io.StringIO()
				with patch("sys.stderr", stderr_buf):
					exit_code = cli_main(cmd)
				assert exit_code == 1, f"Command {cmd} should have failed with exit code 1"
				err_output = stderr_buf.getvalue()
				assert expected_msg in err_output, (
					f"Command {cmd} output did not contain expected diagnostic.\nOutput: {err_output}"
				)
		finally:
			OsConfig.reset()


def test_explicit_paths_work_without_config() -> None:
	"""
	CR044 Invariant: Explicit filesystem paths operate cleanly without requiring
	~/.config/RAIkeep.json5.
	"""
	temp_dir = Path(tempfile.mkdtemp(prefix="jsonpit_cr044_explicit_"))
	try:
		pit_dir = temp_dir / "LocalPit"

		with patch.dict("os.environ", {}, clear=True), patch.object(OsConfig, "find_config_file", return_value=None):
			OsConfig.reset()
			try:
				# Programmatic API with explicit path
				with Pit.open(pit_dir) as pit:
					item = PitItem({"Id": "Item1", "Name": "Local Entity"})
					pit.add(item)
					assert len(pit) == 1

				# Re-open and verify persistence
				with Pit.open(pit_dir) as pit:
					loaded = pit.get("Item1")
					assert loaded is not None
					assert loaded["Name"] == "Local Entity"

				# CLI commands with explicit path
				stdout_buf = io.StringIO()
				with patch("sys.stdout", stdout_buf):
					exit_code = cli_main(["list", str(pit_dir), "--json", "-n"])
				assert exit_code == 0
				assert "Item1" in stdout_buf.getvalue()

				stdout_buf = io.StringIO()
				with patch("sys.stdout", stdout_buf):
					exit_code = cli_main(["grep", "Local Entity", str(pit_dir), "--json", "-n"])
				assert exit_code == 0
				assert "Item1" in stdout_buf.getvalue()
			finally:
				OsConfig.reset()
	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)
