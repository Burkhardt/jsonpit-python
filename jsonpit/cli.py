"""
Command-line interface for jsonpit and jpit.
Provides living-state semantic search (Pit-Grep), stream piping with jq,
point-in-time time-travel, and JSON5 mutation ingestion.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from .canonical import canonical_json, format_iso_timestamp, parse_iso_timestamp, utcnow
from .config import OsConfig, loads_json5
from .exceptions import JsonPitError, PitNotFoundError
from .fs import resolve_pit_target
from .item import PitItem
from .store import Pit
from . import __version__


def run_jq_filter(json_text: str, jq_filter: str) -> None:
	"""Pipes json_text through the system jq executable."""
	jq_bin = shutil.which("jq") or "/usr/bin/jq"
	if not os.path.isfile(jq_bin):
		sys.stderr.write("[jpit] Error: 'jq' executable not found on system PATH.\n")
		sys.stdout.write(json_text)
		return

	proc = subprocess.Popen(
		[jq_bin, jq_filter],
		stdin=subprocess.PIPE,
		stdout=sys.stdout,
		stderr=sys.stderr,
		text=True,
	)
	proc.communicate(input=json_text)


def discover_pits(
	target: str,
	cloud: str | None = "OneDrive",
	root: str | None = None,
) -> list[tuple[Path, str]]:
	"""
	Discovers one or multiple pits based on a target name or root.
	If target is an entire root (e.g. 'AIA'), discovers all contained pits.
	"""
	# Check if target is current directory or default
	if target in (".", ""):
		cwd = Path.cwd()
		discovered_cwd: list[tuple[Path, str]] = []
		for child in sorted(cwd.iterdir()):
			if child.is_dir():
				pit_file = child / f"{child.name}.pit"
				if pit_file.is_file():
					discovered_cwd.append((child, child.name))
			elif child.suffix.lower() == ".pit":
				discovered_cwd.append((child.parent, child.stem))
		if discovered_cwd:
			return discovered_cwd

	# Check if target is a single pit or an explicit directory
	try:
		p_dir, p_name = resolve_pit_target(target, cloud=cloud, root=root)
		if (p_dir / f"{p_name}.pit").is_file() or p_dir.is_dir():
			return [(p_dir, p_name)]
	except Exception:
		pass

	# Check if target is a tenant/root folder containing multiple pit directories
	cfg = OsConfig.load()
	cloud_root = cfg.get_cloud_root(cloud)
	candidates: list[Path] = []
	if cloud_root and (cloud_root / target).is_dir():
		candidates.append(cloud_root / target)
	if Path(target).is_dir():
		candidates.append(Path(target))

	discovered: list[tuple[Path, str]] = []
	for candidate_root in candidates:
		for child in sorted(candidate_root.iterdir()):
			if child.is_dir():
				pit_file = child / f"{child.name}.pit"
				if pit_file.is_file():
					discovered.append((child, child.name))

	if discovered:
		return discovered

	# Fallback single pit target (only return if it physically exists)
	try:
		p_dir, p_name = resolve_pit_target(target, cloud=cloud, root=root)
		if (p_dir / f"{p_name}.pit").is_file() or p_dir.is_dir():
			return [(p_dir, p_name)]
	except Exception:
		pass
	return []


def cmd_grep(args: argparse.Namespace) -> int:
	"""
	Pit-Grep: Living-state semantic search across single or multiple pits.
	Filters out deleted entities by default, supports time-travel and property scoping.
	"""
	pattern_raw = args.pattern
	target_raw = args.target

	# Smart swap if user passed target first and pattern second:
	if (
		Path(pattern_raw).exists()
		or pattern_raw.endswith(".pit")
		or ("/" in pattern_raw and not pattern_raw.startswith("-"))
		or ("\\" in pattern_raw)
	) and not Path(target_raw).exists() and target_raw != ".":
		pattern_raw, target_raw = target_raw, pattern_raw

	at_time: datetime.datetime | None = None
	if args.at:
		at_time = parse_iso_timestamp(args.at)

	flags = re.IGNORECASE if args.ignore_case else 0
	try:
		pattern = re.compile(pattern_raw if args.regex else re.escape(pattern_raw), flags)
	except re.error as ex:
		sys.stderr.write(f"[jpit] Regex error: {ex}\n")
		return 1

	pits = discover_pits(target_raw, cloud=args.cloud, root=args.root)
	if not pits:
		sys.stderr.write(f"[jpit] No pits found for target '{target_raw}'.\n")
		return 1

	matched_entities: list[dict[str, Any]] = []

	for pit_dir, pit_name in pits:
		try:
			with Pit(
				pit_dir=pit_dir,
				pit_name=pit_name,
				read_only=True,
				unflagged=True,
			) as pit:
				for key in pit.keys():
					item = pit.get(key, at=at_time, with_deleted=args.with_deleted)
					if item is None:
						continue
					item_dict = item.to_dict()

					# Property-scoped search or broad search
					matches_found: list[tuple[str, str]] = []
					if args.property:
						val = _get_nested(item_dict, args.property)
						val_str = str(val) if val is not None else ""
						if pattern.search(val_str):
							matches_found.append((args.property, val_str))
					else:
						# Search all attributes
						for k, v in item_dict.items():
							v_str = str(v)
							if pattern.search(v_str):
								matches_found.append((k, v_str))

					if matches_found:
						record = copy.deepcopy(item_dict)
						record["_pit"] = pit_name
						matched_entities.append(record)

						if not args.json:
							label = record.get("Name") or record.get("Id")
							print(f"\033[1;34m[{pit_name} : {record.get('Id')}]\033[0m \033[1m({label})\033[0m")
							for prop_k, prop_v in matches_found[:4]:
								highlighted = pattern.sub(
									lambda m: f"\033[1;31m{m.group(0)}\033[0m",
									prop_v.replace("\n", " ")[:120],
								)
								print(f"  \033[36m.{prop_k}\033[0m: {highlighted}")
							print()
		except Exception as ex:
			sys.stderr.write(f"[jpit] Error reading pit {pit_name}: {ex}\n")

	if args.json:
		raw_json = json.dumps(matched_entities, indent=2, ensure_ascii=False)
		if args.jq:
			run_jq_filter(raw_json, args.jq)
		else:
			sys.stdout.write(raw_json + "\n")

	return 0


def _get_nested(data: dict[str, Any], path: str) -> Any:
	"""Navigates dot-delimited path in a dictionary."""
	curr: Any = data
	for part in path.split("."):
		if isinstance(curr, dict):
			curr = curr.get(part)
		else:
			return None
	return curr


def cmd_get(args: argparse.Namespace) -> int:
	"""Retrieves an entity projection, optionally filtered by timestamp or jq."""
	at_time = parse_iso_timestamp(args.at) if args.at else None
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		read_only=True,
		unflagged=True,
	) as pit:
		if not pit.canonical_file.is_file():
			sys.stderr.write(f"[jpit] Pit '{args.pit}' not found at {pit.pit_dir}.\n")
			return 1

		item = pit.get(args.id, at=at_time, with_deleted=args.with_deleted)
		if item is None:
			sys.stderr.write(f"[jpit] Entity '{args.id}' not found in Pit '{pit.pit_name}'.\n")
			return 1

		output = json.dumps(item.to_dict(), indent=2, ensure_ascii=False)
		if args.jq:
			run_jq_filter(output, args.jq)
		else:
			sys.stdout.write(output + "\n")
	return 0


def cmd_history(args: argparse.Namespace) -> int:
	"""Dumps the raw immutable fragment history array for an entity."""
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		read_only=True,
		unflagged=True,
	) as pit:
		if not pit.canonical_file.is_file():
			sys.stderr.write(f"[jpit] Pit '{args.pit}' not found at {pit.pit_dir}.\n")
			return 1

		pit_items = pit._historic_items.get(args.id)
		if pit_items is None:
			sys.stderr.write(f"[jpit] No history for '{args.id}' in Pit '{pit.pit_name}'.\n")
			return 1

		fragments = [frag.to_dict() for frag in pit_items.history]
		output = json.dumps(fragments, indent=2, ensure_ascii=False)
		if args.jq:
			run_jq_filter(output, args.jq)
		else:
			sys.stdout.write(output + "\n")
	return 0


def cmd_list(args: argparse.Namespace) -> int:
	"""Lists active entities in a Pit."""
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		read_only=True,
		unflagged=True,
	) as pit:
		if not pit.canonical_file.is_file():
			sys.stderr.write(f"[jpit] Pit '{args.pit}' not found at {pit.pit_dir}.\n")
			return 1

		keys = list(pit.keys())
		if args.json:
			entities = [pit[k].to_dict() for k in keys]
			output = json.dumps(entities, indent=2, ensure_ascii=False)
			if args.jq:
				run_jq_filter(output, args.jq)
			else:
				sys.stdout.write(output + "\n")
			return 0

		print(f"\033[1mPit: {pit.pit_name}\033[0m ({len(keys)} active entities) at {pit.pit_dir}\n")
		for k in keys:
			item = pit[k]
			name = item.get("Name") or item.get("Alias") or k
			cls_label = f"[{item.get('Class')}]" if item.get("Class") else ""
			print(f"  • \033[1;34m{k:<24}\033[0m {name:<30} {cls_label}")
	return 0


def cmd_put(args: argparse.Namespace) -> int:
	"""
	Ingests entities from stdin, piped jq output, or a JSON5 file.
	Adds entities cloud-safely with leasing.
	"""
	# Read source content
	content = ""
	if args.source and args.source != "-":
		path = Path(args.source)
		if not path.is_file():
			sys.stderr.write(f"[jpit] Source file not found: {path}\n")
			return 1
		content = path.read_text(encoding="utf-8")
	else:
		content = sys.stdin.read()

	if not content.strip():
		sys.stderr.write("[jpit] Error: No input data provided.\n")
		return 1

	data = loads_json5(content)
	items_to_add: list[dict[str, Any]] = []
	if isinstance(data, list):
		items_to_add = [row for row in data if isinstance(row, dict)]
	elif isinstance(data, dict):
		if "Id" in data or "id" in data:
			items_to_add = [data]
		else:
			for k, v in data.items():
				if isinstance(v, dict):
					v["Id"] = k
					items_to_add.append(v)

	if not items_to_add:
		sys.stderr.write("[jpit] Error: Input data contains no valid entity objects.\n")
		return 1

	for raw_obj in items_to_add:
		forbidden = [k for k in raw_obj if k.lower() in ("modified", "deleted")]
		if forbidden:
			sys.stderr.write(
				f"[jpit] Error: Cannot manually update protected attribute '{forbidden[0]}'. "
				"Use 'jpit del' to delete an entity.\n"
			)
			return 1

	with Pit.open(args.pit, cloud=args.cloud, root=args.root) as pit:
		count = 0
		for raw_obj in items_to_add:
			item_id = raw_obj.get("Id") or raw_obj.get("id") or raw_obj.get("Name")
			if not item_id:
				continue
			item = PitItem(raw_obj, id=str(item_id))
			pit.add(item)
			count += 1

	print(f"[jpit] Successfully committed {count} entity(ies) to Pit '{args.pit}'.")
	return 0


def cmd_set(args: argparse.Namespace) -> int:
	"""Mutates or creates an entity using a JSON5 string payload."""
	payload = loads_json5(args.payload)
	if not isinstance(payload, dict):
		sys.stderr.write("[jpit] Payload must evaluate to a JSON5 object.\n")
		return 1

	forbidden = [k for k in payload if k.lower() in ("modified", "deleted")]
	if forbidden:
		sys.stderr.write(
			f"[jpit] Error: Cannot manually update protected attribute '{forbidden[0]}'. "
			"Use 'jpit del' to delete an entity.\n"
		)
		return 1

	with Pit.open(args.pit, cloud=args.cloud, root=args.root) as pit:
		existing = pit.get(args.id)
		if existing:
			existing.set_property(payload)
			pit.add(existing)
		else:
			payload["Id"] = args.id
			new_item = PitItem(payload)
			pit.add(new_item)

	print(f"[jpit] Updated entity '{args.id}' in Pit '{args.pit}'.")
	return 0


def cmd_delete(args: argparse.Namespace) -> int:
	"""Tombstones an entity with audited author note and 100s backdating."""
	with Pit.open(args.pit, cloud=args.cloud, root=args.root) as pit:
		success = pit.delete_item(args.id, by=args.by)
		if not success:
			sys.stderr.write(f"[jpit] Entity '{args.id}' is already deleted or not found.\n")
			return 1

	print(f"[jpit] Tombstoned entity '{args.id}' in Pit '{args.pit}'.")
	return 0


def cmd_delete_prop(args: argparse.Namespace) -> int:
	"""Appends a property tombstone at a dot-delimited property path."""
	if args.property_path.lower() in ("id", "modified", "deleted"):
		sys.stderr.write(
			f"[jpit] Error: Cannot tombstone protected attribute '{args.property_path}'. "
			"Use 'jpit del' to delete an entity.\n"
		)
		return 1

	with Pit.open(args.pit, cloud=args.cloud, root=args.root) as pit:
		item = pit.get(args.id)
		if item is None:
			sys.stderr.write(f"[jpit] Entity '{args.id}' not found.\n")
			return 1
		item.delete_property_path(args.property_path)
		pit.add(item)

	print(f"[jpit] Tombstoned property '{args.property_path}' on entity '{args.id}'.")
	return 0


def cmd_export(args: argparse.Namespace) -> int:
	"""Exports all projected entities as JSON to stdout or file."""
	at_time = parse_iso_timestamp(args.at) if args.at else None
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		read_only=True,
		unflagged=True,
	) as pit:
		entities = [
			pit.get(k, at=at_time).to_dict()
			for k in pit.keys()
			if pit.get(k, at=at_time) is not None
		]
		raw_json = json.dumps(entities, indent=2, ensure_ascii=False)

		if args.out:
			Path(args.out).write_text(raw_json, encoding="utf-8")
			print(f"[jpit] Exported {len(entities)} entities to {args.out}")
		elif args.jq:
			run_jq_filter(raw_json, args.jq)
		else:
			sys.stdout.write(raw_json + "\n")
	return 0


def cmd_status(args: argparse.Namespace) -> int:
	"""Inspects master lease status, process windows, and pending change files."""
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		read_only=True,
		unflagged=True,
	) as pit:
		print(f"\033[1m=== Pit Status: {pit.pit_name} ===\033[0m")
		print(f"Path: {pit.pit_dir}")
		print(f"Canonical file: {pit.canonical_file.name} (exists={pit.canonical_file.is_file()})")
		print(f"Active entities: {len(pit)}")

		# Master flag inspection
		master = pit.master_flag
		print(f"\n\033[1mMaster Lease:\033[0m")
		print(f"  Originator: {master.originator or 'None'}")
		print(f"  Time: {format_iso_timestamp(master.time)}")
		print(f"  Is Expired: {master.is_expired}")

		# Process flags
		proc_flags = list(pit.pit_dir.glob("*.flag"))
		print(f"\n\033[1mFlag Files ({len(proc_flags)}):\033[0m")
		for pf in proc_flags:
			print(f"  • {pf.name}")

		# Change files
		change_files = [p for p in pit.pit_dir.glob("*.json") if p.name != pit.canonical_file.name]
		print(f"\n\033[1mPending Change Files ({len(change_files)}):\033[0m")
		for cf in change_files[:5]:
			print(f"  • {cf.name}")
		if len(change_files) > 5:
			print(f"  ... and {len(change_files) - 5} more.")

	return 0


def build_parser() -> argparse.ArgumentParser:
	common_parser = argparse.ArgumentParser(add_help=False)
	common_parser.add_argument(
		"-c", "--cloud",
		default=argparse.SUPPRESS,
		help="Cloud drive (OneDrive, Dropbox, etc.)",
	)
	common_parser.add_argument(
		"-r", "--root",
		default=argparse.SUPPRESS,
		help="Root folder / tenant (e.g. AIA, AfricaStage)",
	)

	parser = argparse.ArgumentParser(
		prog="jpit",
		description="jpit — Cloud-first distributed replicated storage CLI and Pit-Grep.",
		parents=[common_parser],
	)
	parser.add_argument(
		"-v",
		"--version",
		action="version",
		version=f"%(prog)s {__version__}",
	)

	subparsers = parser.add_subparsers(dest="command", required=True)

	# grep (Pit-Grep)
	p_grep = subparsers.add_parser("grep", parents=[common_parser], help="Ripgrep-style living state search across pits")
	p_grep.add_argument("pattern", help="Text or regex to match")
	p_grep.add_argument("target", nargs="?", default=".", help="Pit name, file path, or tenant root (default: current directory)")
	p_grep.add_argument("-i", "--ignore-case", action="store_true", help="Case-insensitive search")
	p_grep.add_argument("-e", "--regex", action="store_true", help="Treat pattern as regex")
	p_grep.add_argument("-p", "--property", help="Scope search to a specific property path")
	p_grep.add_argument("--at", help="Project state as of timestamp")
	p_grep.add_argument("--json", action="store_true", help="Output JSON stream for piping to jq")
	p_grep.add_argument("--jq", help="Convenience pipe through jq filter")
	p_grep.add_argument("--with-deleted", action="store_true", help="Include tombstoned entities")

	# get
	p_get = subparsers.add_parser("get", parents=[common_parser], help="Get entity projected state")
	p_get.add_argument("pit", help="Pit name")
	p_get.add_argument("id", help="Entity ID")
	p_get.add_argument("--at", help="Point-in-time timestamp")
	p_get.add_argument("--jq", help="Convenience pipe through jq filter")
	p_get.add_argument("--with-deleted", action="store_true", help="Include tombstoned entities")

	# history
	p_hist = subparsers.add_parser("history", parents=[common_parser], help="Dump immutable fragment history for an entity")
	p_hist.add_argument("pit", help="Pit name")
	p_hist.add_argument("id", help="Entity ID")
	p_hist.add_argument("--jq", help="Convenience pipe through jq filter")

	# list
	p_list = subparsers.add_parser("list", parents=[common_parser], help="List active entities in a Pit")
	p_list.add_argument("pit", help="Pit name")
	p_list.add_argument("--json", action="store_true", help="Output JSON array")
	p_list.add_argument("--jq", help="Convenience pipe through jq filter")

	# put
	p_put = subparsers.add_parser("put", parents=[common_parser], help="Ingest JSON5 entities from file or stdin pipe")
	p_put.add_argument("pit", help="Pit name")
	p_put.add_argument("source", nargs="?", default="-", help="Source file or '-' for stdin")

	# set
	p_set = subparsers.add_parser("set", parents=[common_parser], help="Set or patch entity with JSON5 payload")
	p_set.add_argument("pit", help="Pit name")
	p_set.add_argument("id", help="Entity ID")
	p_set.add_argument("payload", help="JSON5 dictionary payload")

	# del
	p_del = subparsers.add_parser("del", parents=[common_parser], help="Tombstone an entity")
	p_del.add_argument("pit", help="Pit name")
	p_del.add_argument("id", help="Entity ID")
	p_del.add_argument("--by", help="Audited author identity")

	# del-prop
	p_delprop = subparsers.add_parser("del-prop", parents=[common_parser], help="Tombstone a property path")
	p_delprop.add_argument("pit", help="Pit name")
	p_delprop.add_argument("id", help="Entity ID")
	p_delprop.add_argument("property_path", help="Dot-delimited property path")

	# export
	p_export = subparsers.add_parser("export", parents=[common_parser], help="Export entities as JSON array")
	p_export.add_argument("pit", help="Pit name")
	p_export.add_argument("--out", help="Output file path (default stdout)")
	p_export.add_argument("--at", help="Project state as of timestamp")
	p_export.add_argument("--jq", help="Convenience pipe through jq filter")

	# status
	p_status = subparsers.add_parser("status", parents=[common_parser], help="Inspect Pit directory lease and flags")
	p_status.add_argument("pit", help="Pit name")

	return parser


def main(argv: list[str] | None = None) -> int:
	parser = build_parser()
	args = parser.parse_args(argv)

	if not hasattr(args, "cloud"):
		args.cloud = "OneDrive"
	if not hasattr(args, "root"):
		args.root = None

	dispatch = {
		"grep": cmd_grep,
		"get": cmd_get,
		"history": cmd_history,
		"list": cmd_list,
		"put": cmd_put,
		"set": cmd_set,
		"del": cmd_delete,
		"del-prop": cmd_delete_prop,
		"export": cmd_export,
		"status": cmd_status,
	}

	cmd_func = dispatch.get(args.command)
	if not cmd_func:
		parser.print_help()
		return 1

	try:
		return cmd_func(args)
	except JsonPitError as ex:
		sys.stderr.write(f"[jpit] Pit error: {ex}\n")
		return 1
	except Exception as ex:
		sys.stderr.write(f"[jpit] Unexpected error: {ex}\n")
		return 2


if __name__ == "__main__":
	sys.exit(main())
