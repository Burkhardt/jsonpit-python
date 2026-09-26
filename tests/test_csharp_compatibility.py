"""
Cross-language parity tests verifying that Python jsonpit cleanly loads,
queries, and projects actual C# JsonPit snapshots.
"""

from __future__ import annotations

from pathlib import Path

from jsonpit.store import Pit

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_csharp_person_pit() -> None:
	pit_file = FIXTURE_DIR / "Person.pit"
	assert pit_file.is_file(), f"Missing test fixture: {pit_file}"

	pit = Pit(FIXTURE_DIR, "Person", read_only=True, unflagged=True)
	loaded = pit.load()
	assert loaded is True
	assert len(pit) == 7

	# Verify key identities
	keys = set(pit.keys())
	expected_keys = {"118374457781715519159", "7010", "7011", "7012", "7015", "7017", "Ada"}
	assert keys == expected_keys

	# Verify Dr. Rainer Burkhardt entity
	rai = pit["118374457781715519159"]
	assert rai["Name"] == "Dr. Rainer Burkhardt"
	assert rai["Alias"] == "RAI"
	assert rai["Class"] == "Person"
	assert rai["Kind"] == "Per"
	assert rai.deleted is False

	# Verify Adele (7010) entity
	adele = pit["7010"]
	assert adele["Name"] == "Adele"
	assert adele["Class"] == "Agent"
	assert "Smalltalk-80" in adele["Tribute"]

	# Verify Zébio (7011) entity
	zebio = pit["7011"]
	assert zebio["Name"] == "Zébio"
	assert "Mozambican" in zebio["Tribute"]

	# Verify Alan (7012) entity
	alan = pit["7012"]
	assert alan["Name"] == "Alan"
	assert "Dynabook" in alan["Tribute"]
