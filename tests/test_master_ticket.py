"""
Direct 1:1 mirror of C# MasterTicketTests.cs.
Verifies distributed lease coordination, ticket expiration, and process activity flags.
"""

from __future__ import annotations

import datetime
import tempfile
import time
from pathlib import Path

from jsonpit.canonical import utcnow
from jsonpit.flags import (
	MasterFlagFile,
	ProcessFlagFile,
	get_machine_name,
	participant_of,
)
from jsonpit.item import TimestampedValue


def test_master_flag_claim_and_renewal() -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_dir = Path(td)
		master = MasterFlagFile(pit_dir)
		assert master.is_expired is True

		# Claim lease
		claimed = master.try_claim("MachineA-App-100")
		assert claimed is True
		assert master.is_expired is False
		assert master.originator == "MachineA-App-100"

		# Foreign participant cannot steal active lease
		stolen = master.try_claim("MachineB-App-200")
		assert stolen is False
		assert master.originator == "MachineA-App-100"

		# Owner can renew
		renewed = master.try_claim("MachineA-App-100")
		assert renewed is True
		assert master.originator == "MachineA-App-100"


def test_master_flag_expires_after_duration() -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_dir = Path(td)
		master = MasterFlagFile(pit_dir)

		# Write ticket expired in the past
		past = utcnow() - datetime.timedelta(seconds=120)
		master.update(time=past, originator="MachineOld-App-1")
		assert master.is_expired is True

		# New claimant can now claim expired ticket
		claimed = master.try_claim("MachineNew-App-2")
		assert claimed is True
		assert master.originator == "MachineNew-App-2"
		assert master.is_expired is False


def test_process_flag_file_lifecycle() -> None:
	with tempfile.TemporaryDirectory() as td:
		pit_dir = Path(td)
		proc_flag = ProcessFlagFile(pit_dir, subscriber="TestRunner")
		assert not proc_flag.path.is_file()

		# Update creates flag
		proc_flag.update()
		assert proc_flag.path.is_file()
		assert proc_flag.is_owned_by_current_process is True

		# Clean exit removes flag
		released = proc_flag.try_release_current_process()
		assert released is True
		assert not proc_flag.path.is_file()


def test_participant_of_strips_pid() -> None:
	assert participant_of("Nkosikazi-AIA.Api-59346") == "Nkosikazi-AIA.Api"
	assert participant_of("MacBook-openclaw-1234") == "MacBook-openclaw"
	assert participant_of("StandaloneParticipant") == "StandaloneParticipant"
