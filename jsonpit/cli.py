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
from .config import OsConfig, loads_json5, missing_configuration_diagnostic
from .exceptions import (
	JsonPitError,
	PitNotFoundError,
	ProtectedAttributeError,
	StrictPatchValidationError,
)
from .fs import resolve_pit_target
from .item import PitItem
from .icons import Icons
from .store import Pit, parse_and_validate_seed_payload
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
	raw_str = str(target).strip()
	is_explicit_path = (
		raw_str.startswith(("/", "~", ".", "\\"))
		or ("/" in raw_str and not raw_str.startswith("-"))
		or ("\\" in raw_str)
		or Path(raw_str).exists()
	)
	if is_explicit_path:
		try:
			p_dir, p_name = resolve_pit_target(target, cloud=cloud, root=root)
			if (p_dir / f"{p_name}.pit").is_file() or p_dir.is_dir():
				return [(p_dir, p_name)]
		except Exception:
			pass
		if Path(target).is_dir():
			discovered = []
			for child in sorted(Path(target).iterdir()):
				if child.is_dir():
					pit_file = child / f"{child.name}.pit"
					if pit_file.is_file():
						discovered.append((child, child.name))
			if discovered:
				return discovered

	# Target requires cloud resolution
	cfg = OsConfig.load()
	if not cfg.is_config_loaded and not is_explicit_path:
		raise PitNotFoundError(missing_configuration_diagnostic())

	cloud_root = cfg.get_cloud_root(cloud)
	candidates: list[Path] = []
	if cloud_root and (cloud_root / target).is_dir():
		candidates.append(cloud_root / target)

	discovered: list[tuple[Path, str]] = []
	for candidate_root in candidates:
		for child in sorted(candidate_root.iterdir()):
			if child.is_dir():
				pit_file = child / f"{child.name}.pit"
				if pit_file.is_file():
					discovered.append((child, child.name))

	if discovered:
		return discovered

	# Fallback single pit target
	p_dir, p_name = resolve_pit_target(target, cloud=cloud, root=root)
	if (p_dir / f"{p_name}.pit").is_file() or p_dir.is_dir():
		return [(p_dir, p_name)]
	return []


def discover_root_pits(root: str | None, cloud: str | None = "OneDrive") -> list[str]:
	"""Discovers all pit names under a resolved tenant root directory."""
	if not root:
		return []
	raw_str = str(root).strip()
	p = Path(os.path.expanduser(raw_str))
	if p.is_dir():
		candidate: Path | None = p
	else:
		cfg = OsConfig.load()
		if not cfg.is_config_loaded:
			raise PitNotFoundError(missing_configuration_diagnostic())
		cloud_root = cfg.get_cloud_root(cloud or "OneDrive")
		candidate = cloud_root / root if cloud_root else None

	if not candidate or not candidate.is_dir():
		return []

	found: list[str] = []
	for child in sorted(candidate.iterdir()):
		if child.is_dir():
			pit_file = child / f"{child.name}.pit"
			if pit_file.is_file():
				found.append(child.name)
		elif child.suffix.lower() == ".pit":
			found.append(child.stem)
	return sorted(list(dict.fromkeys(found)))


def extract_cloud_and_root(argv: list[str]) -> tuple[str, str | None]:
	"""Extracts -c/--cloud and -r/--root options from CLI token list."""
	cloud = "OneDrive"
	root = None
	i = 0
	while i < len(argv):
		arg = argv[i]
		if arg in ("-c", "--cloud") and i + 1 < len(argv):
			cloud = argv[i + 1]
			i += 2
		elif arg.startswith("--cloud="):
			cloud = arg.split("=", 1)[1]
			i += 1
		elif arg in ("-r", "--root") and i + 1 < len(argv):
			root = argv[i + 1]
			i += 2
		elif arg.startswith("--root="):
			root = arg.split("=", 1)[1]
			i += 1
		else:
			i += 1
	return cloud, root


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


