"""
Read-only audit access to durable JsonPit recovery events (CR003, coordinated v3.13.2).
Inspects immutable event logs and compact archives without opening a Pit,
creating process activity windows, or mutating storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from enum import IntEnum
import json
from pathlib import Path
from typing import Any
import zipfile

from .canonical import format_iso_timestamp, parse_iso_timestamp, utc_ticks_to_datetime
from .flags import get_machine_name
from .fs import safe_read_text


class LogLevel(IntEnum):
	"""Standard severity levels for Pit audit events matching .NET LogLevel."""
	TRACE = 0
	DEBUG = 1
	INFORMATION = 2
	WARNING = 3
	ERROR = 4
	CRITICAL = 5

	@classmethod
	def from_string(cls, name: str) -> LogLevel:
		norm = name.strip().lower()
		if norm in ("trace", "0"):
			return cls.TRACE
		if norm in ("debug", "1"):
			return cls.DEBUG
		if norm in ("information", "info", "2"):
			return cls.INFORMATION
		if norm in ("warning", "warn", "3"):
			return cls.WARNING
		if norm in ("error", "err", "4"):
			return cls.ERROR
		if norm in ("critical", "crit", "fatal", "5"):
			return cls.CRITICAL
		raise ValueError(
			f"Unknown log level '{name}'. Valid levels: Trace, Debug, Information, Warning, Error, Critical."
		)

	@property
	def display_name(self) -> str:
		if self == LogLevel.INFORMATION:
			return "Information"
		return self.name.capitalize()


@dataclass
class PitAuditEvent:
	"""One durable JsonPit audit event as read back from a pit's Events directory."""
	file_name: str
	content: dict[str, Any]
	machine: str
	utc_time: datetime.datetime
	level: LogLevel
	stage: str
	event_id: str
	message: str

	@classmethod
	def from_dict(cls, file_name: str, content: dict[str, Any]) -> PitAuditEvent:
		machine = str(content.get("Machine") or "")

		# Parse timestamp from UtcTicks or UtcTime
		ticks = content.get("UtcTicks")
		if ticks is not None and isinstance(ticks, (int, float)):
			utc_time = utc_ticks_to_datetime(int(ticks))
		elif content.get("UtcTime"):
			try:
				utc_time = parse_iso_timestamp(str(content["UtcTime"]))
			except Exception:
				utc_time = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
		else:
			utc_time = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

		lvl_raw = str(content.get("Level") or "Trace")
		try:
			level = LogLevel.from_string(lvl_raw)
		except ValueError:
			level = LogLevel.TRACE

		stage = str(content.get("Stage") or "")
		event_id = str(content.get("EventId") or "")
		message = str(content.get("Message") or "")

		return cls(
			file_name=file_name,
			content=content,
			machine=machine,
			utc_time=utc_time,
			level=level,
			stage=stage,
			event_id=event_id,
			message=message,
		)


@dataclass
class PitAuditReadResult:
	"""Read result containing filtered events and physical diagnostic issues."""
	events: list[PitAuditEvent] = field(default_factory=list)
	issues: list[str] = field(default_factory=list)

	@property
	def succeeded(self) -> bool:
		return len(self.issues) == 0


class PitAudit:
	"""Read-only audit inspector for durable JsonPit event logs (Events/)."""

	@staticmethod
	def inspect(
		pit_directory: Path | str,
		machine_filter: str = "all",
		min_level: LogLevel = LogLevel.TRACE,
	) -> PitAuditReadResult:
		p_dir = Path(pit_directory)
		events_dir = p_dir / "Events"
		issues: list[str] = []

		if not events_dir.is_dir():
			return PitAuditReadResult(events=[], issues=[])

		raw_events: dict[str, dict[str, Any]] = {}

		# 1. Inspect loose event files (*.event)
		for ef in sorted(events_dir.glob("*.event"), key=lambda p: p.name):
			try:
				text = safe_read_text(ef)
				if not text or not text.strip():
					issues.append(f"Empty loose event '{ef.name}'")
					continue
				parsed = json.loads(text)
				if not isinstance(parsed, dict):
					issues.append(f"Invalid loose event '{ef.name}': content is not a JSON object")
					continue
				raw_events[ef.name] = parsed
			except Exception as ex:
				issues.append(f"Unreadable loose event '{ef.name}': {ex}")

		# 2. Inspect immutable zip archives (Events_*.zip)
		for zf_path in sorted(events_dir.glob("Events_*.zip"), key=lambda p: p.name):
			try:
				with zipfile.ZipFile(zf_path, "r") as zf:
					for info in zf.infolist():
						if info.filename.endswith(".event"):
							try:
								with zf.open(info) as z_entry:
									text = z_entry.read().decode("utf-8")
									parsed = json.loads(text)
									if isinstance(parsed, dict):
										if info.filename in raw_events:
											if raw_events[info.filename] != parsed:
												issues.append(
													f"Conflicting event content for '{info.filename}' in '{zf_path.name}'."
												)
										else:
											raw_events[info.filename] = parsed
							except Exception as ex:
								issues.append(f"Invalid event '{info.filename}' in '{zf_path.name}': {ex}")
			except Exception as ex:
				issues.append(f"Invalid event archive '{zf_path.name}': {ex}")

		# 3. Deduplicate events by EventId
		identities: dict[str, PitAuditEvent] = {}
		distinct: list[PitAuditEvent] = []
		for file_name in sorted(raw_events.keys()):
			content = raw_events[file_name]
			ev = PitAuditEvent.from_dict(file_name, content)
			if not ev.event_id:
				distinct.append(ev)
				continue

			if ev.event_id not in identities:
				identities[ev.event_id] = ev
				distinct.append(ev)
			else:
				existing = identities[ev.event_id]
				if existing.content != ev.content:
					issues.append(
						f"Conflicting event content for EventId '{ev.event_id}' in "
						f"'{existing.file_name}' and '{ev.file_name}'."
					)

		# 4. Filter by machine
		m_filt = (machine_filter or "all").strip().lower()
		events = distinct
		if m_filt != "all":
			target_machine = get_machine_name().lower() if m_filt == "local" else m_filt
			events = [e for e in events if e.machine.lower() == target_machine]

		# 5. Filter by severity level
		if min_level > LogLevel.TRACE:
			events = [e for e in events if e.level >= min_level]

		# 6. Order deterministically: Machine, UtcTime, EventId
		events.sort(key=lambda e: (e.machine, e.utc_time, e.event_id))

		return PitAuditReadResult(events=events, issues=issues)
