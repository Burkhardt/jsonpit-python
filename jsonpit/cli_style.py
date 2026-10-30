"""Help rendering contract: https://github.com/Burkhardt/RAIkeep/blob/main/doc/cli-style.md.

Keep behavior aligned with the dependency-free OsLib/CliHelpStyle.cs formatter.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .icons import Icons

BADGE_COLORS = ["96", "92", "94", "91", "35", "95", "36", "34"]
_SWITCH = re.compile(r"(?<![\w/\-])--?[A-Za-z][A-Za-z0-9-]*")


def paint(text: str, color: str, enabled: bool) -> str:
	return f"\033[{color}m{text}\033[0m" if enabled else text


def glyph_color(icon: str) -> str:
	return {
		Icons.FOLDER: "33", Icons.HELP: "32", Icons.BANNER: "95", Icons.NO_BANNER: "95",
		Icons.INFO: "36", Icons.FILE: "35", Icons.DOWNLOAD: "34", Icons.UPLOAD: "34",
		Icons.SUCCESS: "92", Icons.NOT_AVAILABLE: "91", Icons.WARNING: "93", Icons.ERROR: "31",
	}.get(icon, "36")


def syntax(text: str, base_color: str = "36", enabled: bool = True) -> str:
	if not enabled or not text:
		return text
	colors = [base_color] * len(text)
	italic = [False] * len(text)
	groups: list[tuple[int, int, str, bool]] = []
	opened: list[tuple[int, str]] = []
	quote = -1
	for i, ch in enumerate(text):
		if ch == "'":
			if quote < 0:
				quote = i
			else:
				colors[quote + 1:i] = ["33"] * (i - quote - 1)
				quote = -1
		if ch in "<([":
			opened.append((i, ch))
		elif ch in ">)]":
			expected = {">": "<", ")": "(", "]": "["}[ch]
			if opened and opened[-1][1] == expected:
				start, kind = opened.pop()
				depth = 0
				choice = False
				if kind == "(":
					for inner in text[start + 1:i]:
						if inner in "<([": depth += 1
						elif inner in ">)]": depth -= 1
						elif inner == "|" and depth == 0: choice = True
				groups.append((start, i, kind, choice))
	for start, end, kind, choice in sorted(groups, key=lambda g: g[1] - g[0], reverse=True):
		if kind == "<":
			in_choice = any(c and a < start and b > end for a, b, _, c in groups)
			colors[start + 1:end] = ["35" if in_choice else "96"] * (end - start - 1)
			italic[start + 1:end] = [True] * (end - start - 1)
		elif kind == "[" or choice:
			colors[start:end + 1] = ["35" if choice else "94"] * (end - start + 1)
	for i, ch in enumerate(text):
		if ch in "<>|":
			colors[i], italic[i] = base_color, False
	for match in _SWITCH.finditer(text):
		colors[match.start():match.end()] = ["32"] * len(match.group())
	result: list[str] = []
	start = 0
	while start < len(text):
		end = start + 1
		while end < len(text) and colors[end] == colors[start] and italic[end] == italic[start]: end += 1
		result.append(paint(text[start:end], colors[start] + (";3" if italic[start] else ""), True))
		start = end
	return "".join(result)


def cloud_options(providers: list[str], enabled: bool) -> str:
	if not providers:
		return paint("no DefaultCloudOrder providers are configured", "33", enabled)
	return paint(", ", "33", enabled).join(
		paint(Icons.cloud_provider_icon(name, i + 1), BADGE_COLORS[i % len(BADGE_COLORS)], enabled)
		+ paint(" " + name, "33", enabled) for i, name in enumerate(providers)
	)


@dataclass(frozen=True)
class Row:
	label: str
	icon: str
	description: str
	providers: list[str] | None = None


def rows(items: list[Row], enabled: bool) -> list[str]:
	width = max((len(row.label) for row in items if row.icon), default=0)
	result = []
	for row in items:
		if not row.icon:
			result.append(syntax(row.label, enabled=enabled))
			continue
		base = glyph_color(row.icon)
		desc = cloud_options(row.providers, enabled) if row.providers is not None else syntax(row.description, base, enabled)
		result.append(syntax(row.label.ljust(width), base, enabled) + "  "
			+ paint(row.icon.ljust(2), base, enabled) + "  " + desc)
	return result


def banner(title: str, enabled: bool) -> list[str]:
	rule = Icons.BANNER + " " + "─" * max(40, len(title) - 2)
	return [paint(rule, "36", enabled), paint(title, "1;36", enabled), paint(rule, "36", enabled)]
