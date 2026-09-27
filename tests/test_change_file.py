"""
Direct tests for ChangeFile and ReceiptFile adhering to CR003 and CR021.
Verifies filename format, SHA-256 validation, and receipt grace periods.
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from jsonpit.canonical import utcnow
from jsonpit.changes import ChangeFile, ReceiptFile
from jsonpit.item import PitItem


def test_change_file_name_round_trip() -> None:
	now = utcnow()
	identity = "Nkosikazi-pits-59346"
	sha = "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"

	# CR041 clean format: {ticks}_{identity}
	clean_name = ChangeFile.compose_name(now, identity)
	clean_parsed = ChangeFile.try_parse_name(clean_name)
	assert clean_parsed is not None
	ticks_c, id_c, sha_c = clean_parsed
	assert id_c == identity
	assert sha_c is None
	assert ChangeFile.identity_of(clean_name) == identity

	# CR003 legacy format: {ticks}_{identity}_{sha256}
	legacy_name = ChangeFile.compose_name(now, identity, sha)
	legacy_parsed = ChangeFile.try_parse_name(legacy_name)
	assert legacy_parsed is not None
	ticks_l, id_l, sha_l = legacy_parsed
	assert id_l == identity
	assert sha_l == sha
	assert ChangeFile.identity_of(legacy_name) == identity


def test_change_file_creation_and_validation() -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_dir = Path(td)
		item = PitItem(id="Artist_Hugh")
		item.set_property({"Genre": "Jazz", "Instrument": "Flugelhorn"})

		change_path = ChangeFile.create(pit_dir, item, "TestHost-openclaw-101")
		assert change_path.is_file()

		# CR041: file stem has exactly 1 underscore separating ticks and identity
		assert change_path.stem.count("_") == 1
		assert not any(len(part) == 64 for part in change_path.stem.split("_"))

		# Validated read
		payload = ChangeFile.read_validated(change_path)
		assert payload is not None
		assert len(payload) == 1
		assert len(payload[0]) == 1
		assert payload[0][0]["Id"] == "Artist_Hugh"
		assert payload[0][0]["Genre"] == "Jazz"


def test_receipt_file_grace_period() -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_dir = Path(td)
		fake_change = pit_dir / "12345_Host-app-1_015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862.json"
		fake_change.write_text("[]", encoding="utf-8")

		receipt = ReceiptFile(fake_change)
		assert receipt.path.is_file()
		# Fresh receipt is within the 10-minute grace period
		assert receipt.is_eligible_for_cleanup is False

		# Artificially age the receipt past 10 minutes
		past = utcnow() - datetime.timedelta(minutes=11)
		receipt.time = past
		assert receipt.is_eligible_for_cleanup is True

		# Clean removal
		removed = receipt.remove()
		assert removed is True
		assert not receipt.path.is_file()
