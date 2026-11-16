"""Keep the suite independent of operator credentials, state and upstream services."""

import atexit
import json
import os
import socket
import tempfile
from pathlib import Path

import pytest

_state = tempfile.TemporaryDirectory(prefix="notion2api-tests-")
atexit.register(_state.cleanup)
os.environ["NOTION2API_HOME"] = _state.name
os.environ["DB_PATH"] = str(Path(_state.name) / "conversations.db")
os.environ["API_KEY"] = "synthetic-test-key"
os.environ["SILICONFLOW_API_KEY"] = ""
os.environ["NOTION_ACCOUNTS"] = json.dumps([{
    "profile_name": "test", "token_v2": "synthetic", "space_id": "test-space",
    "user_id": "test-user", "user_name": "Tester", "user_email": "tester@example.invalid",
}])


@pytest.fixture(autouse=True)
def no_upstream_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must mock upstream connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)
