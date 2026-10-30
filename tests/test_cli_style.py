import contextlib
import io
import re

from jsonpit import cli_style as style
from jsonpit.cli import main
from jsonpit.icons import Icons


def strip(text: str) -> str:
	return re.sub(r"\x1b\[[0-9;]*m", "", text)


def cells(text: str) -> list[tuple[str, bool, bool]]:
	result = []
	color, italic, bold = "0", False, False
	for match in re.finditer(r"\x1b\[(?P<codes>[0-9;]+)m|(?P<text>[^\x1b]+)", text):
		if match["codes"]:
			for code in match["codes"].split(";"):
				if code == "0": color, italic, bold = "0", False, False
				elif code == "1": bold = True
				elif code == "3": italic = True
				else: color = code
		else:
			result.extend((color, italic, bold) for _ in match["text"])
	return result


def test_nested_syntax_and_uniform_switches() -> None:
	text = "<tenant|path> (<PitName>|--wwwa) [-c <cloud>] [-a|--all] 'jpit -r <root>'"
	colored = style.syntax(text)
	assert strip(colored) == text
	assert style.syntax(text, enabled=False) == text
	decoded = cells(colored)
	for word, color in [("tenant", "96"), ("PitName", "35"), ("cloud", "96"), ("root", "96")]:
		assert decoded[text.index(word)] == (color, True, False)
	for switch in ["--wwwa", "-c", "-a", "--all", "-r"]:
		assert decoded[text.index(switch)] == ("32", False, False)
	for i, ch in enumerate(text):
		if ch in "<>|": assert decoded[i] == ("36", False, False)
	assert decoded[text.index("jpit")] == ("33", False, False)
	assert decoded[text.index("[")][0] == "94"


def test_banner_and_glyph_groups() -> None:
	title = f"{Icons.INFO} jsonpit CLI (jpit v1.2.3)"
	assert strip(style.banner(title, True)[1]) == title
	assert all(bold for _, _, bold in cells(style.banner(title, True)[1]))
	long_title = Icons.INFO + " " + "x" * 80
	assert len(strip(style.banner(long_title, True)[0])) == len(long_title)
	icons = [Icons.HELP, Icons.INFO, Icons.BANNER, Icons.FOLDER, Icons.FILE, Icons.DOWNLOAD]
	assert len({style.glyph_color(icon) for icon in icons}) == len(icons)
	rows = [style.Row("-h, --help", Icons.HELP, "print help"),
		style.Row("--retain-window", Icons.INFO, "retain the window")]
	plain = style.rows(rows, False)
	assert [strip(line) for line in style.rows(rows, True)] == plain
	assert all("\t" not in line and line[17] in icons for line in plain)


def test_cloud_badges_keep_the_positional_palette() -> None:
	providers = ["OneDrive", "Dropbox", "GoogleDrive", "ICloudDrive", "GoogleDriveOther"]
	colored = style.cloud_options(providers, True)
	assert strip(colored) == style.cloud_options(providers, False)
	for i, provider in enumerate(providers):
		assert f"\033[{style.BADGE_COLORS[i]}m{Icons.cloud_provider_icon(provider, i + 1)}\033[0m" in colored


def test_redirected_help_is_plain_and_aligned(monkeypatch) -> None:
	monkeypatch.delenv("NO_COLOR", raising=False)
	monkeypatch.setenv("TERM", "xterm-256color")
	for args in [["-h", "-n"], ["put", "-h", "-n"], ["--retain-window", "-h", "-n"]]:
		output = io.StringIO()
		with contextlib.redirect_stdout(output): assert main(args) == 0
		assert "\t" not in output.getvalue()
		assert "\033" not in output.getvalue()


def test_color_controls(monkeypatch) -> None:
	from jsonpit.cli import should_color
	output = io.StringIO()
	output.isatty = lambda: True
	with contextlib.redirect_stdout(output):
		monkeypatch.setenv("TERM", "xterm-256color")
		monkeypatch.delenv("NO_COLOR", raising=False)
		assert should_color()
		monkeypatch.setenv("NO_COLOR", "1")
		assert not should_color()
		monkeypatch.delenv("NO_COLOR")
		monkeypatch.setenv("TERM", "dumb")
		assert not should_color()


def test_shared_option_aliases_and_hidden_compatibility_names() -> None:
	from jsonpit.cli import build_parser, extract_cloud_and_root
	for option in ["-w", "--window", "--retain-window"]:
		for args in [[option, "status", "Person"], ["status", "Person", option]]:
			assert build_parser().parse_args(args).retain_window
	for option in ["-x", "--id-exists", "--require-exist", "--require-existing"]:
		assert build_parser().parse_args(["seed", "Person", "-", option]).require_existing
	assert build_parser().parse_args(["list", "--pitroot", "/example"]).root == "/example"
	assert extract_cloud_and_root(["--pitroot=/example"]) == (None, "/example")
	for args in [["-h", "-n"], ["seed", "-h", "-n"]]:
		output = io.StringIO()
		with contextlib.redirect_stdout(output): assert main(args) == 0
		assert "--retain-window" not in output.getvalue()
		assert "--require-exist" not in output.getvalue()
		assert "positional argument:" not in output.getvalue()
	output = io.StringIO()
	with contextlib.redirect_stdout(output): assert main(["Activity", "-h", "-n"]) == 0
	assert "positional argument:" in output.getvalue()
	assert "jpit seed Activity --source" in output.getvalue()


def test_list_alias_is_advertised_only_in_contextual_help() -> None:
	output = io.StringIO()
	with contextlib.redirect_stdout(output): assert main(["-h", "-n"]) == 0
	assert "list (ls)" not in output.getvalue()
	for command in ["list", "ls"]:
		output = io.StringIO()
		with contextlib.redirect_stdout(output): assert main([command, "-h", "-n"]) == 0
		assert "Usage: jpit list" in output.getvalue()
		assert "       jpit ls" in output.getvalue()
