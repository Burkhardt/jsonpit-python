"""
Nerd Font glyph iconography for jsonpit CLI.
100% parity with C# pits Icons class in RAIkeep/PitSeeder/pits/Program.cs.
Zero third-party runtime dependencies.
"""

from __future__ import annotations


class Icons:
	"""Nerd Font glyph code points matching C# pits."""
	ERROR: str = "\uea87"         #  (Codicon: error)
	WARNING: str = "\uf071"       #  (FontAwesome: warning)
	SUCCESS: str = "\ueab2"       #  (Codicon: check/pass)
	INFO: str = "\uea74"          #  (Codicon: info)
	HELP: str = "\uf059"          #  (FontAwesome: question-circle)
	NOT_AVAILABLE: str = "\ueabd" #  (Codicon: circle-slash)
	FILE: str = "\uea7b"          #  (Codicon: file)
	FOLDER: str = "\uea83"        #  (Codicon: folder)
	DOWNLOAD: str = "\ueac2"      #  (Codicon: cloud-download)
	UPLOAD: str = "\ueac3"        #  (Codicon: cloud-upload)
	BANNER: str = "\ueb1e"        #  (Codicon: megaphone/banner)
	NO_BANNER: str = "\ueb24"     #  (Codicon: mute-banner)

	# Material Design Icons: Cloud Providers
	DROPBOX: str = "\U000F0BF4"      # 󰯴 (Dropbox box outline)
	GOOGLE_DRIVE: str = "\U000F0BFD" # 󰯽 (Google Drive box outline)
	ICLOUD_DRIVE: str = "\U000F0C03" # 󰰃 (iCloud box outline)
	ONE_DRIVE: str = "\U000F0C15"    # 󰰕 (OneDrive box outline)

	HELP_LINE_WIDTH_COMPENSATION: str = "  "
	NUMBER_BOX_OUTLINES: list[str] = [
		"\U000F03A6", "\U000F03A9", "\U000F03AC", "\U000F03AE", "\U000F03B0",
		"\U000F03B5", "\U000F03B8", "\U000F03BB", "\U000F03BE",
	]

	@classmethod
	def cloud_provider_icon(cls, provider: str, fallback_number: int = 1) -> str:
		"""Returns the specific brand glyph for a cloud provider."""
		p = provider.lower()
		if p == "dropbox":
			return cls.DROPBOX
		if p == "googledrive":
			return cls.GOOGLE_DRIVE
		if p == "iclouddrive":
			return cls.ICLOUD_DRIVE
		if p == "onedrive":
			return cls.ONE_DRIVE
		if 1 <= fallback_number <= len(cls.NUMBER_BOX_OUTLINES):
			return cls.NUMBER_BOX_OUTLINES[fallback_number - 1]
		return f"({fallback_number})"

	@classmethod
	def letter_box_outline(cls, char: str) -> str:
		"""Returns the Material Design alpha-box-outline glyph for any letter A-Z."""
		if not char:
			return ""
		c = char[0].upper()
		if "A" <= c <= "Z":
			cp = 0xF0BEB + (ord(c) - ord("A")) * 3
			return chr(cp)
		return f"[{c}]"

