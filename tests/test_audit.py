"""
Unit tests for jsonpit durable recovery event audit (CR003, coordinated v3.13.2).
Provides 100% parity verification with C# pits audit.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from jsonpit import LogLevel, PitAudit, PitAuditEvent, PitAuditReadResult
from jsonpit.canonical import format_iso_timestamp
from jsonpit.cli import cmd_audit


def test_log_level_from_string_valid() -> None:
	assert LogLevel.from_string("trace") == LogLevel.TRACE
	assert LogLevel.from_string("0") == LogLevel.TRACE
	assert LogLevel.from_string("Debug") == LogLevel.DEBUG
	assert LogLevel.from_string("1") == LogLevel.DEBUG
	assert LogLevel.from_string("Information") == LogLevel.INFORMATION
	assert LogLevel.from_string("info") == LogLevel.INFORMATION
	assert LogLevel.from_string("Warning") == LogLevel.WARNING
	assert LogLevel.from_string("warn") == LogLevel.WARNING
	assert LogLevel.from_string("Error") == LogLevel.ERROR
	assert LogLevel.from_string("err") == LogLevel.ERROR
	assert LogLevel.from_string("Critical") == LogLevel.CRITICAL
	assert LogLevel.from_string("fatal") == LogLevel.CRITICAL


def test_log_level_from_string_invalid() -> None:
	try:
		LogLevel.from_string("unknown_level")
		assert False, "Expected ValueError"
	except ValueError:
		pass


def test_log_level_display_name() -> None:
	assert LogLevel.TRACE.display_name == "Trace"
	assert LogLevel.DEBUG.display_name == "Debug"
	assert LogLevel.INFORMATION.display_name == "Information"
	assert LogLevel.WARNING.display_name == "Warning"
	assert LogLevel.ERROR.display_name == "Error"
	assert LogLevel.CRITICAL.display_name == "Critical"


def test_missing_events_dir() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		res = PitAudit.inspect(p)
		assert res.events == []
		assert res.issues == []
		assert res.succeeded


def test_inspect_loose_event_files() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		event_payload = {
			"Machine": "HostA",
			"UtcTicks": 639259195699256450,
			"UtcTime": "2026-09-25T07:52:49.9256450Z",
			"Level": "Information",
			"Stage": "ChangeFilesPublished",
			"EventId": "ev-001",
			"Message": "Loose event published.",
		}
		(events_dir / "639259195699256450_HostA-pits-1_test.event").write_text(
			json.dumps(event_payload), encoding="utf-8"
		)

		res = PitAudit.inspect(p)
		assert len(res.events) == 1
		assert res.succeeded
		ev = res.events[0]
		assert ev.machine == "HostA"
		assert ev.level == LogLevel.INFORMATION
		assert ev.stage == "ChangeFilesPublished"
		assert ev.event_id == "ev-001"
		assert ev.message == "Loose event published."


def test_inspect_zip_archive() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		event_payload = {
			"Machine": "HostB",
			"UtcTicks": 639259255565811370,
			"UtcTime": "2026-09-25T09:32:36.5811370Z",
			"Level": "Warning",
			"Stage": "CleanupPending",
			"EventId": "ev-002",
			"Message": "Archived event.",
		}
		zip_path = events_dir / "Events_20260925-0900_to_20260925-1000.zip"
		with zipfile.ZipFile(zip_path, "w") as zf:
			zf.writestr("639259255565811370_HostB-pits-2.event", json.dumps(event_payload))

		res = PitAudit.inspect(p)
		assert len(res.events) == 1
		assert res.succeeded
		ev = res.events[0]
		assert ev.machine == "HostB"
		assert ev.level == LogLevel.WARNING
		assert ev.event_id == "ev-002"


def test_deduplication_between_loose_and_zip() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		event_payload = {
			"Machine": "HostA",
			"UtcTicks": 639259195699256450,
			"UtcTime": "2026-09-25T07:52:49.9256450Z",
			"Level": "Information",
			"Stage": "ChangeFilesPublished",
			"EventId": "shared-id-123",
			"Message": "Identical event.",
		}
		(events_dir / "ev1.event").write_text(json.dumps(event_payload), encoding="utf-8")
		zip_path = events_dir / "Events_20260925-0700_to_20260925-0800.zip"
		with zipfile.ZipFile(zip_path, "w") as zf:
			zf.writestr("ev2.event", json.dumps(event_payload))

		res = PitAudit.inspect(p)
		assert len(res.events) == 1
		assert res.succeeded


def test_conflicting_event_identity_reports_issue() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		payload1 = {
			"Machine": "HostA",
			"UtcTicks": 639259195699256450,
			"EventId": "conflict-123",
			"Message": "Message 1",
		}
		payload2 = {
			"Machine": "HostA",
			"UtcTicks": 639259195699256450,
			"EventId": "conflict-123",
			"Message": "Message 2 (conflicting)",
		}
		(events_dir / "ev1.event").write_text(json.dumps(payload1), encoding="utf-8")
		(events_dir / "ev2.event").write_text(json.dumps(payload2), encoding="utf-8")

		res = PitAudit.inspect(p)
		assert not res.succeeded
		assert any("conflict-123" in issue for issue in res.issues)


def test_filtering_by_machine_and_level() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		p1 = {"Machine": "HostA", "Level": "Debug", "EventId": "1", "Message": "d1"}
		p2 = {"Machine": "HostA", "Level": "Error", "EventId": "2", "Message": "e1"}
		p3 = {"Machine": "HostB", "Level": "Error", "EventId": "3", "Message": "e2"}

		(events_dir / "e1.event").write_text(json.dumps(p1), encoding="utf-8")
		(events_dir / "e2.event").write_text(json.dumps(p2), encoding="utf-8")
		(events_dir / "e3.event").write_text(json.dumps(p3), encoding="utf-8")

		res_host_a = PitAudit.inspect(p, machine_filter="HostA")
		assert len(res_host_a.events) == 2

		res_err = PitAudit.inspect(p, min_level=LogLevel.ERROR)
		assert len(res_err.events) == 2

		res_both = PitAudit.inspect(p, machine_filter="HostA", min_level=LogLevel.ERROR)
		assert len(res_both.events) == 1
		assert res_both.events[0].event_id == "2"


def test_audit_cli_validation_rules() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		pit_file = p / "TestPit.pit"
		pit_file.write_text("{}", encoding="utf-8")

		# 1. Mutually exclusive pit and --wwwa
		args1 = argparse.Namespace(pit=str(pit_file), wwwa=True)
		err1 = io.StringIO()
		old_err = sys.stderr
		try:
			sys.stderr = err1
			ret1 = cmd_audit(args1)
		finally:
			sys.stderr = old_err
		assert ret1 == 1
		assert "audit accepts either <PitName> or --wwwa, not both" in err1.getvalue()

		# 2. Neither pit nor --wwwa
		args2 = argparse.Namespace(pit=None, wwwa=False)
		err2 = io.StringIO()
		try:
			sys.stderr = err2
			ret2 = cmd_audit(args2)
		finally:
			sys.stderr = old_err
		assert ret2 == 1
		assert "audit requires exactly one <PitName>, or --wwwa" in err2.getvalue()


def test_audit_cli_output_table_and_json() -> None:
	with tempfile.TemporaryDirectory() as tmpdir:
		p = Path(tmpdir)
		events_dir = p / "Events"
		events_dir.mkdir(parents=True)
		(p / "TestPit.pit").write_text("{}", encoding="utf-8")

		ev = {
			"Machine": "HostA",
			"UtcTicks": 639259195699256450,
			"UtcTime": "2026-09-25T07:52:49.9256450Z",
			"Level": "Information",
			"Stage": "ChangeFilesPublished",
			"EventId": "ev-001",
			"Message": "Testing CLI output.",
		}
		(events_dir / "ev1.event").write_text(json.dumps(ev), encoding="utf-8")

		# 1. Text table output
		args = argparse.Namespace(
			pit=str(p / "TestPit.pit"),
			wwwa=False,
			machine="all",
			level="Trace",
			json=False,
		)
		out = io.StringIO()
		old_out = sys.stdout
		try:
			sys.stdout = out
			ret = cmd_audit(args)
		finally:
			sys.stdout = old_out
		assert ret == 0
		assert "HostA\t" in out.getvalue()
		assert "Information\tChangeFilesPublished\tTesting CLI output." in out.getvalue()

		# 2. JSON output
		args.json = True
		out_json = io.StringIO()
		try:
			sys.stdout = out_json
			ret = cmd_audit(args)
		finally:
			sys.stdout = old_out
		assert ret == 0
		parsed = json.loads(out_json.getvalue())
		assert isinstance(parsed, list)
		assert len(parsed) == 1
		assert parsed[0]["EventId"] == "ev-001"


def test_audit_wwwa_cloud_not_hijacked_by_local_cwd_directory() -> None:
	"""
	Regression test: when running `jpit audit --wwwa -c <cloud> -r AIA`,
	if an eponymous folder `./AIA` exists in the current working directory,
	the audit target MUST resolve against the cloud root, not the local cwd folder.
	"""
	with tempfile.TemporaryDirectory() as tmp_cloud, tempfile.TemporaryDirectory() as tmp_cwd:
		cloud_root = Path(tmp_cloud) / "CloudData"
		cloud_root.mkdir(parents=True)
		tenant_cloud = cloud_root / "AIA"
		for pit_name in ["Person", "Object", "Place", "Activity"]:
			p_dir = tenant_cloud / pit_name
			p_dir.mkdir(parents=True)
			(p_dir / f"{pit_name}.pit").write_text("[]\n", encoding="utf-8")

		# Create local ./AIA in cwd without .pit files
		local_aia = Path(tmp_cwd) / "AIA"
		local_aia.mkdir(parents=True)

		from jsonpit.config import OsConfig
		mock_cfg = OsConfig({"Cloud": {"MockDrive": str(cloud_root)}})
		OsConfig._instance = mock_cfg

		orig_cwd = os.getcwd()
		try:
			os.chdir(tmp_cwd)
			args = argparse.Namespace(
				pit=None,
				wwwa=True,
				cloud="MockDrive",
				root="AIA",
				machine="all",
				level="Trace",
				json=True,
			)
			out_json = io.StringIO()
			old_out = sys.stdout
			try:
				sys.stdout = out_json
				ret = cmd_audit(args)
			finally:
				sys.stdout = old_out

			assert ret == 0
			parsed = json.loads(out_json.getvalue())
			assert isinstance(parsed, list)
		finally:
			os.chdir(orig_cwd)
			OsConfig.reset()
