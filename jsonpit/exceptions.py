"""
Domain exceptions for the jsonpit library.
"""


class JsonPitError(Exception):
	"""Base exception for all jsonpit domain errors."""


class PitNotFoundError(JsonPitError):
	"""Raised when an explicit pit target directory or file does not exist."""


class PitCorruptError(JsonPitError):
	"""Raised when a pit file or change artifact contains invalid or corrupt JSON."""


class PitConcurrencyError(JsonPitError):
	"""Raised when a process conflict or lease expiration occurs."""


class PitInstanceConflictError(PitConcurrencyError):
	"""Raised when attempting to open a second live pit instance for the same canonical path."""


class TombstoneError(JsonPitError):
	"""Raised when attempting an invalid operation on a tombstoned property or item."""


class ProtectedAttributeError(JsonPitError, ValueError):
	"""Raised when attempting to manually mutate or inject protected lifecycle attributes (Modified, Deleted, Id)."""
