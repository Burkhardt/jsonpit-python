"""
Direct 1:1 mirror of C# PitItemSetPropertyChangeDetectionTests.cs.
Verifies mutation change detection, dirty tracking, array replacement, and tombstone preservation.
"""

from __future__ import annotations

import time

from jsonpit.item import PitItem


def test_set_property_same_value_does_not_change_modified() -> None:
	item = PitItem("AAPL")
	item.set_property({"Price": 262.77})
	modified1 = item.modified

	time.sleep(0.03)
	item.set_property({"Price": 262.77})
	modified2 = item.modified

	assert modified1 == modified2
	assert item["Price"] == 262.77


def test_set_property_new_property_changes_modified_while_keeping_existing() -> None:
	item = PitItem("AAPL")
	item.set_property({"Price": 262.77})
	modified1 = item.modified

	time.sleep(0.03)
	item.set_property({"Price": 262.77, "Volume": 17320})
	modified2 = item.modified

	assert modified2 > modified1
	assert item["Price"] == 262.77
	assert item["Volume"] == 17320


def test_set_property_value_changed_changes_modified() -> None:
	item = PitItem("AAPL")
	item.set_property({"Bid": 263.41})
	modified1 = item.modified

	time.sleep(0.03)
	item.set_property({"Bid": 263.43})
	modified2 = item.modified

	assert modified2 > modified1
	assert item["Bid"] == 263.43


def test_set_property_nested_object_same_value_does_not_change_modified() -> None:
	item = PitItem("AAPL")
	item.set_property('{"Meta": {"src": "Tiingo", "venue": "IEX"}}')
	modified1 = item.modified

	time.sleep(0.03)
	item.set_property('{"Meta": {"src": "Tiingo", "venue": "IEX"}}')
	modified2 = item.modified

	assert modified1 == modified2
	meta = item["Meta"]
	assert meta["src"] == "Tiingo"
	assert meta["venue"] == "IEX"


def test_set_property_nested_object_deep_merges_replaces_arrays_and_retains_null_tombstones() -> None:
	item = PitItem("AAPL")
	item.set_property({
		"Meta": {
			"Venue": "NASDAQ",
			"Feeds": ["primary", "secondary"],
			"Notes": "active",
		}
	})

	# Merge patch with replaced array and null tombstone on Notes
	item.set_property({
		"Meta": {
			"Feeds": ["backup"],
			"Notes": None,
			"Extra": 42,
		}
	})

	meta = item["Meta"]
	assert meta["Venue"] == "NASDAQ"
	assert meta["Feeds"] == ["backup"]
	assert meta["Notes"] is None
	assert meta["Extra"] == 42
