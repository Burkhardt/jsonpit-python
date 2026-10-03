"""
Live Reference & MutationTrackingMode parity tests matching C# LiveReferenceTests.cs.
Verifies:
1. Zero-cloning live object identity (pit[id] is item, item['Who'] is who).
2. Live sparse mutation emission without mutating earlier history.
3. Fallback diffing for silent/unreported edits in TrackedChangesWithFallback mode.
4. TrackedChangesOnly high-throughput mode disabling persistence-boundary diffs.
5. Per-instance immutable capture of static DefaultMutationTrackingMode.
6. Detached snapshots on historical time-travel queries.
7. Rollback of illegal mutations to Id/Modified/Deleted without history generation.
8. ObjectDisposedError on mutations after pit disposal.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import tempfile
import time

from jsonpit import (
	MutationTrackingMode,
	ObjectDisposedError,
	Pit,
	PitItem,
	PitItems,
	ProtectedAttributeError,
	utcnow,
)


def _new_pit(tracking_mode: MutationTrackingMode | None = None) -> tuple[Pit, tempfile.TemporaryDirectory[str]]:
	td = tempfile.TemporaryDirectory()
	p = Pit(
		Path(td.name),
		"TestPit",
		read_only=False,
		autoload=False,
		unflagged=True,
		tracking_mode=tracking_mode,
	)
	return p, td


def _sample_item() -> PitItem:
	return PitItem({
		"Id": "Ego",
		"Who": {"Owner": "Unknown", "Observer": "Adele"},
		"Role": "Person",
	})


def test_original_aliases_append_sparse_fragments_without_changing_earlier_history() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		who = item["Who"]
		pit.add(item)
		initial_time = item.modified

		item["Instagram"] = "@Dr2RAI"
		who["Owner"] = "Rainer"

		assert pit["Ego"] is item
		assert pit["Ego"]["Who"] is who

		history = pit.historic_items["Ego"].history
		assert len(history) == 3

		newest_keys = set(history[0].keys())
		assert "Instagram" not in newest_keys
		assert newest_keys == {"Deleted", "Id", "Modified", "Who"}
		assert history[0]["Who"] == {"Owner": "Rainer"}

		past = pit.get_at("Ego", initial_time)
		assert past is not None
		assert past["Who"]["Owner"] == "Unknown"
		assert past.get("Instagram") is None
	finally:
		pit.close()
		td.cleanup()


def test_silent_scalar_edits_are_coalesced_and_timestamped_when_save_detects_them() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		pit.save()
		original_time = item.modified

		# Silent direct modifications to underlying data (unnotified scalar edits)
		with item.suppress_notifications():
			item["Who"]["Owner"] = "Intermediate"
			item["Who"]["Owner"] = "Rainer"

		assert pit["Ego"]["Who"]["Owner"] == "Rainer"
		assert len(pit.historic_items["Ego"].history) == 1
		assert item.modified == original_time

		# Projected history before save still sees old value
		assert pit.get_at("Ego", utcnow())["Who"]["Owner"] == "Unknown"

		time.sleep(0.01)
		detection_started = utcnow()
		pit.save()

		assert item.modified >= detection_started
		assert len(pit.historic_items["Ego"].history) == 2
		assert pit.historic_items["Ego"].history[0]["Who"] == {"Owner": "Rainer"}
		assert pit.get_at("Ego", original_time)["Who"]["Owner"] == "Unknown"

		pit.save()
		assert len(pit.historic_items["Ego"].history) == 2
	finally:
		pit.close()
		td.cleanup()


def test_sparse_add_preserves_live_identity_and_previously_silent_edits() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		who = item["Who"]
		item._data["Who"]["Owner"] = "Rainer"

		pit.add(PitItem({"Id": "Ego", "Role": "Musician"}))

		assert pit["Ego"] is item
		assert item["Who"] is who
		assert who["Owner"] == "Rainer"
		assert item["Role"] == "Musician"
		assert len(pit.historic_items["Ego"].history) == 3
	finally:
		pit.close()
		td.cleanup()


def test_load_preserves_silent_local_edits_and_held_references() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		pit.save()
		who = item["Who"]
		item._data["Who"]["Owner"] = "Rainer"

		assert pit.load() is True
		assert pit["Ego"] is item
		assert item["Who"] is who
		assert who["Owner"] == "Rainer"
		assert len(pit.historic_items["Ego"].history) == 2
		assert pit.invalid() is True
	finally:
		pit.close()
		td.cleanup()


def test_historical_merge_folds_at_acceptance_and_preserves_held_references() -> None:
	pit, td = _new_pit()
	try:
		base_time = utcnow() - datetime.timedelta(minutes=3)
		pit.add_historical(PitItem({
			"Id": "Ego",
			"Who": {"Owner": "Unknown", "Observer": "Adele"},
		}, modified=base_time))

		item = pit["Ego"]
		who = item["Who"]

		history = PitItems("Ego", [
			PitItem({"Id": "Ego", "Who": {"Owner": "Latest"}}, modified=base_time + datetime.timedelta(minutes=2)),
			PitItem({"Id": "Ego", "Who": {"Owner": "Earlier"}}, modified=base_time + datetime.timedelta(minutes=1)),
		])
		pit.merge_into_history(history)

		assert pit["Ego"] is item
		assert item["Who"] is who
		assert who["Owner"] == "Latest"
		assert who["Observer"] == "Adele"
		assert pit.get_at("Ego", base_time + datetime.timedelta(minutes=1))["Who"]["Owner"] == "Earlier"
	finally:
		pit.close()
		td.cleanup()


def test_helpers_commit_once_and_tombstones_prune_the_live_object() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		item.set_property({"Instagram": "@Dr2RAI", "Email": "example@example.org"})
		assert len(pit.historic_items["Ego"].history) == 2

		item.delete_property("Instagram")
		assert item.get("Instagram") is None
		assert "Instagram" not in item

		item.delete_property_path("Who.Owner")
		assert item["Who"].get("Owner") is None
		assert "Owner" not in item["Who"]
		assert item["Who"]["Observer"] == "Adele"
		assert len(pit.historic_items["Ego"].history) == 4

		assert item.delete() is True
		assert pit.get("Ego") is None
	finally:
		pit.close()
		td.cleanup()


def test_native_mutations_work_with_observable_list_and_preserve_sparse_history() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		item["Tags"] = ["first"]
		pit.add(item)

		item["Extra"] = 1
		del item["Extra"]
		item["Role"] = None
		assert item.get("Role") is None

		del item["Who"]["Owner"]
		item["Tags"].append("second")

		assert len(pit.historic_items["Ego"].history) == 6
		assert len(pit["Ego"]["Tags"]) == 2
		assert pit["Ego"]["Tags"] == ["first", "second"]
		assert "Owner" not in pit["Ego"]["Who"]
	finally:
		pit.close()
		td.cleanup()


def test_protected_native_and_silent_mutations_roll_back_without_history() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)

		try:
			item["Id"] = "Other"
			assert False, "Expected ProtectedAttributeError"
		except ProtectedAttributeError:
			pass

		try:
			del item["Id"]
			assert False, "Expected ProtectedAttributeError"
		except ProtectedAttributeError:
			pass

		assert item.id == "Ego"

		# Silent modification (unnotified scalar edit)
		with item.suppress_notifications():
			item._data["Id"] = "Other"
		try:
			pit.save()
			assert False, "Expected ProtectedAttributeError on save"
		except ProtectedAttributeError:
			pass

		assert item.id == "Ego"
		assert len(pit.historic_items["Ego"].history) == 1
	finally:
		pit.close()
		td.cleanup()


def test_historical_values_and_snapshots_are_detached_from_live_and_stored_objects() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		at = item.modified

		snap = pit.get_at("Ego", at)
		assert snap is not None
		snap["Who"]["Owner"] = "Past edited"

		hist_top = pit.historic_items["Ego"].history[0]
		hist_top["Who"]["Owner"] = "History edited"

		vot = pit.values_over_time("Ego", "Who")
		assert len(vot) >= 1
		vot[0].value["Owner"] = "Value edited"

		assert item["Who"]["Owner"] == "Unknown"
		assert pit.get_at("Ego", at)["Who"]["Owner"] == "Unknown"
	finally:
		pit.close()
		td.cleanup()


def test_dispose_captures_silent_edits_and_reopen_builds_stable_live_objects() -> None:
	pit, td = _new_pit()
	try:
		item = _sample_item()
		pit.add(item)
		with item.suppress_notifications():
			item["Who"]["Owner"] = "Rainer"
		pit.dispose()

		try:
			item["Role"] = "Late edit"
			assert False, "Expected ObjectDisposedError"
		except ObjectDisposedError:
			pass

		with Pit(pit.pit_dir, "TestPit", read_only=True, unflagged=True) as reopened:
			loaded = reopened["Ego"]
			assert loaded is not None
			assert reopened["Ego"] is loaded
			assert loaded["Who"]["Owner"] == "Rainer"
	finally:
		td.cleanup()


def test_tracking_mode_is_captured_per_instance_and_never_persisted() -> None:
	prev = Pit.default_mutation_tracking_mode
	try:
		Pit.default_mutation_tracking_mode = MutationTrackingMode.TrackedChangesWithFallback
		cli, td_cli = _new_pit()
		Pit.default_mutation_tracking_mode = MutationTrackingMode.TrackedChangesOnly
		server, td_server = _new_pit()

		assert cli.tracking_mode == MutationTrackingMode.TrackedChangesWithFallback
		assert cli.TrackingMode == MutationTrackingMode.TrackedChangesWithFallback
		assert server.tracking_mode == MutationTrackingMode.TrackedChangesOnly
		assert server.TrackingMode == MutationTrackingMode.TrackedChangesOnly

		cli.add(_sample_item())
		cli.save()

		text = cli.canonical_file.read_text(encoding="utf-8")
		assert "TrackingMode" not in text
		assert "tracking_mode" not in text

		cli.dispose()
		with Pit(cli.pit_dir, "TestPit", read_only=True, unflagged=True) as server_opening:
			assert server_opening.tracking_mode == MutationTrackingMode.TrackedChangesOnly
			assert server_opening["Ego"] is not None
		td_cli.cleanup()
		server.dispose()
		td_server.cleanup()
	finally:
		Pit.default_mutation_tracking_mode = prev


def test_both_modes_keep_original_references_and_track_indexer_edits_immediately() -> None:
	prev = Pit.default_mutation_tracking_mode
	try:
		for mode in (MutationTrackingMode.TrackedChangesOnly, MutationTrackingMode.TrackedChangesWithFallback):
			Pit.default_mutation_tracking_mode = mode
			pit, td = _new_pit()
			try:
				item = _sample_item()
				who = item["Who"]
				pit.add(item)
				who["Owner"] = "Rainer"
				item["Instagram"] = "@Dr2RAI"

				assert pit["Ego"] is item
				assert pit["Ego"]["Who"] is who
				assert len(pit.historic_items["Ego"].history) == 3
				assert pit.get_at("Ego", item.modified)["Who"]["Owner"] == "Rainer"
			finally:
				pit.close()
				td.cleanup()
	finally:
		Pit.default_mutation_tracking_mode = prev


def test_tracked_changes_only_does_not_reconcile_unsupported_scalar_edits_at_save() -> None:
	prev = Pit.default_mutation_tracking_mode
	try:
		Pit.default_mutation_tracking_mode = MutationTrackingMode.TrackedChangesOnly
		pit, td = _new_pit()
		try:
			item = _sample_item()
			pit.add(item)
			pit.save()

			with item.suppress_notifications():
				item["Who"]["Owner"] = "Unreported"
			pit.save()

			assert len(pit.historic_items["Ego"].history) == 1
			assert pit.get_at("Ego", utcnow())["Who"]["Owner"] == "Unknown"
			assert "Unreported" not in pit.canonical_file.read_text(encoding="utf-8")
		finally:
			pit.close()
			td.cleanup()
	finally:
		Pit.default_mutation_tracking_mode = prev
