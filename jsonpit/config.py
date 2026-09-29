"""
Configuration loader and pure standard library JSON5 parser.
Reads ~/.config/RAIkeep.json5 (or ~/.config/jsonpit.json5) to discover
cloud storage roots (OneDrive, Dropbox, etc.) and runtime directories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def loads_json5(text: str) -> Any:
	"""
	Parses a JSON5 string into Python dictionaries, lists, strings, numbers, booleans, or None.
	Supports unquoted keys, single and double quotes, trailing commas, line comments (//),
	and block comments (/* ... */) without third-party dependencies.
	"""
	# Step 1: Strip comments while respecting strings
	chars = list(text)
	n = len(chars)
	i = 0
	cleaned: list[str] = []
	in_string: str | None = None
	escape = False

	while i < n:
		c = chars[i]
		if in_string:
			cleaned.append(c)
			if escape:
				escape = False
			elif c == "\\":
				escape = True
			elif c == in_string:
				in_string = None
			i += 1
		else:
			if c in ('"', "'"):
				in_string = c
				cleaned.append(c)
				i += 1
			elif c == "/" and i + 1 < n and chars[i + 1] == "/":
				# Line comment
				i += 2
				while i < n and chars[i] not in ("\r", "\n"):
					i += 1
			elif c == "/" and i + 1 < n and chars[i + 1] == "*":
				# Block comment
				i += 2
				while i + 1 < n and not (chars[i] == "*" and chars[i + 1] == "/"):
					i += 1
				i += 2
			else:
				cleaned.append(c)
				i += 1

	cleaned_str = "".join(cleaned)
	pos = 0
	length = len(cleaned_str)

	def skip_ws() -> None:
		nonlocal pos
		while pos < length and cleaned_str[pos].isspace():
			pos += 1

	def parse_value() -> Any:
		skip_ws()
		if pos >= length:
			raise ValueError("Unexpected end of JSON5 input")
		ch = cleaned_str[pos]
		if ch == "{":
			return parse_object()
		elif ch == "[":
			return parse_array()
		elif ch in ('"', "'"):
			return parse_string()
		elif ch in ("t", "f"):
			return parse_bool()
		elif ch == "n":
			return parse_null()
		else:
			return parse_number_or_ident()

	def parse_string() -> str:
		nonlocal pos
		quote = cleaned_str[pos]
		pos += 1
		res: list[str] = []
		while pos < length:
			c = cleaned_str[pos]
			if c == "\\":
				pos += 1
				if pos >= length:
					raise ValueError("Unterminated escape sequence")
				esc = cleaned_str[pos]
				if esc == "n":
					res.append("\n")
				elif esc == "r":
					res.append("\r")
				elif esc == "t":
					res.append("\t")
				elif esc == "\\":
					res.append("\\")
				elif esc == quote:
					res.append(quote)
				elif esc == "/":
					res.append("/")
				else:
					res.append(esc)
				pos += 1
			elif c == quote:
				pos += 1
				return "".join(res)
			else:
				res.append(c)
				pos += 1
		raise ValueError("Unterminated string literal")

	def parse_object() -> dict[str, Any]:
		nonlocal pos
		pos += 1  # skip {
		obj: dict[str, Any] = {}
		while True:
			skip_ws()
			if pos >= length:
				raise ValueError("Unterminated JSON5 object")
			if cleaned_str[pos] == "}":
				pos += 1
				return obj
			# Key: either quoted string or bare identifier
			if cleaned_str[pos] in ('"', "'"):
				key = parse_string()
			else:
				k_start = pos
				while pos < length and (
					cleaned_str[pos].isalnum() or cleaned_str[pos] in ("_", "$", "-")
				):
					pos += 1
				key = cleaned_str[k_start:pos]
				if not key:
					raise ValueError(f"Invalid key at position {pos}")
			skip_ws()
			if pos >= length or cleaned_str[pos] != ":":
				raise ValueError(f"Expected ':' at position {pos}")
			pos += 1  # skip :
			val = parse_value()
			obj[key] = val
			skip_ws()
			if pos < length and cleaned_str[pos] == ",":
				pos += 1
				skip_ws()
			elif pos < length and cleaned_str[pos] == "}":
				pass
			else:
				raise ValueError(f"Expected ',' or '}}' at position {pos}")

	def parse_array() -> list[Any]:
		nonlocal pos
		pos += 1  # skip [
		arr: list[Any] = []
		while True:
			skip_ws()
			if pos >= length:
				raise ValueError("Unterminated JSON5 array")
			if cleaned_str[pos] == "]":
				pos += 1
				return arr
			val = parse_value()
			arr.append(val)
			skip_ws()
			if pos < length and cleaned_str[pos] == ",":
				pos += 1
				skip_ws()
			elif pos < length and cleaned_str[pos] == "]":
				pass
			else:
				raise ValueError(f"Expected ',' or ']' at position {pos}")

	def parse_bool() -> bool:
		nonlocal pos
		if cleaned_str.startswith("true", pos):
			pos += 4
			return True
		if cleaned_str.startswith("false", pos):
			pos += 5
			return False
		raise ValueError(f"Unknown literal at position {pos}")

	def parse_null() -> None:
		nonlocal pos
		if cleaned_str.startswith("null", pos):
			pos += 4
			return None
		raise ValueError(f"Unknown literal at position {pos}")

	def parse_number_or_ident() -> Any:
		nonlocal pos
		start = pos
		if cleaned_str[pos] in ("-", "+"):
			pos += 1
		while pos < length and (
			cleaned_str[pos].isalnum() or cleaned_str[pos] in (".", "-", "+")
		):
			pos += 1
		raw = cleaned_str[start:pos]
		try:
			if "." in raw or "e" in raw or "E" in raw:
				return float(raw)
			if raw.startswith(("0x", "0X")):
				return int(raw, 16)
			return int(raw)
		except ValueError:
			return raw

	return parse_value()


DEFAULT_CONFIG_FILE_LOCATION: str = "~/.config/RAIkeep.json5"


def missing_configuration_diagnostic() -> str:
	"""
	CR044 §7.4: Standardized diagnostic when RAIkeep configuration is not found.
	Directs the operator to 'amafu init'.
	"""
	return (
		f"RAIkeep configuration was not found at '{DEFAULT_CONFIG_FILE_LOCATION}'. "
		"Run 'amafu init' to detect cloud providers and create it."
	)


class OsConfig:
	"""
	System configuration derived from ~/.config/RAIkeep.json5 or fallback files.
	Provides authoritative cloud drive paths, temporary directories, and backup paths.
	"""

	_instance: OsConfig | None = None

	def __init__(self, config_dict: dict[str, Any] | None = None, config_path: Path | None = None) -> None:
		self._config_path = config_path
		raw = config_dict or {}

		# TempDir
		raw_temp = raw.get("TempDir", "~/temp/")
		self.temp_dir: Path = self._normalize_path(raw_temp)

		# LocalBackupDir
		raw_backup = raw.get("LocalBackupDir")
		self.local_backup_dir: Path | None = self._normalize_path(raw_backup) if raw_backup else None

		# SyncPropagationDelayMs
		self.sync_propagation_delay_ms: int = int(raw.get("SyncPropagationDelayMs", 10000))

		# DefaultCloudOrder
		self.default_cloud_order: list[str] = list(
			raw.get("DefaultCloudOrder", ["OneDrive", "Dropbox", "GoogleDrive", "ICloudDrive"])
		)

		# Cloud roots
		self.clouds: dict[str, Path] = {}
		raw_cloud = raw.get("Cloud", {})
		if isinstance(raw_cloud, dict):
			for name, path_str in raw_cloud.items():
				if path_str:
					self.clouds[name] = self._normalize_path(str(path_str))

	@property
	def is_config_loaded(self) -> bool:
		"""Returns True if configuration was loaded from a file or explicit dictionary."""
		return self._config_path is not None or bool(self.clouds)

	@classmethod
	def reset(cls) -> None:
		"""Resets the singleton instance (used in tests)."""
		cls._instance = None

	@staticmethod
	def _normalize_path(p: str) -> Path:
		expanded = os.path.expanduser(p.strip())
		return Path(os.path.abspath(expanded))

	@staticmethod
	def find_config_file() -> Path | None:
		"""Locates the active configuration file according to ecosystem precedence."""
		# 1. Environment variable override
		for env_var in ("JSONPIT_CONFIG", "RAIKEEP_CONFIG"):
			val = os.getenv(env_var)
			if val:
				p = Path(os.path.expanduser(val))
				if p.is_file():
					return p

		# 2. Shared ecosystem ground truth: ~/.config/RAIkeep.json5
		raikeep = Path(os.path.expanduser("~/.config/RAIkeep.json5"))
		if raikeep.is_file():
			return raikeep

		# 3. Python-specific fallback: ~/.config/jsonpit.json5
		jsonpit_conf = Path(os.path.expanduser("~/.config/jsonpit.json5"))
		if jsonpit_conf.is_file():
			return jsonpit_conf

		# 4. XDG fallback: $XDG_CONFIG_HOME/jsonpit/config.json5
		xdg_config = os.getenv("XDG_CONFIG_HOME")
		if xdg_config:
			xdg_path = Path(os.path.expanduser(xdg_config)) / "jsonpit" / "config.json5"
			if xdg_path.is_file():
				return xdg_path

		return None

	@classmethod
	def load(cls, config_path: Path | str | None = None) -> OsConfig:
		"""Loads OsConfig from file or singleton instance."""
		if config_path is not None:
			p = Path(os.path.expanduser(str(config_path)))
			if p.is_file():
				data = loads_json5(p.read_text(encoding="utf-8"))
				return cls(data, config_path=p)
			raise FileNotFoundError(f"Configuration file not found: {p}")

		if cls._instance is not None:
			return cls._instance

		resolved_file = cls.find_config_file()
		if resolved_file and resolved_file.is_file():
			try:
				data = loads_json5(resolved_file.read_text(encoding="utf-8"))
				cls._instance = cls(data, config_path=resolved_file)
				return cls._instance
			except Exception:
				pass

		# Fallback default configuration
		cls._instance = cls({}, config_path=None)
		return cls._instance

	def get_cloud_root(self, cloud_name: str | None = None) -> Path | None:
		"""Returns the Path to the requested cloud drive root, or default."""
		if cloud_name:
			# Check case-insensitive match
			for k, v in self.clouds.items():
				if k.lower() == cloud_name.lower():
					return v
			return None
		# Use default cloud order
		for cloud in self.default_cloud_order:
			root = self.get_cloud_root(cloud)
			if root and root.exists():
				return root
		return None

	def is_cloud_path(self, path: Path | str) -> bool:
		"""Returns True if the target path is inside any known cloud drive root."""
		target = Path(os.path.abspath(os.path.expanduser(str(path))))
		for root in self.clouds.values():
			try:
				target.relative_to(root)
				return True
			except ValueError:
				continue
		return False
