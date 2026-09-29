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
	ProtectedAttributeError,
	TombstoneError,
)
from .fs import OsConfig
from .history import PitItems
from .icons import Icons
from .item import PitItem
from .store import Pit, PitStore, parse_and_validate_seed_payload

try:
	import importlib.metadata
	__version__ = importlib.metadata.version("jsonpit")
except Exception:
	__version__ = "4.4.3"

__all__ = [
	"Pit",
	"PitStore",
	"parse_and_validate_seed_payload",
	"PitItem",
	"PitItems",
	"OsConfig",
	"Icons",
	"JsonPitError",
	"PitNotFoundError",
	"PitCorruptError",
	"PitConcurrencyError",
	"PitInstanceConflictError",
	"ProtectedAttributeError",
	"TombstoneError",
]
