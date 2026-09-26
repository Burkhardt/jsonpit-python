"""
Direct 1:1 mirror of C# EqualTimestampOrderingTests.cs.
Verifies CR003 §3 deterministic equal-timestamp sorting and replay idempotence.
"""

from __future__ import annotations

import datetime
import itertools
from typing import Any

from jsonpit.canonical import canonical_json, utcnow
from jsonpit.history import PitItems
from jsonpit.item import PitItem


def fragment(id: str, modified: datetime.datetime, **properties: Any) -> PitItem:
	data = {"Id": id, "Modified": modified, "Deleted": False}
	data.update(properties)
	return PitItem(data, invalidate=False)


def test_exact_replay_is_idempotent_and_does_not_consume_history_slot() -> None:
	t = utcnow()
	a = fragment("X", t - datetime.timedelta(minutes=2), P=1)
	b = fragment("X", t - datetime.timedelta(minutes=1), P=2)
	c = fragment("X", t, P=3)
	history = PitItems.create("X", max_count=3).push(a).push(b).push(c)
	assert len(history) == 3

	# Replaying exact existing fragment is ignored
	replayed = history.push(fragment("X", t - datetime.timedelta(minutes=1), P=2))
	assert replayed is history
	assert len(replayed) == 3
	assert any(f["P"] == 1 for f in replayed.history)


def test_equal_timestamps_distinct_fragments_are_both_retained() -> None:
	t = utcnow()
	small = fragment("X", t, P1="small")
	large = fragment("X", t, P1="large", P2="extra")
	history = PitItems.create("X").push(large).push(small)
	assert len(history) == 2


def test_equal_timestamps_fewer_properties_sort_first_and_have_precedence() -> None:
	t = utcnow()
	props_pi0 = {f"p{i}": f"pi0-{i}" for i in range(1, 11)}
	props_pi1 = {f"p{i}": f"pi1-{i}" for i in range(1, 12)}

	pi0 = fragment("X", t, **props_pi0)
	pi1 = fragment("X", t, **props_pi1)

	for arrival in ([pi0, pi1], [pi1, pi0]):
		history = PitItems.create("X")
		for frag in arrival:
			history = history.push(frag)
		projected = history.project_state()
		assert projected is not None
		# The smaller fragment sorts first and wins contradictory overlap
		assert projected["p10"] == "pi0-10"
		# While later equal-time fragment still contributes its new property
		assert projected["p11"] == "pi1-11"


def test_equal_timestamp_and_property_count_canonical_tie_break() -> None:
	t = utcnow()
	one = fragment("X", t, P="aaa")
	two = fragment("X", t, P="bbb")

	forward = PitItems.create("X").push(one).push(two)
	backward = PitItems.create("X").push(two).push(one)

	forward_canonical = [canonical_json(f.to_dict()) for f in forward.history]
	backward_canonical = [canonical_json(f.to_dict()) for f in backward.history]
	assert forward_canonical == backward_canonical

	assert canonical_json(forward.project_state().to_dict()) == canonical_json(
		backward.project_state().to_dict()
	)


def test_projection_is_identical_regardless_of_arrival_order() -> None:
	t = utcnow()
	fragments = [
		fragment("X", t - datetime.timedelta(minutes=2), A=1, B=1),
		fragment("X", t, A=2),
		fragment("X", t, A=3, C=3),
		fragment("X", t - datetime.timedelta(minutes=1), B=4),
	]

	reference: str | None = None
	for permutation in itertools.permutations(fragments):
		history = PitItems.create("X")
		for frag in permutation:
			history = history.push(frag)
		projected = canonical_json(history.project_state().to_dict())
		if reference is None:
			reference = projected
		assert reference == projected
