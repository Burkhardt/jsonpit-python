#!/usr/bin/env python3
"""Build the jpit zipapp reproducibly from the current Python sources."""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import zipfile

ROOT_DIR = Path(__file__).resolve().parent.parent
ENTRY_POINT = (
	"import sys\nfrom jsonpit.cli import main\n\n"
	"if __name__ == '__main__':\n\tsys.exit(main())\n"
)


def archive_bytes() -> bytes:
	stream = io.BytesIO()
	stream.write(b"#!/usr/bin/env python3\n")
	files = {"__main__.py": ENTRY_POINT.encode("utf-8")}
	files.update({f"jsonpit/{path.name}": path.read_bytes() for path in (ROOT_DIR / "jsonpit").glob("*.py")})
	with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
		for name, content in sorted(files.items()):
			info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
			info.compress_type = zipfile.ZIP_DEFLATED
			info.create_system = 3
			info.external_attr = 0o100644 << 16
			archive.writestr(info, content)
	return stream.getvalue()


def build_standalone(output: Path | None = None) -> Path:
	content = archive_bytes()
	paths = [output] if output else [ROOT_DIR / "dist/jpit", ROOT_DIR / "bin/jpit"]
	for path in paths:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(content)
		path.chmod(0o755)
		print(f"Built {path} ({len(content)} bytes)")
	return paths[0]


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output", type=Path, help="Write only this artifact; leave tracked bin/jpit unchanged.")
	args = parser.parse_args()
	build_standalone(args.output)
