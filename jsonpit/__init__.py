"""
jsonpit — Cloud-first, eventually-consistent replicated storage engine in pure Python.
100% C# JsonPit parity · Zero third-party runtime dependencies.
"""

from .exceptions import (
	JsonPitError,
	PitConcurrencyError,
	PitCorruptError,
	PitInstanceConflictError,
	PitNotFoundError,
	TombstoneError,
)
from .fs import OsConfig
from .history import PitItems
from .item import PitItem
try:
	import importlib.metadata
	__version__ = importlib.metadata.version("jsonpit")
except Exception:
	__version__ = "0.1.2"

__all__ = [
	"Pit",
	"PitItem",
	"PitItems",
	"OsConfig",
	"JsonPitError",
	"PitNotFoundError",
	"PitCorruptError",
	"PitConcurrencyError",
	"PitInstanceConflictError",
	"TombstoneError",
]