def cmd_pits(args: argparse.Namespace) -> int:
	"""Discovers and lists available pits under the tenant root (-r is required)."""
	use_color = should_color()
	root = getattr(args, "root", None)
	cloud = getattr(args, "cloud", "OneDrive")
	if not root:
		err_content = color(f"{Icons.ERROR} error: -r/--root is required to list pits (e.g. -r AIA)", C_BOLD + C_RED, use_color)
		sys.stderr.write(f"jpit pits: {err_content}\n")
		return 1

	pits = discover_root_pits(root, cloud)
	if getattr(args, "json", False):
		sys.stdout.write(json.dumps(pits, indent=2) + "\n")
		return 0

	if not pits:
		sys.stderr.write(f"No pits found under tenant root '{root}'.\n")
		return 1

	for p in pits:
		sys.stdout.write(f"{p}\n")
	return 0


def cmd_list(args: argparse.Namespace) -> int:
	"""Lists active entities in a Pit, or available pits if <pit> is omitted."""
	if not getattr(args, "pit", None):
		return cmd_pits(args)

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
	CR043: Supports single root entity, keyed entity map, or entity array.
	CR047: Strict patch mode via --require-existing or --patch.
	"""
	require_existing = bool(getattr(args, "require_existing", False) or getattr(args, "patch", False))
	source_path_str = getattr(args, "source", None)
	if not source_path_str and getattr(args, "source_opt", None):
		source_path_str = args.source_opt
	if not source_path_str:
		source_path_str = "-"

	# Read source content
	content = ""
	if source_path_str != "-":
		path = Path(source_path_str)
		if not path.is_file():
			sys.stderr.write(f"[jpit] Source file not found: {path}\n")
			return 1
		content = path.read_text(encoding="utf-8")
		source_name = str(path)
	else:
		content = sys.stdin.read()
		source_name = "<stdin>"

	# CR043 Pre-flight validation strictly before opening target Pit or creating directories
	try:
		items_to_add = parse_and_validate_seed_payload(content, source_name)
	except (ValueError, ProtectedAttributeError) as ex:
		sys.stderr.write(f"[jpit] Error: {ex}\n")
		return 1

	if require_existing and not items_to_add:
		sys.stderr.write("error: Patch source contained 0 entities.\n")
		return 1

	if not items_to_add:
		print(f"[jpit] Seed source '{source_name}' contained 0 entities.")
		return 0

	# CR047: Strict patch mode pre-validation before opening target Pit for writing or creating flags
	if require_existing:
		try:
			with Pit.open(
				args.pit,
				cloud=args.cloud,
				root=args.root,
				read_only=True,
				unflagged=True,
			) as living_state:
				for raw_obj in items_to_add:
					item_id = raw_obj["Id"]
					if not living_state.contains(item_id, with_deleted=False):
						sys.stderr.write(
							f"error: Entity '{item_id}' does not exist in Pit '{living_state.pit_name}'. "
							"Use without --require-existing / --patch to allow creating new entities.\n"
						)
						return 1
		except PitNotFoundError:
			sys.stderr.write(
				f"error: Entity '{items_to_add[0]['Id']}' does not exist in Pit '{args.pit}'. "
				"Use without --require-existing / --patch to allow creating new entities.\n"
			)
			return 1
		except Exception as ex:
			sys.stderr.write(f"[jpit] Error: {ex}\n")
			return 1

	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		retain_window=getattr(args, "retain_window", False),
	) as pit:
		count = 0
		for raw_obj in items_to_add:
			item = PitItem(raw_obj)
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

	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		retain_window=getattr(args, "retain_window", False),
	) as pit:
		existing = pit.get(args.id)
		if existing is not None:
			existing.set_property(payload)
		else:
			delta = dict(payload)
			delta["Id"] = args.id
			pit.add(PitItem(delta))

	print(f"[jpit] Updated entity '{args.id}' in Pit '{args.pit}'.")
	return 0


def cmd_delete(args: argparse.Namespace) -> int:
	"""Tombstones an entity with audited author note and 100s backdating."""
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		retain_window=getattr(args, "retain_window", False),
	) as pit:
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

	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		retain_window=getattr(args, "retain_window", False),
	) as pit:
		item = pit.get(args.id)
		if item is None:
			sys.stderr.write(f"[jpit] Entity '{args.id}' not found.\n")
			return 1
		item.delete_property_path(args.property_path)

	print(f"[jpit] Tombstoned property '{args.property_path}' on entity '{args.id}'.")
	return 0


def cmd_rename(args: argparse.Namespace) -> int:
	"""Migrates state from old_id to new_id and tombstones old_id."""
	with Pit.open(
		args.pit,
		cloud=args.cloud,
		root=args.root,
		retain_window=getattr(args, "retain_window", False),
	) as pit:
		success = pit.rename_id(args.old_id, args.new_id, by=args.by)
		if not success:
			sys.stderr.write(
				f"[jpit] Failed to rename '{args.old_id}' to '{args.new_id}' "
				f"(check if '{args.old_id}' exists or '{args.new_id}' is already taken).\n"
			)
			return 1

	print(f"[jpit] Renamed entity '{args.old_id}' -> '{args.new_id}' in Pit '{args.pit}'.")
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


# ANSI escape codes for Option B multi-token highlights
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_BRIGHT_GREEN = "\033[92m"
C_CYAN = "\033[36m"
C_BRIGHT_CYAN = "\033[96m"
C_YELLOW = "\033[33m"
C_BRIGHT_YELLOW = "\033[93m"
C_BLUE = "\033[34m"
C_BRIGHT_BLUE = "\033[94m"
C_MAGENTA = "\033[35m"
C_BRIGHT_MAGENTA = "\033[95m"
C_RED = "\033[31m"
C_BRIGHT_RED = "\033[91m"
C_WHITE = "\033[37m"
C_BRIGHT_WHITE = "\033[97m"

# Deterministic positional badge palette for multi-option listings
# 1st: Cyan, 2nd: Green, 3rd: Blue, 4th: Red, 5th: Magenta, 6th: Violet, etc.
# Note: Yellow is intentionally omitted to reserve it exclusively for directory/folder glyphs.
OPTION_BADGE_COLORS: list[str] = [
	C_BRIGHT_CYAN,       # 1st: Cyan
	C_BRIGHT_GREEN,      # 2nd: Green
	C_BRIGHT_BLUE,       # 3rd: Blue
	C_BRIGHT_RED,        # 4th: Red (matching ICloudDrive)
	C_MAGENTA,           # 5th: Magenta
	C_BRIGHT_MAGENTA,    # 6th: Violet / Bright Magenta
	C_CYAN,              # 7th: Deep Cyan
	C_BLUE,              # 8th: Deep Blue
]


def should_color() -> bool:
	"""Determines if colored terminal output should be emitted."""
	if os.getenv("NO_COLOR"):
		return False
	if os.getenv("TERM") == "dumb":
		return False
	return True


def color(text: str, code: str, use_color: bool = True) -> str:
	"""Wraps text in ANSI escape sequence if color is enabled."""
	if not use_color:
		return text
	return f"{code}{text}{C_RESET}"


def get_cloud_options_description(use_color: bool = True) -> str:
	"""Builds the cloud provider options line with brand-specific badge glyphs."""
	try:
		cfg = OsConfig.load()
		order = cfg.default_cloud_order
		available = [c for c in order if c in cfg.clouds]
	except Exception:
		available = ["OneDrive", "Dropbox", "GoogleDrive", "ICloudDrive"]

	if not available:
		available = ["OneDrive", "Dropbox", "GoogleDrive", "ICloudDrive"]

	formatted = []
	for idx, name in enumerate(available):
		glyph = Icons.cloud_provider_icon(name, idx + 1)
		badge_color = OPTION_BADGE_COLORS[idx % len(OPTION_BADGE_COLORS)]
		badge = color(glyph, badge_color, use_color)
		default_str = " (default)" if idx == 0 else ""
		formatted.append(f"{badge} {name}{default_str}")

	return ", ".join(formatted)


def print_banner(use_color: bool = True) -> None:
	"""Prints the signature double-bordered jpit banner."""
	bar_icon = color(Icons.BANNER, C_CYAN, use_color)
	rule = color("────────────────────────────", C_CYAN, use_color)
	info_icon = color(Icons.INFO, C_CYAN, use_color)
	# Use bold cyan to match the border and guarantee high contrast on both light and dark backgrounds
	title = color(f"jsonpit CLI (jpit v{__version__})", C_BOLD + C_CYAN, use_color)
	sys.stdout.write(f"{bar_icon} {rule}\n")
	sys.stdout.write(f"{info_icon} {title}\n")
	sys.stdout.write(f"{bar_icon} {rule}\n")


def print_top_help(
	nologo: bool = False,
	use_color: bool = True,
	root: str | None = None,
	cloud: str | None = "OneDrive",
) -> None:
	"""Prints the branded jpit help screen with Nerd Font glyphs and multi-token ANSI accents."""
	if not nologo:
		print_banner(use_color=use_color)

	c_cmd = color("Commands:", C_BOLD + C_GREEN, use_color)
	i_info = color(Icons.INFO, C_CYAN, use_color)
	i_help = color(Icons.HELP, C_GREEN, use_color)
	i_folder = color(Icons.FOLDER, C_YELLOW, use_color)
	i_banner = color(Icons.BANNER, C_CYAN, use_color)

	cmd_list = "grep, get, history, list, put, set, del, del-prop, rename, export, status, pits"
	sys.stdout.write(f"{c_cmd}\t{i_info}\t{cmd_list}\n")

	commands_spec = [
		("grep", "<pattern> [<target>] [-i] [-e] [-p <prop>] [--at <ts>] [--json] [--jq <expr>]"),
		("get", "<PitName> <ItemId> [--at <ts>] [--jq <expr>] [--with-deleted]"),
		("history", "<PitName> <ItemId> [--jq <expr>]"),
		("list", "[<PitName>] [--json] [--jq <expr>] (lists pits if <PitName> omitted)"),
		("put", "<PitName> [<source>] [-s <source>] (alias: seed)"),
		("set", "<PitName> <ItemId> <payload>"),
		("del", "<PitName> <ItemId> [--by <author>]"),
		("del-prop", "<PitName> <ItemId> <PropertyPath>"),
		("rename", "<PitName> <OldId> <NewId> [--by <author>]"),
		("export", "<PitName> [--out <file>] [--at <ts>] [--jq <expr>]"),
		("status", "<PitName>"),
		("pits", "[-r <root>] [-c <cloud>] [--json] (discover available pits)"),
	]
	for cmd, spec in commands_spec:
		cmd_str = color(f"  jpit {cmd}", C_GREEN, use_color)
		sys.stdout.write(f"{cmd_str} {spec}\n")

	cloud_desc = get_cloud_options_description(use_color=use_color)

	root_desc = (
		f"root directory or tenant (current: {root})"
		if root
		else "root directory or tenant (e.g. AIA, AfricaStage)"
	)

	options_spec = [
		("-h, --help", i_help, "print out all options"),
		("-v, --version", i_info, "print version info"),
		("-n, --nologo", i_banner, "do not display the banner"),
		("-r, --root", i_folder, root_desc),
		("-c, --cloud", i_folder, cloud_desc),
		("--retain-window", i_info, "keep the activity window until timeout"),
	]

	for opt, icon, desc in options_spec:
		sys.stdout.write(f"{opt}\t{icon}\t{desc}\n")

	# Dynamic Pits Discovery line
	pits_title = color(f"{Icons.INFO} PitNames", C_CYAN, use_color)
	if root:
		try:
			discovered = discover_root_pits(root, cloud)
		except Exception:
			discovered = []
		if discovered:
			formatted_pits = []
			for idx, p in enumerate(discovered):
				badge = Icons.letter_box_outline(p)
				b_col = OPTION_BADGE_COLORS[idx % len(OPTION_BADGE_COLORS)]
				c_badge = color(badge, b_col, use_color)
				formatted_pits.append(f"{c_badge} {p}")
			pits_str = ", ".join(formatted_pits)
		else:
			pits_str = color("(no pits found)", C_DIM, use_color)
		sys.stdout.write(f"{pits_title}\t{i_folder}\t{pits_str}\n")
	else:
		hint = "specify -r <root> (e.g. -r AIA) to discover pits"
		sys.stdout.write(f"{pits_title}\t{i_folder}\t{hint}\n")


def print_command_help(cmd: str, nologo: bool = False, use_color: bool = True) -> None:
	"""Prints formatted help for an individual subcommand."""
	if not nologo:
		print_banner(use_color=use_color)

	alias_map = {
		"delete": "del",
		"delete-item": "del",
		"delete-property": "del-prop",
		"seed": "put",
	}
	canonical_cmd = alias_map.get(cmd, cmd)

	help_data: dict[str, dict[str, Any]] = {
		"grep": {
			"usage": "jpit grep <pattern> [<target>] [options]",
			"desc": "Ripgrep-style living state semantic search across pits.",
			"args": [
				("pattern", "Text or regex to match"),
				("target", "Pit name, file path, or tenant root (default: current directory)"),
			],
			"opts": [
				("-i, --ignore-case", "Case-insensitive search"),
				("-e, --regex", "Treat pattern as regex"),
				("-p, --property <path>", "Scope search to a specific property path"),
				("--at <timestamp>", "Project state as of ISO-8601 timestamp"),
				("--json", "Output JSON stream for piping to jq"),
				("--jq <expr>", "Convenience pipe through jq filter"),
				("--with-deleted", "Include tombstoned entities"),
			],
		},
		"get": {
			"usage": "jpit get <PitName> <ItemId> [options]",
			"desc": "Get entity projected state.",
			"args": [
				("PitName", "Pit name or file path"),
				("ItemId", "Entity ID to retrieve"),
			],
			"opts": [
				("--at <timestamp>", "Point-in-time timestamp"),
				("--jq <expr>", "Convenience pipe through jq filter"),
				("--with-deleted", "Include tombstoned entities"),
			],
		},
		"history": {
			"usage": "jpit history <PitName> <ItemId> [options]",
			"desc": "Dump immutable fragment history for an entity.",
			"args": [
				("PitName", "Pit name or file path"),
				("ItemId", "Entity ID"),
			],
			"opts": [
				("--jq <expr>", "Convenience pipe through jq filter"),
			],
		},
		"list": {
			"usage": "jpit list [<PitName>] [options]",
			"desc": "List active entities in a Pit, or available pits in -r root if <PitName> is omitted.",
			"args": [
				("PitName", "Pit name or file path (optional)"),
			],
			"opts": [
				("--json", "Output JSON array"),
				("--jq <expr>", "Convenience pipe through jq filter"),
			],
		},
		"pits": {
			"usage": "jpit pits [-r <root>] [-c <cloud>] [--json]",
			"desc": "Discover available pits under a tenant root (-r is required).",
			"args": [],
			"opts": [
				("--json", "Output JSON array of pit names"),
			],
		},
		"put": {
			"usage": "jpit put <PitName> [<source>] [-s <source>] [--require-existing] [--patch] [options]",
			"desc": "Ingest JSON5 entities from file or stdin pipe (alias: seed).",
			"args": [
				("PitName", "Pit name or file path"),
				("source", "Source file or '-' for stdin (default: '-')"),
			],
			"opts": [
				("-s, --source <file>", "Source file for import (JSON or JSON5)"),
				("--require-existing", "Reject batch if any entity does not already exist"),
				("--patch", "Alias for --require-existing"),
			],
			"aliases": ["seed"],
		},
		"set": {
			"usage": "jpit set <PitName> <ItemId> <payload> [options]",
			"desc": "Set or patch entity with JSON5 payload.",
			"args": [
				("PitName", "Pit name or file path"),
				("ItemId", "Entity ID"),
				("payload", "JSON5 dictionary payload"),
			],
			"opts": [],
		},
		"del": {
			"usage": "jpit del <PitName> <ItemId> [--by <author>] [options]",
			"desc": "Tombstone an entity (aliases: delete-item, delete).",
			"args": [
				("PitName", "Pit name or file path"),
				("ItemId", "Entity ID to tombstone"),
			],
			"opts": [
				("--by <author>", "Audited author identity"),
			],
			"aliases": ["delete-item", "delete"],
		},
		"del-prop": {
			"usage": "jpit del-prop <PitName> <ItemId> <PropertyPath> [options]",
			"desc": "Tombstone a property path (alias: delete-property).",
			"args": [
				("PitName", "Pit name or file path"),
				("ItemId", "Entity ID"),
				("PropertyPath", "Dot-delimited property path (e.g. What.Chat)"),
			],
			"opts": [],
			"aliases": ["delete-property"],
		},
		"rename": {
			"usage": "jpit rename <PitName> <OldId> <NewId> [--by <author>] [options]",
			"desc": "Migrate entity to new ID and tombstone old ID.",
			"args": [
				("PitName", "Pit name or file path"),
				("OldId", "Current entity ID"),
				("NewId", "New entity ID"),
			],
			"opts": [
				("--by <author>", "Audited author identity"),
			],
		},
		"export": {
			"usage": "jpit export <PitName> [--out <file>] [--at <ts>] [--jq <expr>] [options]",
			"desc": "Export entities as JSON array.",
			"args": [
				("PitName", "Pit name or file path"),
			],
			"opts": [
				("--out <file>", "Output file path (default stdout)"),
				("--at <timestamp>", "Project state as of timestamp"),
				("--jq <expr>", "Convenience pipe through jq filter"),
			],
		},
		"status": {
			"usage": "jpit status <PitName> [options]",
			"desc": "Inspect Pit directory lease and flags.",
			"args": [
				("PitName", "Pit name or file path"),
			],
			"opts": [],
		},
	}

	info = help_data.get(canonical_cmd)
	if not info:
		print_top_help(nologo=nologo, use_color=use_color)
		return

	u_label = color("Usage:", C_BOLD + C_GREEN, use_color)
	sys.stdout.write(f"{u_label} {info['usage']}\n\n")
	sys.stdout.write(f"{info['desc']}\n\n")

	if info["args"]:
		sys.stdout.write(f"{color('Arguments:', C_BOLD + C_CYAN, use_color)}\n")
		for arg, arg_desc in info["args"]:
			sys.stdout.write(f"  {color(arg, C_GREEN, use_color):<24} {arg_desc}\n")
		sys.stdout.write("\n")

	if info["opts"]:
		sys.stdout.write(f"{color('Options:', C_BOLD + C_CYAN, use_color)}\n")
		for opt, opt_desc in info["opts"]:
			sys.stdout.write(f"  {color(opt, C_GREEN, use_color):<24} {opt_desc}\n")
		sys.stdout.write("\n")

	sys.stdout.write(f"{color('Global options:', C_BOLD + C_CYAN, use_color)}\n")
	sys.stdout.write(f"  {color('-c, --cloud <name>', C_GREEN, use_color):<24} Cloud drive (OneDrive, Dropbox, etc.)\n")
	sys.stdout.write(f"  {color('-r, --root <tenant>', C_GREEN, use_color):<24} Root folder / tenant (e.g. AIA, AfricaStage)\n")
	sys.stdout.write(f"  {color('--retain-window', C_GREEN, use_color):<24} Keep the activity window until timeout\n")
	sys.stdout.write(f"  {color('-n, --nologo', C_GREEN, use_color):<24} Do not display the banner\n")
	sys.stdout.write(f"  {color('-h, --help', C_GREEN, use_color):<24} Print command usage\n")

	if info.get("aliases"):
		alias_str = ", ".join(f"'{a}'" for a in info["aliases"])
		a_label = color(f"{Icons.WARNING} Aliases:", C_YELLOW, use_color)
		sys.stdout.write(f"\n{a_label} {alias_str}\n")


def make_terminal_hyperlink(text: str, uri: str, use_color: bool = True) -> str:
	"""Creates an OSC 8 terminal hyperlink with visual accent if terminal allows."""
	if not use_color:
		return text
	return f"\033]8;;{uri}\033\\{color(text, C_CYAN, use_color)}\033]8;;\033\\"


def print_retain_window_help(nologo: bool = False, use_color: bool = True) -> None:
	"""Prints in-depth help, rationale, and specification links for --retain-window."""
	if not nologo:
		print_banner(use_color=use_color)

	opt_name = color("--retain-window", C_BOLD + C_GREEN, use_color)
	sys.stdout.write(f"{color('Option:', C_BOLD + C_CYAN, use_color)}    {opt_name}\n")
	sys.stdout.write(f"{color('Type:', C_BOLD + C_CYAN, use_color)}      Boolean flag (default: False)\n\n")

	sys.stdout.write(f"{color('Summary:', C_BOLD + C_GREEN, use_color)}\n")
	sys.stdout.write("  Keep the ephemeral process activity window file until natural timeout.\n\n")

	sys.stdout.write(f"{color('Lifecycle & Behavior:', C_BOLD + C_GREEN, use_color)}\n")
	sys.stdout.write(
		"  By default, every finite jpit operation registers an ephemeral process activity flag\n"
		"  ({Machine}-{Process}-{PID}.flag) during execution to announce its presence across cloud\n"
		"  drives, and cleanly self-deletes its flag upon process exit (CR024).\n\n"
		"  When --retain-window is specified, jpit deliberately preserves the owned activity flag\n"
		"  on disk upon exit, leaving it active until its 60-second lease window expires naturally.\n"
		"  (Retained for backward compatibility; scheduled for retirement in the next major release).\n\n"
	)

	sys.stdout.write(f"{color('Specification & Documentation:', C_BOLD + C_GREEN, use_color)}\n")
	pkg_dir = Path(__file__).resolve().parent
	doc_cr_file = pkg_dir.parent / "doc" / "CR" / "CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md"
	if doc_cr_file.is_file():
		abs_uri = f"file://{doc_cr_file.as_posix()}#L45"
		rel_jump = "doc/CR/CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md:45"
	else:
		abs_uri = "https://github.com/Burkhardt/jsonpit-python/blob/main/doc/CR/CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md#3---retain-window-compatibility-exception"
		rel_jump = "doc/CR/CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md:45"

	github_uri = "https://github.com/Burkhardt/jsonpit-python/blob/main/doc/CR/CR024_AIA_to_RAIkeep_Ephemeral_Flag_Self_Cleanup.md#3---retain-window-compatibility-exception"

	cr_title = "CR024 — Ephemeral Process-Flag Self-Cleanup (§3: --retain-window compatibility exception)"
	hyperlink = make_terminal_hyperlink(cr_title, abs_uri, use_color=use_color)
	sys.stdout.write(f"  {Icons.HELP} {hyperlink}\n")
	sys.stdout.write(f"    • Local (IDE jump): {color(rel_jump, C_CYAN, use_color)}\n")
	sys.stdout.write(f"    • File URI:         {color(abs_uri, C_DIM, use_color)}\n")
	sys.stdout.write(f"    • GitHub:           {color(github_uri, C_DIM, use_color)}\n\n")


class JsonPitArgumentParser(argparse.ArgumentParser):
	"""Custom ArgumentParser that formats errors with Icons.ERROR and bold red."""

	def error(self, message: str) -> None:
		use_color = should_color()
		self.print_usage(sys.stderr)
		err_content = color(f"{Icons.ERROR} error: {message}", C_BOLD + C_RED, use_color)
		sys.stderr.write(f"{self.prog}: {err_content}\n")
		sys.exit(2)


def get_cli_prog_name(argv0: str | None = None) -> str:
	"""Determines whether CLI is invoked as 'jsonpit' or 'jpit'."""
	if argv0 is None:
		argv0 = sys.argv[0] if sys.argv and sys.argv[0] else "jpit"
	base = Path(argv0).name.lower()
	if base == "jsonpit" or base.startswith("jsonpit"):
		return "jsonpit"
	if "jsonpit" in str(argv0).lower() and "jpit" not in base:
		return "jsonpit"
	return "jpit"


def build_parser(prog: str | None = None) -> JsonPitArgumentParser:
	if prog is None:
		prog = get_cli_prog_name()

	common_parser = JsonPitArgumentParser(add_help=False)
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
	common_parser.add_argument(
		"--retain-window",
		action="store_true",
		default=False,
		help="Keep the activity window until timeout",
	)
	common_parser.add_argument(
		"-n", "--nologo",
		action="store_true",
		default=False,
		help="Do not display the banner",
	)

	parser = JsonPitArgumentParser(
		prog=prog,
		description=f"{prog} — Cloud-first distributed replicated storage CLI and Pit-Grep.",
		parents=[common_parser],
	)
	parser.add_argument(
		"-v",
		"--version",
		action="version",
		version=f"%(prog)s v{__version__}",
	)

	subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JsonPitArgumentParser)

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
	p_list = subparsers.add_parser("list", parents=[common_parser], help="List active entities in a Pit (or available pits if <pit> omitted)")
	p_list.add_argument("pit", nargs="?", default=None, help="Pit name (optional: if omitted, lists available pits in -r root)")
	p_list.add_argument("--json", action="store_true", help="Output JSON array")
	p_list.add_argument("--jq", help="Convenience pipe through jq filter")

	# pits
	p_pits = subparsers.add_parser("pits", parents=[common_parser], help="Discover available pits under a tenant root (-r is required)")
	p_pits.add_argument("--json", action="store_true", help="Output JSON array of pit names")

	# put / seed
	p_put = subparsers.add_parser(
		"put",
		aliases=["seed"],
		parents=[common_parser],
		help="Ingest JSON5 entities from file or stdin pipe (alias: seed)",
	)
	p_put.add_argument("pit", help="Pit name")
	p_put.add_argument("source", nargs="?", default=None, help="Source file or '-' for stdin")
	p_put.add_argument("-s", "--source", dest="source_opt", help="Source file for import (JSON or JSON5)")
	p_put.add_argument(
		"--require-existing",
		action="store_true",
		default=False,
		help="CR047: Strictly require all incoming entity IDs to exist in the Pit",
	)
	p_put.add_argument(
		"--patch",
		action="store_true",
		default=False,
		help="CR047: Alias for --require-existing",
	)

	# set
	p_set = subparsers.add_parser("set", parents=[common_parser], help="Set or patch entity with JSON5 payload")
	p_set.add_argument("pit", help="Pit name")
	p_set.add_argument("id", help="Entity ID")
	p_set.add_argument("payload", help="JSON5 dictionary payload")

	# del / delete-item
	p_del = subparsers.add_parser(
		"del",
		aliases=["delete-item", "delete"],
		parents=[common_parser],
		help="Tombstone an entity (aliases: delete-item, delete)",
	)
	p_del.add_argument("pit", help="Pit name")
	p_del.add_argument("id", help="Entity ID")
	p_del.add_argument("--by", help="Audited author identity")

	# del-prop / delete-property
	p_delprop = subparsers.add_parser(
		"del-prop",
		aliases=["delete-property"],
		parents=[common_parser],
		help="Tombstone a property path (alias: delete-property)",
	)
	p_delprop.add_argument("pit", help="Pit name")
	p_delprop.add_argument("id", help="Entity ID")
	p_delprop.add_argument("property_path", help="Dot-delimited property path")

	# rename
	p_rename = subparsers.add_parser("rename", parents=[common_parser], help="Migrate entity to new ID and tombstone old ID")
	p_rename.add_argument("pit", help="Pit name")
	p_rename.add_argument("old_id", help="Current entity ID")
	p_rename.add_argument("new_id", help="New entity ID")
	p_rename.add_argument("--by", help="Audited author identity")

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
	if argv is None:
		argv = sys.argv[1:]

	use_color = should_color()
	nologo = "-n" in argv or "--nologo" in argv
	cloud, root = extract_cloud_and_root(argv)

	known_subcommands = {
		"grep", "get", "history", "list", "put", "seed", "set", "del",
		"delete", "delete-item", "del-prop", "delete-property",
		"rename", "export", "status", "pits",
	}

	# Quick check for top-level help or no arguments
	if len(argv) == 0 or (len(argv) == 1 and argv[0] in ("-h", "--help")):
		print_top_help(nologo=nologo, use_color=use_color, root=root, cloud=cloud)
		return 0

	# Check for command-specific or option-specific help: e.g. jpit --retain-window -h or jpit grep -h
	is_help = "-h" in argv or "--help" in argv or (len(argv) > 0 and argv[0] == "help")
	if is_help:
		target_cmd = next((a for a in argv if a in known_subcommands), None)
		if "--retain-window" in argv and target_cmd is None:
			print_retain_window_help(nologo=nologo, use_color=use_color)
			return 0
		if target_cmd:
			print_command_help(target_cmd, nologo=nologo, use_color=use_color)
			return 0
		print_top_help(nologo=nologo, use_color=use_color, root=root, cloud=cloud)
		return 0

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
		"pits": cmd_pits,
		"put": cmd_put,
		"seed": cmd_put,
		"set": cmd_set,
		"del": cmd_delete,
		"delete": cmd_delete,
		"delete-item": cmd_delete,
		"del-prop": cmd_delete_prop,
		"delete-property": cmd_delete_prop,
		"rename": cmd_rename,
		"export": cmd_export,
		"status": cmd_status,
	}

	cmd_func = dispatch.get(args.command)
	if not cmd_func:
		print_top_help(nologo=nologo, use_color=use_color, root=root, cloud=cloud)
		return 1

	try:
		return cmd_func(args)
	except JsonPitError as ex:
		err_icon = color(Icons.ERROR, C_BOLD + C_RED, use_color)
		err_label = color("Pit error:", C_BOLD + C_RED, use_color)
		sys.stderr.write(f"{err_icon} {err_label} {ex}\n")
		return 1
	except Exception as ex:
		err_icon = color(Icons.ERROR, C_BOLD + C_RED, use_color)
		err_label = color("Unexpected error:", C_BOLD + C_RED, use_color)
		sys.stderr.write(f"{err_icon} {err_label} {ex}\n")
		return 2


if __name__ == "__main__":
	sys.exit(main())


