import pytest
import os
import json
from unittest.mock import patch
from app.config import load_accounts, get_default_account
from ask_notion import show_auth_status

def test_load_accounts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTION_ACCOUNTS", "")
    with patch("os.path.exists", return_value=False):
        accounts = load_accounts()
        assert accounts == []

def test_get_default_account_raises_when_empty(monkeypatch):
    monkeypatch.setenv("NOTION_ACCOUNTS", "")
    with patch("app.config.load_accounts", return_value=[]):
        with pytest.raises(RuntimeError) as exc_info:
            get_default_account()
        assert "voyager-relay login" in str(exc_info.value)

def test_show_auth_status_with_accounts(capsys):
    mock_acc = [{
        "profile_name": "test-prof",
        "user_name": "Tester",
        "user_email": "test@example.com",
        "space_id": "space-123"
    }]
    with patch("app.config.load_accounts", return_value=mock_acc):
        rc = show_auth_status()
        assert rc == 0
        captured = capsys.readouterr().out
        assert "Tester" in captured
        assert "test@example.com" in captured
        assert "space-123" in captured

def test_show_auth_status_empty(capsys):
    with patch("app.config.load_accounts", return_value=[]):
        rc = show_auth_status()
        assert rc == 1
        captured = capsys.readouterr().out
        assert "Henüz bağlı bir Notion hesabı bulunamadı" in captured
