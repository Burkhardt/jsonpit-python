"""
jsonpit — Cloud-first, eventually-consistent replicated storage engine in pure Python.
100% C# JsonPit parity · Zero third-party runtime dependencies.
"""

from .canonical import (
	utcnow,
)
from .exceptions import (
	JsonPitError,
	ObjectDisposedError,
	PitConcurrencyError,
	PitCorruptError,
	PitDisposedError,
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
	MutationTrackingMode,
	Pit,
	PitMaintenanceOptions,
	PitMaintenanceResult,
	PitStore,
	TimeValue,
	parse_and_validate_seed_payload,
)

__version__ = "4.5.5"

__all__ = [
	"Pit",
	"PitStore",
	"MutationTrackingMode",
	"TimeValue",
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
	"ObjectDisposedError",
	"PitDisposedError",
	"PitNotFoundError",
	"PitCorruptError",
	"PitConcurrencyError",
	"PitInstanceConflictError",
	"ProtectedAttributeError",
	"StrictPatchValidationError",
	"TombstoneError",
	"utcnow",
]
