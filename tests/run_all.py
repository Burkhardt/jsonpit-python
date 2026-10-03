"""
Unified runner for the entire jsonpit test suite.
Can be executed directly via: python3 tests/run_all.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

# Ensure workspace root is in sys.path and subprocess environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))
import os
os.environ["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + os.environ["PYTHONPATH"] if "PYTHONPATH" in os.environ else "")


def run_suite() -> int:
	import tests.test_audit as t_audit
	import tests.test_canonical as t_canon
	import tests.test_change_file as t_change
	import tests.test_cli as t_cli
	import tests.test_cr043_seed_shapes as t_cr043
	import tests.test_cr044_missing_config as t_cr044
	import tests.test_cr047_strict_patch as t_cr047
	import tests.test_cr049_live_id_validation as t_cr049
	import tests.test_csharp_compatibility as t_compat
	import tests.test_delete_property_projection as t_dp
	import tests.test_equal_timestamp_ordering as t_equal
	import tests.test_live_references as t_live
	import tests.test_maintain as t_maintain
	import tests.test_master_ticket as t_master
	import tests.test_pit_item as t_item
	import tests.test_sequence_suites as t_seq
	import tests.test_sparse_delta as t_sparse

	modules = [
		("test_audit", t_audit),
		("test_canonical", t_canon),
		("test_csharp_compatibility", t_compat),
		("test_pit_item", t_item),
		("test_equal_timestamp_ordering", t_equal),
		("test_delete_property_projection", t_dp),
		("test_master_ticket", t_master),
		("test_change_file", t_change),
		("test_cli", t_cli),
		("test_cr043_seed_shapes", t_cr043),
		("test_cr044_missing_config", t_cr044),
		("test_cr047_strict_patch", t_cr047),
		("test_cr049_live_id_validation", t_cr049),
		("test_live_references", t_live),
		("test_maintain", t_maintain),
		("test_sparse_delta", t_sparse),
		("test_sequence_suites", t_seq),
	]

	total = 0
	passed = 0
	failed = 0
	start_time = time.perf_counter()

	print("=" * 70)
	print("jsonpit Test Suite Execution (100% C# Parity)")
	print("=" * 70)

	for mod_name, mod in modules:
		print(f"\n[{mod_name}]")
		for attr_name in dir(mod):
			if attr_name.startswith("test_") and callable(getattr(mod, attr_name)):
				func = getattr(mod, attr_name)
				total += 1
				try:
					func()
					passed += 1
					print(f"  \u2714 {attr_name}")
				except Exception as ex:
					failed += 1
					print(f"  \u2716 {attr_name} FAILED: {ex}")
					traceback.print_exc()

	duration = time.perf_counter() - start_time
	print("\n" + "=" * 70)
	print(f"Results: {passed} passed, {failed} failed in {duration:.3f}s (Total: {total})")
	print("=" * 70)

	return 0 if failed == 0 else 1


if __name__ == "__main__":
	sys.exit(run_suite())
