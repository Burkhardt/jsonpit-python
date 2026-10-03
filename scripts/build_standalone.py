#!/usr/bin/env python3
"""
Builds a standalone, zero-dependency, self-contained single-file executable for jpit.
Uses Python's built-in zipapp module. No pip, no pipx, no venv, no third-party tools needed.
Output: dist/jpit (chmod +x, runnable anywhere python3 is present).
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipapp

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "jsonpit"
DIST_DIR = ROOT_DIR / "dist"
OUTPUT_FILE = DIST_DIR / "jpit"


def build_standalone() -> Path:
	DIST_DIR.mkdir(parents=True, exist_ok=True)

	with tempfile.TemporaryDirectory() as tmp_dir_str:
		tmp_dir = Path(tmp_dir_str)
		app_pkg_dir = tmp_dir / "jsonpit"
		app_pkg_dir.mkdir(parents=True, exist_ok=True)

		# Copy all python source files
		for src_file in SRC_DIR.glob("*.py"):
			shutil.copy2(src_file, app_pkg_dir / src_file.name)

		# Write entry point __main__.py
		entry_point = tmp_dir / "__main__.py"
		entry_point.write_text(
			"import sys\n"
			"from jsonpit.cli import main\n\n"
			"if __name__ == '__main__':\n"
			"    sys.exit(main())\n",
			encoding="utf-8",
		)

		if OUTPUT_FILE.exists():
			OUTPUT_FILE.unlink()

		# Build compressed zipapp with standard POSIX python3 shebang
		zipapp.create_archive(
			source=tmp_dir,
			target=OUTPUT_FILE,
			interpreter="/usr/bin/env python3",
			compressed=True,
		)

		# Ensure executable permissions (chmod +x)
		current_mode = os.stat(OUTPUT_FILE).st_mode
		os.chmod(OUTPUT_FILE, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

	size_kb = OUTPUT_FILE.stat().st_size / 1024.0
	print(f"📦 Built standalone self-contained executable: {OUTPUT_FILE} ({size_kb:.1f} KB)")
	return OUTPUT_FILE


if __name__ == "__main__":
	build_standalone()
