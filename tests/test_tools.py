import json
import sys

import pytest

from app.tools import (
    _resolve_path,
    is_safe_path,
    tool_read_file_range,
    tool_run_command,
    tool_write_file,
)


def test_resolve_path_within_workspace(tmp_path):
    sub_file = tmp_path / "test.txt"
    sub_file.write_text("hello", encoding="utf-8")
    
    resolved = _resolve_path("test.txt", base_dir=str(tmp_path))
    assert resolved == sub_file.resolve()


def test_resolve_path_traversal_denied(tmp_path):
    # Attempting to escape base_dir via ..
    with pytest.raises(PermissionError) as exc_info:
        _resolve_path("../outside.txt", base_dir=str(tmp_path))
    assert "Yol izin verilen çalışma alanının dışında" in str(exc_info.value)


def test_is_safe_path(tmp_path):
    assert is_safe_path("safe.txt", base_dir=str(tmp_path)) is True
    assert is_safe_path("../../escape.txt", base_dir=str(tmp_path)) is False
    assert is_safe_path("", base_dir=str(tmp_path)) is False


def test_tool_write_and_read_confined(tmp_path, monkeypatch):
    monkeypatch.setattr("app.tools.WORKSPACE_ROOT", tmp_path)
    
    # Write a file
    res_raw = tool_write_file("hello.txt", "line1\nline2\n")
    res = json.loads(res_raw)
    assert res["ok"] is True
    
    # Read the file
    read_raw = tool_read_file_range("hello.txt", 1, 10)
    read_res = json.loads(read_raw)
    assert read_res["ok"] is True
    assert "line1\nline2\n" in read_res["data"]["content"]
    
    # Attempt write outside workspace
    escape_raw = tool_write_file("../escape.txt", "bad")
    escape_res = json.loads(escape_raw)
    assert escape_res["ok"] is False
    assert escape_res["code"] == "PATH_DENIED"


def test_tool_run_command_echo(monkeypatch, tmp_path):
    monkeypatch.setattr("app.tools.WORKSPACE_ROOT", tmp_path)
    
    res_raw = tool_run_command("echo test_output_123")
    res = json.loads(res_raw)
    assert res["ok"] is True
    assert "test_output_123" in res["data"]["stdout"]


def test_tool_run_command_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("app.tools.WORKSPACE_ROOT", tmp_path)
    
    cmd = "dir" if sys.platform == "win32" else "ls"
    res_raw = tool_run_command(cmd)
    res = json.loads(res_raw)
    assert res["ok"] is True
    assert res["data"]["returncode"] == 0


def test_tool_run_command_denied():
    res_raw = tool_run_command("curl http://example.com")
    res = json.loads(res_raw)
    assert res["ok"] is False
    assert res["code"] == "COMMAND_DENIED"
