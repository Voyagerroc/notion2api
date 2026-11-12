from unittest.mock import MagicMock

from app.conversation import ConversationManager
from app.notion_client import NotionOpusAPI
from ask_notion import resolve_model


def test_resolve_model_defaults_to_auto():
    assert resolve_model("") == "auto"
    assert resolve_model("auto") == "auto"
    assert resolve_model("default") == "auto"
    assert resolve_model("opus") == "claude-opus4.6"
    assert resolve_model("sonnet") == "claude-sonnet4.6"

def test_build_config_block_auto_sets_model_from_user_false():
    cm = ConversationManager()
    cfg = cm._build_config_block("auto")
    assert cfg["value"]["model"] == "auto"
    assert cfg["value"]["modelFromUser"] is False

    cfg_opus = cm._build_config_block("claude-opus4.6")
    assert cfg_opus["value"]["model"] == "claude-opus4.6"
    assert cfg_opus["value"]["modelFromUser"] is True

def test_agent_create_thread_fallback_on_429():
    account = {
        "token_v2": "fake-token",
        "space_id": "fake-space",
        "user_id": "fake-user",
        "space_view_id": "fake-view",
    }
    client = NotionOpusAPI(account)
    session = MagicMock()

    # First call fails with 429 Rate Limit, second succeeds with 200
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = '{"type":"error","subType":"rate_limit_exceeded"}'

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200

    session.post.side_effect = [mock_resp_429, mock_resp_200]

    thread_id = client._agent_create_thread(session, "t-123", "prompt", "claude-opus4.6")
    assert thread_id is not None
    assert session.post.call_count == 2
    
    # Second post should have had model removed (Auto mode)
    call_payload = session.post.call_args_list[1][1]["json"]
    assert "model" not in call_payload

def test_agent_create_thread_fallback_on_model_not_supported():
    account = {
        "token_v2": "fake-token",
        "space_id": "fake-space",
        "user_id": "fake-user",
    }
    client = NotionOpusAPI(account)
    session = MagicMock()

    mock_resp_400 = MagicMock()
    mock_resp_400.status_code = 400
    mock_resp_400.text = "Workspace does not support selected model: avocado-froyo"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200

    session.post.side_effect = [mock_resp_400, mock_resp_200]

    thread_id = client._agent_create_thread(session, "t-456", "prompt", "avocado-froyo-medium")
    assert thread_id is not None
    assert session.post.call_count == 2
    call_payload = session.post.call_args_list[1][1]["json"]
    assert "model" not in call_payload
