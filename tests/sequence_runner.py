"""
Minimalist Cross-Engine Sequence Test Runner for jsonpit and pits.

Executes declarative test sequences with Construct/Destruct lifecycles,
delayed convergence polling (eventual consistency), and assertions on
exit code, stdout, stderr, and JSON projections.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonpit.config import loads_json5


@dataclass
class StepResult:
	command: str
	exit_code: int
	stdout: str
	stderr: str
	duration_ms: float
	passed: bool
	error_message: str = ""


@dataclass
class TestCaseResult:
	name: str
	passed: bool
	duration_ms: float
	step_results: list[StepResult] = field(default_factory=list)
	error_message: str = ""


@dataclass
class TestSuiteResult:
	name: str
	total: int
	passed: int
	failed: int
	duration_ms: float
	case_results: list[TestCaseResult] = field(default_factory=list)


def _json_contains(actual: Any, expected: Any) -> bool:
	"""Recursively checks if actual contains all keys and values from expected."""
	if isinstance(expected, dict):
		if not isinstance(actual, dict):
			return False
		for k, v in expected.items():
			if k not in actual:
				return False
			if not _json_contains(actual[k], v):
				return False
		return True
	elif isinstance(expected, list):
		if not isinstance(actual, list) or len(actual) != len(expected):
			return False
		return all(_json_contains(a, e) for a, e in zip(actual, expected))
	else:
		return actual == expected


class SequenceRunner:
	"""Executes declarative test sequences defined in JSON or JSON5."""

	def __init__(self, workspace_root: Path | None = None) -> None:
		self.workspace_root = workspace_root or Path.cwd()

	def execute_step(
		self,
		cmd_str: str,
		variables: dict[str, str],
		expect_code: int = 0,
		expect_stdout: str | list[str] | None = None,
		expect_stderr: str | list[str] | None = None,
		expect_json: Any | None = None,
		timeout_sec: float = 0.0,
		poll_interval_sec: float = 0.2,
	) -> StepResult:
		"""
		Executes a single step with optional polling until convergence or timeout.
		"""
		# Interpolate variables: {root}, {cloud}, etc.
		for k, v in variables.items():
			cmd_str = cmd_str.replace(f"{{{k}}}", v)

		start_time = time.monotonic()
		deadline = start_time + max(0.0, timeout_sec)

		last_code = -1
		last_out = ""
		last_err = ""
		last_err_msg = ""

		while True:
			step_start = time.monotonic()
			sub_env = dict(os.environ)
			ws_str = str(self.workspace_root)
			sub_env["PYTHONPATH"] = ws_str + (os.pathsep + sub_env["PYTHONPATH"] if "PYTHONPATH" in sub_env else "")
			proc = subprocess.run(
				cmd_str,
				shell=True,
				cwd=ws_str,
				capture_output=True,
				text=True,
				env=sub_env,
			)
			step_duration = (time.monotonic() - step_start) * 1000.0

			last_code = proc.returncode
			last_out = proc.stdout
			last_err = proc.stderr

			# Evaluate assertions
			passed = True
			last_err_msg = ""

			if last_code != expect_code:
				passed = False
				last_err_msg = f"Expected exit code {expect_code}, got {last_code}."

			if passed and expect_stdout is not None:
				expected_list = [expect_stdout] if isinstance(expect_stdout, str) else expect_stdout
				for needle in expected_list:
					if needle not in last_out:
						passed = False
						last_err_msg = f"Expected stdout to contain: {needle!r}."
						break

			if passed and expect_stderr is not None:
				expected_list = [expect_stderr] if isinstance(expect_stderr, str) else expect_stderr
				for needle in expected_list:
					if needle not in last_err:
						passed = False
						last_err_msg = f"Expected stderr to contain: {needle!r}."
						break

			if passed and expect_json is not None:
				try:
					parsed_json = json.loads(last_out)
					if not _json_contains(parsed_json, expect_json):
						passed = False
						last_err_msg = f"JSON output does not match expected subset: {expect_json}."
				except Exception as ex:
					passed = False
					last_err_msg = f"Failed to parse stdout as JSON: {ex}."

			if passed:
				total_duration = (time.monotonic() - start_time) * 1000.0
				return StepResult(
					command=cmd_str,
					exit_code=last_code,
					stdout=last_out,
					stderr=last_err,
					duration_ms=total_duration,
					passed=True,
				)

			# If timeout was configured and we have time left, poll
			now = time.monotonic()
			if timeout_sec > 0 and now < deadline:
				time.sleep(poll_interval_sec)
				continue
			else:
				break

		total_duration = (time.monotonic() - start_time) * 1000.0
		return StepResult(
			command=cmd_str,
			exit_code=last_code,
			stdout=last_out,
			stderr=last_err,
			duration_ms=total_duration,
			passed=False,
			error_message=last_err_msg,
		)

	def run_suite(self, suite_path: Path | str) -> TestSuiteResult:
		"""Loads a suite from JSON5 or JSON and runs Construct, Tests, Destruct."""
		path = Path(suite_path)
		content = path.read_text(encoding="utf-8")
		data = loads_json5(content)

		suite_name = data.get("Name", path.stem)
		construct_steps = data.get("Construct", [])
		destruct_steps = data.get("Destruct", [])
		test_cases = data.get("Tests", [])

		# Determine or allocate root
		temp_dir: tempfile.TemporaryDirectory[str] | None = None
		root_var = data.get("Root")
		if not root_var or root_var == "TEMP":
			temp_dir = tempfile.TemporaryDirectory(prefix="jpit_parity_")
			root_val = temp_dir.name
		else:
			root_val = root_var

		variables = {
			"root": root_val,
			"cloud": data.get("Cloud", "OneDrive"),
		}
		for k, v in data.get("Variables", {}).items():
			variables[k] = str(v)

		suite_start = time.monotonic()
		case_results: list[TestCaseResult] = []

		try:
			# 1. Construct
			for cmd in construct_steps:
				cmd_str = cmd if isinstance(cmd, str) else cmd.get("Command", "")
				for k, v in variables.items():
					cmd_str = cmd_str.replace(f"{{{k}}}", v)
				subprocess.run(cmd_str, shell=True, cwd=str(self.workspace_root), check=False)

			# 2. Tests
			for tc in test_cases:
				tc_name = tc.get("Name", "Unnamed Test")
				tc_start = time.monotonic()
				tc_passed = True
				tc_error = ""
				step_results: list[StepResult] = []

				# If simple test with single Command
				steps_def = tc.get("Steps")
				if steps_def is None and "Command" in tc:
					steps_def = [tc]

				for step_data in steps_def or []:
					cmd = step_data.get("Command", "")
					res = self.execute_step(
						cmd_str=cmd,
						variables=variables,
						expect_code=step_data.get("ExpectCode", 0),
						expect_stdout=step_data.get("ExpectStdout") or step_data.get("ExpectStdoutContains"),
						expect_stderr=step_data.get("ExpectStderr") or step_data.get("ExpectStderrContains"),
						expect_json=step_data.get("ExpectJson"),
						timeout_sec=step_data.get("Timeout", 0.0),
						poll_interval_sec=step_data.get("PollInterval", 0.2),
					)
					step_results.append(res)
					if not res.passed:
						tc_passed = False
						tc_error = f"Step failed: {res.command}\n  -> {res.error_message}"
						if res.stderr.strip():
							tc_error += f"\n  -> stderr: {res.stderr.strip()}"
						if res.stdout.strip():
							tc_error += f"\n  -> stdout: {res.stdout.strip()}"
						break

				tc_duration = (time.monotonic() - tc_start) * 1000.0
				case_results.append(
					TestCaseResult(
						name=tc_name,
						passed=tc_passed,
						duration_ms=tc_duration,
						step_results=step_results,
						error_message=tc_error,
					)
				)

		finally:
			# 3. Destruct
			for cmd in destruct_steps:
				cmd_str = cmd if isinstance(cmd, str) else cmd.get("Command", "")
				for k, v in variables.items():
					cmd_str = cmd_str.replace(f"{{{k}}}", v)
				subprocess.run(cmd_str, shell=True, cwd=str(self.workspace_root), check=False)

			if temp_dir is not None:
				temp_dir.cleanup()

		suite_duration = (time.monotonic() - suite_start) * 1000.0
		passed_count = sum(1 for c in case_results if c.passed)
		failed_count = len(case_results) - passed_count

		return TestSuiteResult(
			name=suite_name,
			total=len(case_results),
			passed=passed_count,
			failed=failed_count,
			duration_ms=suite_duration,
			case_results=case_results,
		)


def print_suite_report(result: TestSuiteResult) -> None:
	"""Renders a clean human-readable terminal report."""
	print(f"\n\033[1m=== TestSuite: {result.name} ===\033[0m")
	print(f"Total: {result.total}  Passed: {result.passed}  Failed: {result.failed}  Time: {result.duration_ms:.1f}ms\n")

	for tc in result.case_results:
		if tc.passed:
			print(f"  \033[32m[PASS]\033[0m {tc.name:<40} ({tc.duration_ms:.1f}ms)")
		else:
			print(f"  \033[31m[FAIL]\033[0m {tc.name:<40} ({tc.duration_ms:.1f}ms)")
			if tc.error_message:
				for line in tc.error_message.splitlines():
					print(f"         \033[31m{line}\033[0m")
	print()


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: python -m tests.sequence_runner <suite_file.json5>")
		sys.exit(1)

	suite_file = sys.argv[1]
	runner = SequenceRunner()
	res = runner.run_suite(suite_file)
	print_suite_report(res)
	sys.exit(0 if res.failed == 0 else 1)
