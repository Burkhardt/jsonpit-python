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
	StrictPatchValidationError,
	TombstoneError,
)
from .audit import (
	LogLevel,
	PitAudit,
	PitAuditEvent,
	PitAuditReadResult,
)
from .config import DEFAULT_CONFIG_FILE_LOCATION, OsConfig, missing_configuration_diagnostic
from .history import PitItems
from .icons import Icons
from .item import PitItem
from .store import (
	Pit,
	PitMaintenanceOptions,
	PitMaintenanceResult,
	PitStore,
	parse_and_validate_seed_payload,
)

__version__ = "4.4.7"

__all__ = [
	"Pit",
	"PitStore",
	"PitMaintenanceOptions",
	"PitMaintenanceResult",
	"parse_and_validate_seed_payload",
	"PitItem",
	"PitItems",
	"LogLevel",
	"PitAuditEvent",
	"PitAuditReadResult",
	"PitAudit",
	"OsConfig",
	"DEFAULT_CONFIG_FILE_LOCATION",
	"missing_configuration_diagnostic",
	"Icons",
	"JsonPitError",
	"PitNotFoundError",
	"PitCorruptError",
	"PitConcurrencyError",
	"PitInstanceConflictError",
	"ProtectedAttributeError",
	"StrictPatchValidationError",
	"TombstoneError",
]
