"""Installed commands must work outside the checkout without consulting credentials."""

import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import zipfile

import pytest

from app.paths import state_dir

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("arguments", [["--help"], ["--list-models"]])
def test_source_offline_commands_without_site_packages(tmp_path, arguments):
    # -S removes third-party dependencies. Invalid credentials would fail if read.
    (tmp_path / "accounts.json").write_text("not valid JSON", encoding="utf-8")
    (tmp_path / ".env").write_text("NOTION_ACCOUNTS=not-valid-json", encoding="utf-8")
    env = dict(os.environ, NOTION2API_HOME=str(tmp_path), NOTION_ACCOUNTS="not-valid-json",
               PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-S", str(ROOT / "ask_notion.py"), *arguments],
                            cwd=tmp_path, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert "voyager-relay" in result.stdout or "auto" in result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env", "accounts.json"]


@pytest.mark.parametrize("name", ["notion-ai", "voyager-relay", "notion-ai-server"])
def test_installed_entrypoints_have_account_free_help(tmp_path, name):
    scripts = Path(sysconfig.get_path("scripts"))
    command = scripts / (name + (".exe" if os.name == "nt" else ""))
    assert command.is_file(), "Install the project with pip install -e .[dev] before testing"
    result = subprocess.run([str(command), "--help"], cwd=tmp_path,
                            env=dict(os.environ, NOTION2API_HOME=str(tmp_path),
                                     NOTION_ACCOUNTS="invalid", PYTHONIOENCODING="utf-8"),
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_explicit_state_root_is_used_without_creating_it(tmp_path, monkeypatch):
    target = tmp_path / "operator state"
    monkeypatch.setenv("NOTION2API_HOME", str(target))
    assert state_dir() == target
    assert not target.exists()


def test_explicit_environment_is_not_overridden_by_dotenv(tmp_path):
    (tmp_path / ".env").write_text("NOTION_ACCOUNTS=invalid\n", encoding="utf-8")
    env = dict(os.environ, NOTION2API_HOME=str(tmp_path),
               NOTION_ACCOUNTS='[{"token_v2":"synthetic","space_id":"test","user_id":"test"}]')
    result = subprocess.run([sys.executable, "-c",
                             "from app.config import load_accounts; print(len(load_accounts()))"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_distribution_metadata_has_both_cli_aliases():
    import importlib.metadata

    distribution = importlib.metadata.distribution("notion2api")
    commands = {e.name: e.value for e in distribution.entry_points if e.group == "console_scripts"}
    assert commands["notion-ai"] == commands["voyager-relay"] == "ask_notion:main"


def test_masked_login_never_falls_back_to_echoed_input(monkeypatch):
    import getpass
    import login

    def unavailable(*args, **kwargs):
        raise OSError("no terminal")

    def echoed_input(*args, **kwargs):
        raise AssertionError("Credential input must never be echoed")

    monkeypatch.setattr(getpass, "getpass", unavailable)
    monkeypatch.setattr("builtins.input", echoed_input)
    with pytest.raises(RuntimeError, match="Masked input unavailable"):
        login._prompt_token()


def test_built_wheel_contains_frontend_when_requested():
    # Packaging CI sets this to the actual built wheel, not a source-tree surrogate.
    wheel = os.getenv("NOTION2API_TEST_WHEEL")
    if not wheel:
        pytest.skip("Set NOTION2API_TEST_WHEEL to inspect the built distribution")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "frontend/index.html" in names
    assert "frontend/js/core/app.js" in names
    assert "frontend/css/main.css" in names
    assert "app/paths.py" in names
    assert not any(n.endswith(("accounts.json", ".env", ".db")) for n in names)
