"""
Direct 1:1 mirror of C# DeletePropertyProjectionTests.cs.
Verifies property tombstone semantics, nested path tombstones, and state projection.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from jsonpit.item import PitItem
from jsonpit.store import Pit


def _create_temp_pit() -> tuple[Pit, tempfile.TemporaryDirectory[str]]:
	td = tempfile.TemporaryDirectory()
	pit = Pit(Path(td.name), "TestPit", read_only=False, unflagged=True)
	return pit, td


def test_delete_property_removes_attribute_no_null_shadow(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_basic_1"
		item = PitItem(id=item_id)
		item.set_property({"Keep": "here", "Doomed": "bye"})
		pit.add(item)
		pit.save(force=True)

		live = pit[item_id]
		live.delete_property("Doomed")
		pit.add(live)
		pit.save(force=True)

		projected = pit.get(item_id)
		assert projected is not None
		assert projected["Keep"] == "here"
		assert "Doomed" not in projected
		assert projected.get("Doomed") is None
	finally:
		if td:
			td.cleanup()


def test_delete_property_survives_reload_from_disk(tmp_path: Path | None = None) -> None:
	td = None
	if tmp_path is None:
		td = tempfile.TemporaryDirectory()
		root = Path(td.name)
	else:
		root = tmp_path

	try:
		item_id = "DP_reload_1"
		with Pit(root, "TestPit", read_only=False, unflagged=True) as pit:
			item = PitItem(id=item_id)
			item.set_property({"A": 1, "B": 2})
			pit.add(item)
			pit.save(force=True)

			live = pit[item_id]
			live.delete_property("A")
			pit.add(live)
			pit.save(force=True)

		# Reopen fresh instance from disk
		with Pit(root, "TestPit", read_only=True, unflagged=True) as reloaded:
			projected = reloaded.get(item_id)
			assert projected is not None
			assert "A" not in projected
			assert projected["B"] == 2
	finally:
		if td:
			td.cleanup()


def test_delete_property_item_remains_live_others_intact(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_live_1"
		item = PitItem(id=item_id)
		item.set_property({"A": "x", "B": "y", "C": "z"})
		pit.add(item)
		pit.save(force=True)

		live = pit[item_id]
		live.delete_property("B")
		pit.add(live)
		pit.save(force=True)

		projected = pit.get(item_id)
		assert projected is not None
		assert projected.deleted is False
		assert projected["A"] == "x"
		assert projected["C"] == "z"
		assert "B" not in projected
	finally:
		if td:
			td.cleanup()


def test_partial_null_fragment_deletes_only_that_attribute(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_partial_1"
		item = PitItem(id=item_id)
		item.set_property({"A": "x", "B": "y"})
		pit.add(item)
		pit.save(force=True)

		deletion = PitItem(id=item_id)
		deletion.delete_property("A")
		pit.add(deletion)
		pit.save(force=True)

		projected = pit.get(item_id)
		assert projected is not None
		assert "A" not in projected
		assert projected["B"] == "y"
	finally:
		if td:
			td.cleanup()


def test_delete_property_then_reintroduce_works(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_readd_1"
		item = PitItem(id=item_id)
		item.set_property({"Status": "Draft"})
		pit.add(item)
		pit.save(force=True)

		live = pit[item_id]
		live.delete_property("Status")
		pit.add(live)
		pit.save(force=True)

		again = PitItem(id=item_id)
		again.set_property({"Status": "Signed"})
		pit.add(again)
		pit.save(force=True)

		assert pit.get(item_id)["Status"] == "Signed"
	finally:
		if td:
			td.cleanup()


def test_delete_property_preserves_history_time_travel(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_history_1"
		item = PitItem(id=item_id)
		item.set_property({"A": "before"})
		pit.add(item)
		pit.save(force=True)
		before_delete = pit[item_id].modified

		time.sleep(0.01)
		live = pit[item_id]
		live.delete_property("A")
		pit.add(live)
		pit.save(force=True)

		past = pit.get_at(item_id, before_delete)
		assert past is not None
		assert past["A"] == "before"
	finally:
		if td:
			td.cleanup()


def test_nested_path_tombstone(temp_pit: Pit | None = None) -> None:
	pit, td = (temp_pit, None) if temp_pit else _create_temp_pit()
	try:
		item_id = "DP_nested_path_1"
		item = PitItem(id=item_id)
		item.set_property({
			"What": {
				"Instrument": "Guitar",
				"Chat": "LegacyChatId",
			}
		})
		pit.add(item)
		pit.save(force=True)

		live = pit[item_id]
		live.delete_property_path("What.Chat")
		pit.add(live)
		pit.save(force=True)

		projected = pit.get(item_id)
		assert projected is not None
		what = projected["What"]
		assert what["Instrument"] == "Guitar"
		assert "Chat" not in what
	finally:
		if td:
			td.cleanup()
