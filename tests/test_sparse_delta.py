"""
Certification test suite for sparse delta mutations and the Bound Entity Protocol.
Verifies that:
1. Mutating a living entity via indexer (entity["Alter"] = 63) or set_property() automatically
   dispatches a sparse delta fragment to the Pit.
2. The appended fragment in storage contains ONLY the delta properties and Id/Modified,
   with ZERO leakage of prior projected properties.
3. 'jpit set' and 'jpit del-prop' emit pure sparse deltas without Read-Modify-Write.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from jsonpit import Pit, PitItem
from jsonpit.cli import main


def test_bound_entity_attribute_assignment_emits_sparse_delta() -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		with Pit.open(pit_dir, unflagged=True) as pit:
			# Base entity with 5 attributes
			base = PitItem({
				"Id": "Alice",
				"Kind": "Person",
				"Name": "Alice Smith",
				"City": "Cape Town",
				"Status": "Active",
			})
			pit.add(base)

		with Pit.open(pit_dir, unflagged=True) as pit:
			alice = pit["Alice"]
			assert alice.pit is pit, "Retrieved living entity must be bound to parent Pit!"

			# Object-oriented mutation directly on the living entity
			alice["Alter"] = 63

			# Verify history fragment count
			history = pit._historic_items["Alice"].history
			assert len(history) == 2, "Expected 2 fragments in history stack!"

			newest_frag = history[0]
			frag_dict = newest_frag.to_dict()

			# THE GOLDEN INVARIANT: Newest fragment must ONLY contain Id, Modified, and Alter
			expected_keys = {"Id", "Modified", "Deleted", "Alter"}
			assert set(frag_dict.keys()) == expected_keys, (
				f"Storage leakage! Fragment carried unexpected properties: {set(frag_dict.keys()) - expected_keys}"
			)
			assert frag_dict["Alter"] == 63
			assert "Kind" not in frag_dict
			assert "Name" not in frag_dict
			assert "City" not in frag_dict
			assert "Status" not in frag_dict

			# Verify projected state includes both base attributes and new delta
			living = pit["Alice"]
			assert living["Alter"] == 63
			assert living["City"] == "Cape Town"
			assert living["Status"] == "Active"


def test_bound_entity_set_property_emits_sparse_delta() -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		with Pit.open(pit_dir, unflagged=True) as pit:
			pit.add(PitItem({
				"Id": "Alice",
				"Kind": "Person",
				"Name": "Alice Smith",
				"City": "Cape Town",
			}))

		with Pit.open(pit_dir, unflagged=True) as pit:
			alice = pit["Alice"]
			changed = alice.set_property({"UseCase": "PerformLive", "Rating": 5})
			assert changed is True

			history = pit._historic_items["Alice"].history
			assert len(history) == 2

			newest_frag = history[0].to_dict()
			expected_keys = {"Id", "Modified", "Deleted", "UseCase", "Rating"}
			assert set(newest_frag.keys()) == expected_keys
			assert "Kind" not in newest_frag
			assert "City" not in newest_frag


def test_bound_entity_property_tombstone_emits_sparse_delta() -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		with Pit.open(pit_dir, unflagged=True) as pit:
			pit.add(PitItem({
				"Id": "Alice",
				"Kind": "Person",
				"City": "Cape Town",
			}))

		with Pit.open(pit_dir, unflagged=True) as pit:
			alice = pit["Alice"]
			alice.delete_property("City")

			history = pit._historic_items["Alice"].history
			assert len(history) == 2

			newest_frag = history[0].to_dict()
			# Tombstone fragment carries only City: None
			assert newest_frag["City"] is None
			assert "Kind" not in newest_frag

			# Living state projection has pruned City
			assert pit["Alice"].get("City") is None


def test_cli_set_emits_pure_sparse_delta_no_read_modify_write() -> None:
	"""Certifies that 'jpit set' never performs Read-Modify-Write."""
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		# Seed initial entity with Kind, Name, Status, What, Who
		with Pit.open(pit_dir, unflagged=True) as pit:
			pit.add(PitItem({
				"Id": "Loc1",
				"Kind": "Location",
				"Name": "Cape Town HQ",
				"Status": "Active",
				"What": "Headquarters",
				"Who": "RSB",
			}))

		# Execute jpit set Loc1 {"UseCase": "PerformLive"}
		exit_code = main(["set", str(pit_dir), "Loc1", '{"UseCase": "PerformLive"}'])
		assert exit_code == 0

		with Pit.open(pit_dir, unflagged=True) as pit:
			history = pit._historic_items["Loc1"].history
			assert len(history) == 2, "Expected 2 fragments in history stack!"

			newest_frag = history[0].to_dict()

			# Strict invariant check on newest fragment
			expected_keys = {"Id", "Modified", "Deleted", "UseCase"}
			assert set(newest_frag.keys()) == expected_keys, (
				f"Read-Modify-Write violation! Fragment carried: {set(newest_frag.keys())}"
			)
			assert newest_frag["UseCase"] == "PerformLive"
			assert "Kind" not in newest_frag
			assert "Name" not in newest_frag
			assert "Status" not in newest_frag
			assert "What" not in newest_frag
			assert "Who" not in newest_frag

			# Verify projected living state holds full merged projection
			projected = pit["Loc1"]
			assert projected["UseCase"] == "PerformLive"
			assert projected["Kind"] == "Location"
			assert projected["Name"] == "Cape Town HQ"
			assert projected["Status"] == "Active"
			assert projected["What"] == "Headquarters"
			assert projected["Who"] == "RSB"


def test_cli_del_prop_emits_pure_sparse_delta() -> None:
	"""Certifies that 'jpit del-prop' emits a sparse tombstone without prior properties."""
	with tempfile.TemporaryDirectory() as tmp_dir:
		pit_dir = Path(tmp_dir) / "TestPit"

		with Pit.open(pit_dir, unflagged=True) as pit:
			pit.add(PitItem({
				"Id": "Loc1",
				"Kind": "Location",
				"Name": "Cape Town HQ",
				"What": "Temporary Depot",
			}))

		exit_code = main(["del-prop", str(pit_dir), "Loc1", "What"])
		assert exit_code == 0

		with Pit.open(pit_dir, unflagged=True) as pit:
			history = pit._historic_items["Loc1"].history
			assert len(history) == 2

			newest_frag = history[0].to_dict()
			expected_keys = {"Id", "Modified", "Deleted", "What"}
			assert set(newest_frag.keys()) == expected_keys
			assert newest_frag["What"] is None
			assert "Kind" not in newest_frag
			assert "Name" not in newest_frag

			assert pit["Loc1"].get("What") is None
