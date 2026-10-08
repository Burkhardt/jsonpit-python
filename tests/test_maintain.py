"""
Unit tests for Pit maintenance and CLI parity (CR021/CR022).
Verifies report-only dry-runs, apply reconciliation, 10-minute receipt grace periods,
process flag pruning with --older-than, legacy event repairs, and JSON schema output.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import tempfile

from jsonpit.canonical import format_iso_timestamp, utcnow
from jsonpit.changes import ChangeFile, ReceiptFile
from jsonpit.cli import cmd_maintain, main, parse_duration
from jsonpit.flags import MasterFlagFile, ProcessFlagFile, TimestampedValue
from jsonpit.item import PitItem
from jsonpit.store import Pit, PitMaintenanceOptions, PitMaintenanceResult


def test_parse_duration() -> None:
	# Standard .NET TimeSpan formats
	assert parse_duration("01:00:00") == datetime.timedelta(hours=1)
	assert parse_duration("7.00:00:00") == datetime.timedelta(days=7)
	assert parse_duration("00:10:00") == datetime.timedelta(minutes=10)
	assert parse_duration("00:00:30") == datetime.timedelta(seconds=30)
	assert parse_duration("1:30:00") == datetime.timedelta(hours=1, minutes=30)

	# Suffix forms
	assert parse_duration("1h") == datetime.timedelta(hours=1)
	assert parse_duration("7d") == datetime.timedelta(days=7)
	assert parse_duration("10m") == datetime.timedelta(minutes=10)
	assert parse_duration("30s") == datetime.timedelta(seconds=30)

	# Raw integer seconds
	assert parse_duration("3600") == datetime.timedelta(seconds=3600)

	# Validation failures
	for invalid in ["", "0", "-1h", "00:00:00", "invalid", "xyz"]:
		try:
			parse_duration(invalid)
			assert False, f"Expected ValueError for '{invalid}'"
		except ValueError:
			pass


def test_maintain_dry_run_report_only() -> None:
	with tempfile.TemporaryDirectory() as tmp:
		pit_dir = Path(tmp) / "TestPit"
		pit_dir.mkdir(parents=True)
		canonical = pit_dir / "TestPit.pit"
		canonical.write_text("[]\n", encoding="utf-8")

		# Create an expired process flag
		old_time = utcnow() - datetime.timedelta(hours=2)
		flag_file = pit_dir / "Host-Proc-1234.flag"
		flag_file.write_text(str(TimestampedValue("Host-Proc-1234", old_time)) + "\n", encoding="utf-8")

		# Create a pending change file using ChangeFile.create
		change_item = PitItem({"Id": "item-1", "Name": "DryRun"})
		cf_file = ChangeFile.create(pit_dir, change_item, "Host-Proc-1234")

		with Pit.open(pit_dir, read_only=True, unflagged=True) as pit:
			res = pit.maintain(apply=False)

		assert res.applied is False
		assert res.succeeded is True
		assert res.change_files_observed == 1
		assert res.change_files_merged == 1
		assert res.change_files_removed == 0
		assert res.process_flags_expired == 1
		assert res.process_flags_pruned == 0

		# On disk, nothing was removed or modified
		assert cf_file.is_file()
		assert flag_file.is_file()
		assert canonical.read_text(encoding="utf-8") == "[]\n"


def test_maintain_apply_reconciliation_and_receipt_grace() -> None:
	with tempfile.TemporaryDirectory() as tmp:
		pit_dir = Path(tmp) / "TestPit"
		pit_dir.mkdir(parents=True)
		canonical = pit_dir / "TestPit.pit"
		canonical.write_text("[]\n", encoding="utf-8")

		change_item = PitItem({"Id": "item-abc", "Status": "Active"})
		cf_file = ChangeFile.create(pit_dir, change_item, "Host-Proc-5555")

		# First apply: merges change, persists canonical, creates receipt
		with Pit.open(pit_dir, unflagged=True, autoload=False) as pit:
			res1 = pit.maintain(apply=True)

		assert res1.applied is True
		assert res1.canonical_persisted is True
		assert res1.receipts_created == 1
		assert res1.change_files_removed == 0  # Grace period active

		receipt_file = cf_file.with_suffix(".receipt")
		assert receipt_file.is_file()
		assert cf_file.is_file()

		# Backdate receipt past the 10-minute grace period
		past_time = utcnow() - datetime.timedelta(minutes=11)
		receipt_file.write_text(f"{format_iso_timestamp(past_time)}\n", encoding="utf-8")

		# Second apply: grace period expired, both change file and receipt pruned
		with Pit.open(pit_dir, unflagged=True, autoload=False) as pit:
			res2 = pit.maintain(apply=True)

		assert res2.applied is True
		assert res2.change_files_removed == 1
		assert res2.receipts_removed == 1
		assert not cf_file.exists()
		assert not receipt_file.exists()


def test_maintain_prune_process_flags() -> None:
	with tempfile.TemporaryDirectory() as tmp:
		pit_dir = Path(tmp) / "TestPit"
		pit_dir.mkdir(parents=True)
		canonical = pit_dir / "TestPit.pit"
		canonical.write_text("[]\n", encoding="utf-8")

		now = utcnow()

		# 1. Master.flag (must never be pruned)
		m_flag = pit_dir / "Master.flag"
		m_flag.write_text(str(TimestampedValue("MasterHost", now)) + "\n", encoding="utf-8")

		# 2. Active process flag (now - 10s)
		active_flag = pit_dir / "Host-Proc-1111.flag"
		active_flag.write_text(str(TimestampedValue("Host-Proc-1111", now - datetime.timedelta(seconds=10))) + "\n", encoding="utf-8")

		# 3. Expired process flag younger than 1h (now - 15m)
		young_expired = pit_dir / "Host-Proc-2222.flag"
		young_expired.write_text(str(TimestampedValue("Host-Proc-2222", now - datetime.timedelta(minutes=15))) + "\n", encoding="utf-8")

		# 4. Expired process flag older than 1h (now - 2h)
		old_expired = pit_dir / "Host-Proc-3333.flag"
		old_expired.write_text(str(TimestampedValue("Host-Proc-3333", now - datetime.timedelta(hours=2))) + "\n", encoding="utf-8")

		opts = PitMaintenanceOptions(
			apply=True,
			prune_process_flags=True,
			older_than=datetime.timedelta(hours=1),
		)

		with Pit.open(pit_dir, unflagged=True) as pit:
			res = pit.maintain(opts)

		assert res.process_flags_active == 1
		assert res.process_flags_expired == 2
		assert res.process_flags_pruned == 1
		assert res.succeeded is True

		assert m_flag.is_file()
		assert active_flag.is_file()
		assert young_expired.is_file()
		assert not old_expired.exists()


def test_maintain_repair_legacy_events() -> None:
	with tempfile.TemporaryDirectory() as tmp:
		pit_dir = Path(tmp) / "TestPit"
		pit_dir.mkdir(parents=True)
		(pit_dir / "TestPit.pit").write_text("[]\n", encoding="utf-8")

		events_dir = pit_dir / "Events"
		events_dir.mkdir()

		body = "{\"Event\": \"test\"}\n"
		digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

		legacy_file = events_dir / f"EventStem_{digest}.event"
		legacy_file.write_text(body, encoding="utf-8")

		opts = PitMaintenanceOptions(apply=True, repair_legacy_extensions=True)

		with Pit.open(pit_dir, unflagged=True) as pit:
			res = pit.maintain(opts)

		assert res.legacy_artifacts_observed == 1
		assert res.legacy_artifacts_repaired == 1

		clean_file = events_dir / "EventStem.event"
		assert clean_file.is_file()
		assert not legacy_file.exists()


def test_maintain_cli_validation_rules() -> None:
	# --prune-process-flags requires --apply
	args1 = argparse.Namespace(
		pit="Dummy",
		apply=False,
		prune_process_flags=True,
		older_than="01:00:00",
		repair_legacy_extensions=False,
		archive_events=False,
		json=False,
		wwwa=False,
	)
	assert cmd_maintain(args1) == 1

	# --prune-process-flags requires --older-than
	args2 = argparse.Namespace(
		pit="Dummy",
		apply=True,
		prune_process_flags=True,
		older_than=None,
		repair_legacy_extensions=False,
		archive_events=False,
		json=False,
		wwwa=False,
	)
	assert cmd_maintain(args2) == 1

	# --older-than applies only with --prune-process-flags
	args3 = argparse.Namespace(
		pit="Dummy",
		apply=True,
		prune_process_flags=False,
		older_than="01:00:00",
		repair_legacy_extensions=False,
		archive_events=False,
		json=False,
		wwwa=False,
	)
	assert cmd_maintain(args3) == 1

	# --repair-legacy-extensions requires --apply
	args4 = argparse.Namespace(
		pit="Dummy",
		apply=False,
		prune_process_flags=False,
		older_than=None,
		repair_legacy_extensions=True,
		archive_events=False,
		json=False,
		wwwa=False,
	)
	assert cmd_maintain(args4) == 1

	# both <pit> and --wwwa
	args5 = argparse.Namespace(
		pit="Dummy",
		wwwa=True,
		apply=True,
		prune_process_flags=False,
		older_than=None,
		repair_legacy_extensions=False,
		archive_events=False,
		json=False,
	)
	assert cmd_maintain(args5) == 1


def test_maintain_cli_json_schema() -> None:
	with tempfile.TemporaryDirectory() as tmp:
		pit_dir = Path(tmp) / "TestPit"
		pit_dir.mkdir(parents=True)
		canonical = pit_dir / "TestPit.pit"
		canonical.write_text("[]\n", encoding="utf-8")

		args = argparse.Namespace(
			pit=str(pit_dir),
			apply=False,
			prune_process_flags=False,
			older_than=None,
			repair_legacy_extensions=False,
			archive_events=False,
			json=True,
			wwwa=False,
			cloud="OneDrive",
			root=None,
		)

		import io
		import sys

		buf = io.StringIO()
		old_stdout = sys.stdout
		try:
			sys.stdout = buf
			rc = cmd_maintain(args)
		finally:
			sys.stdout = old_stdout

		assert rc == 0
		data = json.loads(buf.getvalue())

		expected_keys = {
			"PitFile", "Applied", "Succeeded", "MasterFlagsObserved",
			"ConflictFlagsObserved", "ProcessFlagsActive", "ProcessFlagsExpired",
			"ProcessFlagsPruned", "ProcessFlagsMalformed", "ChangeFilesObserved",
			"ChangeFilesInvalid", "ChangeFilesValid", "ChangeFilesMerged",
			"ChangeFilesEligible", "ChangeFilesRemoved", "ReceiptsObserved",
			"ReceiptsCreated", "ReceiptsRetained", "ReceiptsRemoved",
			"ReceiptsMalformed", "LegacyArtifactsObserved", "LegacyArtifactsRepaired",
			"EventFilesObserved", "EventFilesArchived", "EventFilesRemoved",
			"EventArchiveName", "CanonicalPersisted", "CurrentMaster",
			"Deferred", "Failures"
		}
		for key in expected_keys:
			assert key in data, f"Key '{key}' missing from maintain JSON output"


def test_maintain_wwwa_cloud_not_hijacked_by_local_cwd_directory() -> None:
	"""
	Regression test: when running `jpit maintain --wwwa -c <cloud> -r AIA`,
	if an eponymous folder `./AIA` exists in the current working directory,
	the maintain target MUST resolve against the cloud root, not the local cwd folder.
	"""
	with tempfile.TemporaryDirectory() as tmp_cloud, tempfile.TemporaryDirectory() as tmp_cwd:
		# 1. Setup cloud storage with WWWA pits under AIA/
		cloud_root = Path(tmp_cloud) / "CloudData"
		cloud_root.mkdir(parents=True)
		tenant_cloud = cloud_root / "AIA"
		for pit_name in ["Activity", "Image", "Object", "Person", "Place"]:
			p_dir = tenant_cloud / pit_name
			p_dir.mkdir(parents=True)
			(p_dir / f"{pit_name}.pit").write_text("[]\n", encoding="utf-8")

		# 2. Setup a dummy local ./AIA directory in cwd (without .pit files)
		local_aia = Path(tmp_cwd) / "AIA"
		local_aia.mkdir(parents=True)

		# 3. Configure mock OsConfig with our cloud_root
		import os
		from jsonpit.config import OsConfig
		mock_cfg = OsConfig({"Cloud": {"MockDrive": str(cloud_root)}})
		OsConfig._instance = mock_cfg

		orig_cwd = os.getcwd()
		try:
			os.chdir(tmp_cwd)
			args = argparse.Namespace(
				pit=None,
				apply=False,
				prune_process_flags=False,
				older_than=None,
				repair_legacy_extensions=False,
				archive_events=False,
				json=True,
				wwwa=True,
				cloud="MockDrive",
				root="AIA",
			)

			import io
			import sys

			buf = io.StringIO()
			err_buf = io.StringIO()
			old_stdout = sys.stdout
			old_stderr = sys.stderr
			try:
				sys.stdout = buf
				sys.stderr = err_buf
				rc = cmd_maintain(args)
			finally:
				sys.stdout = old_stdout
				sys.stderr = old_stderr

			assert rc == 0, f"Expected cmd_maintain to succeed, got rc={rc}, err={err_buf.getvalue()}"
			data = json.loads(buf.getvalue())
			assert isinstance(data, list)
			assert len(data) == 4
			for item in data:
				assert str(cloud_root) in item["PitFile"]
				assert str(local_aia) not in item["PitFile"]
		finally:
			os.chdir(orig_cwd)
			OsConfig.reset()
