"""CR082: tenant resolution and honest missing-snapshot export failures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jsonpit.cli import main
from jsonpit.audit import PitAudit
from jsonpit.config import OsConfig


def snapshot(root: Path, name: str = "Object", item_id: str = "CloudItem") -> Path:
	path = root / name / f"{name}.pit"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps([[{"Id": item_id, "Name": item_id}]]), encoding="utf-8")
	return path


@pytest.fixture
def clouds(tmp_path, monkeypatch):
	one, google = tmp_path / "OneDrive", tmp_path / "GoogleDrive"
	one.mkdir()
	google.mkdir()
	config = OsConfig({"Cloud": {"OneDrive": str(one), "GoogleDrive": str(google)},
		"DefaultCloudOrder": ["OneDrive", "GoogleDrive"]})
	monkeypatch.setattr(OsConfig, "_instance", config)
	monkeypatch.chdir(tmp_path)
	snapshot(one / "AfricaStage")
	snapshot(google / "AfricaStage", item_id="OtherCloudItem")
	return one, google, config


@pytest.mark.parametrize("root_option", ["-r", "--pitroot", "--root"])
def test_export_uses_configured_default_and_explicit_cloud_override(clouds, tmp_path, capsys, root_option):
	for options, expected in [([], "CloudItem"), (["-c", "GoogleDrive"], "OtherCloudItem")]:
		assert main(["export", "Object", root_option, "AfricaStage", "--json", *options]) == 0
		result = capsys.readouterr()
		assert json.loads(result.out)[0]["Id"] == expected
		assert result.err == ""
	assert not (tmp_path / "AfricaStage").exists()


def test_directory_export_and_timestamp_use_default_cloud(clouds, tmp_path, capsys):
	destination = tmp_path / "exports"
	assert main(["export", "Object", "-r", "AfricaStage", "--out-dir", str(destination),
		"--at", "2030-01-01T00:00:00Z"]) == 0
	assert json.loads((destination / "Object.json").read_text())["data"][0]["Id"] == "CloudItem"
	assert "Exported Object" in capsys.readouterr().out


@pytest.mark.parametrize("command", [
	["get", "Object", "CloudItem"], ["history", "Object", "CloudItem"],
	["list", "Object", "--json"], ["status", "Object"],
	["grep", "CloudItem", "Object", "--json"], ["grep", "CloudItem", "--json"],
	["list", "--json"], ["export", "Object", "--json"],
	["audit", "--wwwa", "--json"], ["maintain", "--wwwa", "--json"],
	["audit", "Object", "--json"], ["maintain", "Object", "--json"],
])
def test_read_commands_do_not_select_same_named_local_directory(clouds, tmp_path, capsys, monkeypatch, command):
	one, _, _ = clouds
	snapshot(tmp_path / "AfricaStage", item_id="LocalDecoy")
	inspected = []
	original_inspect = PitAudit.inspect
	def inspect(directory, **kwargs):
		inspected.append(directory)
		return original_inspect(directory, **kwargs)
	monkeypatch.setattr(PitAudit, "inspect", inspect)
	assert main([*command, "-r", "AfricaStage"]) == 0
	result = capsys.readouterr()
	assert "LocalDecoy" not in result.out
	assert result.err == ""
	if command[0] not in ("audit", "maintain"):
		assert "CloudItem" in result.out or str(one / "AfricaStage") in result.out
	else:
		assert str(tmp_path / "AfricaStage") not in result.out
	if command[0] == "audit":
		names = ["Person", "Object", "Place", "Activity"] if "--wwwa" in command else ["Object"]
		assert inspected == [one / "AfricaStage" / name for name in names]
	assert not list(one.rglob("*.flag"))


def test_default_cloud_order_is_configured_not_hardcoded(clouds, capsys):
	_, _, config = clouds
	config.default_cloud_order = ["GoogleDrive", "OneDrive"]
	assert main(["export", "Object", "-r", "AfricaStage", "--json"]) == 0
	assert json.loads(capsys.readouterr().out)[0]["Id"] == "OtherCloudItem"


@pytest.mark.parametrize("root_form", ["absolute", "relative", "home"])
def test_explicit_local_roots_work_without_config(tmp_path, monkeypatch, capsys, root_form):
	monkeypatch.setattr(OsConfig, "_instance", OsConfig({}))
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv("HOME", str(tmp_path))
	snapshot(tmp_path / "LocalTenant", item_id="LocalItem")
	root = {"absolute": str(tmp_path / "LocalTenant"), "relative": "./LocalTenant", "home": "~/LocalTenant"}[root_form]
	assert main(["export", "Object", "-r", root, "--json"]) == 0
	assert json.loads(capsys.readouterr().out)[0]["Id"] == "LocalItem"


@pytest.mark.parametrize("output_mode", ["json", "directory", "file", "jq"])
@pytest.mark.parametrize("source_form", ["tenant", "directory", "file"])
def test_missing_snapshot_fails_without_output_or_destination_changes(clouds, tmp_path, capsys, output_mode, source_form):
	one, _, _ = clouds
	missing = one / "AfricaStage" / "Missing" / "Missing.pit"
	missing.parent.mkdir()
	source = {"tenant": ["Missing", "-r", "AfricaStage"], "directory": [str(missing.parent)],
		"file": [str(missing)]}[source_form]
	destination = tmp_path / "exports"
	destination.mkdir()
	existing = destination / "Missing.json"
	existing.write_text("preserve existing export", encoding="utf-8")
	mode = {"json": ["--json"], "directory": ["--out-dir", str(destination)],
		"file": ["--out", str(existing)], "jq": ["--jq", "."]}[output_mode]
	assert main(["export", *source, *mode]) == 1
	result = capsys.readouterr()
	assert result.out == ""
	assert "does not exist" in result.err and str(missing) in result.err
	assert existing.read_text() == "preserve existing export"
	assert not list(one.rglob("*.flag"))


def test_missing_wwwa_member_fails_without_creating_output_directory(clouds, tmp_path, capsys):
	one, _, _ = clouds
	snapshot(one / "AfricaStage", "Person")
	destination = tmp_path / "not-created"
	assert main(["export", "--wwwa", "-r", "AfricaStage", "--out-dir", str(destination)]) == 1
	result = capsys.readouterr()
	assert result.out == "" and "Place.pit" in result.err
	assert not destination.exists()


def test_existing_empty_snapshot_is_a_successful_empty_export(clouds, capsys):
	one, _, _ = clouds
	(one / "AfricaStage" / "Object" / "Object.pit").write_text("[]", encoding="utf-8")
	assert main(["export", "Object", "-r", "AfricaStage", "--json"]) == 0
	result = capsys.readouterr()
	assert json.loads(result.out) == [] and result.err == ""


def test_complete_wwwa_export_uses_default_cloud(clouds, capsys):
	one, _, _ = clouds
	for name in ("Person", "Place", "Activity"):
		snapshot(one / "AfricaStage", name, item_id=name)
	assert main(["export", "--wwwa", "-r", "AfricaStage", "--json"]) == 0
	result = capsys.readouterr()
	assert set(json.loads(result.out)) == {"Person", "Object", "Place", "Activity"}
	assert result.err == ""


def test_explicit_missing_cloud_does_not_fall_back_to_default(clouds, capsys):
	assert main(["export", "Object", "-r", "AfricaStage", "-c", "UnknownDrive", "--json"]) == 1
	result = capsys.readouterr()
	assert result.out == "" and "UnknownDrive" in result.err


@pytest.mark.parametrize("configuration", ["missing", "unavailable"])
def test_no_cloud_never_falls_back_to_local_tenant(tmp_path, monkeypatch, capsys, configuration):
	config = OsConfig({} if configuration == "missing" else {"Cloud": {"OneDrive": str(tmp_path / "offline")}})
	monkeypatch.setattr(OsConfig, "_instance", config)
	monkeypatch.chdir(tmp_path)
	snapshot(tmp_path / "AfricaStage", item_id="LocalDecoy")
	assert main(["export", "Object", "-r", "AfricaStage", "--json"]) == 1
	result = capsys.readouterr()
	assert result.out == ""
	assert "amafu init" in result.err if configuration == "missing" else "default" in result.err


@pytest.mark.parametrize("command", [
	["seed", "Object", "--source", "-"], ["put", "Object", "--source", "-"],
	["set", "Object", "CloudItem", '{"Name":"changed"}'],
	["del", "Object", "CloudItem"], ["delete", "Object", "CloudItem"],
	["delete-item", "Object", "CloudItem"], ["del-prop", "Object", "CloudItem", "Name"],
	["delete-property", "Object", "CloudItem", "Name"], ["rename", "Object", "CloudItem", "NewId"],
	["maintain", "Object", "--apply"], ["maintain", "--wwwa", "--apply"],
])
def test_cr069_explicit_write_destination_is_still_required(clouds, tmp_path, capsys, command):
	one, _, _ = clouds
	cloud_file = one / "AfricaStage" / "Object" / "Object.pit"
	local_file = snapshot(tmp_path / "AfricaStage", item_id="LocalDecoy")
	before = cloud_file.read_bytes(), local_file.read_bytes()
	assert main([*command, "-r", "AfricaStage"]) == 1
	result = capsys.readouterr()
	assert "Supply -c <provider> or an explicit local directory path" in result.err
	assert result.out == ""
	assert (cloud_file.read_bytes(), local_file.read_bytes()) == before
	assert not list(one.rglob("*.flag"))


def test_missing_first_default_provider_uses_next_available_provider(clouds, capsys):
	one, _, config = clouds
	config.clouds["OneDrive"] = one / "offline"
	assert main(["export", "Object", "-r", "AfricaStage", "--json"]) == 0
	assert json.loads(capsys.readouterr().out)[0]["Id"] == "OtherCloudItem"
