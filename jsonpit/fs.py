"""
Cloud-safe filesystem operations and path resolution.
Strictly adheres to CR022: all atomic operations are in-place or sibling writes
within the same cloud folder, never crossing filesystem volume boundaries.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_FILE_LOCATION, OsConfig, missing_configuration_diagnostic
from .exceptions import PitNotFoundError


def resolve_pit_target(
	name_or_path: str | Path,
	cloud: str | None = None,
	root: str | None = None,
	config: OsConfig | None = None,
) -> tuple[Path, str]:
	"""
	Resolves a pit target to its directory Path and canonical Pit name.

	Supported forms:
	1. Cloud triad: Pit.open("Person", cloud="OneDrive", root="AfricaStage")
	   -> (<OneDriveData>/AfricaStage/Person/, "Person")
	2. Explicit directory: Pit.open("/path/to/AfricaStage/Person")
	   -> (/path/to/AfricaStage/Person/, "Person")
	3. Explicit file: Pit.open("/path/to/AfricaStage/Person/Person.pit")
	   -> (/path/to/AfricaStage/Person/, "Person")
	"""
	cfg = config or OsConfig.load()

	raw_str = str(name_or_path).strip()
	is_explicit_path = (
		isinstance(name_or_path, Path)
		or raw_str.startswith(("/", "~", ".", "\\"))
		or ("/" in raw_str and not raw_str.startswith("-"))
		or ("\\" in raw_str)
	)

	if is_explicit_path:
		resolved = Path(os.path.abspath(os.path.expanduser(raw_str)))
		if resolved.suffix.lower() == ".pit":
			pit_dir = resolved.parent
			pit_name = resolved.stem
		else:
			pit_dir = resolved
			pit_name = resolved.name
		return pit_dir, pit_name

	# CR044 §7.4: If attempting cloud triad resolution and no configuration file exists
	if not cfg.is_config_loaded:
		raise PitNotFoundError(missing_configuration_diagnostic())

	# Cloud triad resolution (e.g. name="Person", cloud="OneDrive", root="AfricaStage")
	cloud_root = cfg.get_cloud_root(cloud)
	if cloud_root is None:
		raise PitNotFoundError(
			f"Could not resolve cloud storage root for cloud '{cloud or 'default'}'. "
			f"Ensure {DEFAULT_CONFIG_FILE_LOCATION} or ~/.config/jsonpit.json5 is configured."
		)

	pit_name = raw_str
	target_dir = cloud_root
	if root:
		target_dir = target_dir / root
	target_dir = target_dir / pit_name

	return target_dir, pit_name


def ensure_directory(path: Path | str) -> Path:
	"""Ensures the directory exists, creating intermediate parents if needed."""
	p = Path(path)
	p.mkdir(parents=True, exist_ok=True)
	return p


def safe_write_in_place(
	file_path: Path,
	content: str,
	backup: bool = False,
	backup_dir: Path | None = None,
) -> None:
	"""
	Writes text content adhering to the CR003/CR022 cloud-safe persistence contract:
	- Creates parent directories if missing.
	- If backup is requested, copies previous content to backup_dir (never moves it).
	- Writes/truncates the existing path directly in place so the canonical pathname
	  never disappears to concurrent readers or triggers cloud delete events.
	"""
	ensure_directory(file_path.parent)

	if backup and file_path.is_file() and backup_dir is not None:
		ensure_directory(backup_dir)
		backup_target = backup_dir / f"{file_path.name}.bak"
		shutil.copy2(file_path, backup_target)

	# In-place write with UTF-8 encoding and no trailing newline added automatically
	with open(file_path, "w", encoding="utf-8", newline="") as f:
		f.write(content)
		f.flush()
		os.fsync(f.fileno())


def safe_write_sibling_tmp(file_path: Path, content: str) -> None:
	"""
	Writes content to an in-place sibling temporary file (e.g. Person.pit.tmp)
	in the exact same directory, followed by an atomic rename on the same volume.
	Guarantees that no cross-device moves occur.
	"""
	ensure_directory(file_path.parent)
	tmp_file = file_path.parent / f"{file_path.name}.tmp"

	with open(tmp_file, "w", encoding="utf-8", newline="") as f:
		f.write(content)
		f.flush()
		os.fsync(f.fileno())

	tmp_file.replace(file_path)


def safe_read_text(file_path: Path) -> str | None:
	"""Reads file content as UTF-8 string, returning None if missing or unreadable."""
	if not file_path.is_file():
		return None
	try:
		with open(file_path, "r", encoding="utf-8") as f:
			return f.read()
	except (OSError, UnicodeDecodeError):
		return None


def safe_delete_file(file_path: Path) -> bool:
	"""Safely deletes a file if it exists, returning True if successfully removed."""
	try:
		if file_path.is_file():
			file_path.unlink(missing_ok=True)
			return not file_path.exists()
		return True
	except OSError:
		return False
